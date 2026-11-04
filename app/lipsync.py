"""Optional local English audio/transcript alignment, isolated from inference.

The worker runs in a separate process, so recognition cannot block the mic or
WebSocket loop. No equal-duration word estimates or volume-to-mouth rules are
used. PocketSphinx 5.0.4 includes native Python 3.12 Apple Silicon wheels.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ProcessPoolExecutor
import importlib.util
import multiprocessing
import math
from pathlib import Path
import re
import time

RATE = 24000
PHONE_POSE = {
    "SIL": 0, "+SPN+": 0, "+NSN+": 0,
    "P": 1, "B": 1, "M": 1, "F": 2, "V": 2, "TH": 3, "DH": 3,
    "T": 4, "D": 4, "K": 5, "G": 5, "NG": 5,
    "CH": 6, "SH": 6, "JH": 6, "ZH": 6, "S": 7, "Z": 7,
    "N": 8, "L": 8, "R": 9, "ER": 9, "AA": 10, "AE": 10, "AH": 10,
    "EH": 11, "IY": 12, "IH": 12, "Y": 12, "AO": 13,
    "UH": 14, "UW": 14, "W": 14,
}
DIPHTHONGS = {"AW": (10, 14), "AY": (10, 12), "EY": (11, 12), "OW": (13, 14), "OY": (13, 12)}
_decoder = None
_phone_decoder = None


class AlignmentTimingError(RuntimeError):
    @property
    def timing_reason(self):
        return str(self)


def available():
    return importlib.util.find_spec("pocketsphinx") is not None


def timing_issue(phones, samples, rate=RATE):
    """Use audio energy only to reject missing timing, never to invent poses."""
    import numpy as np
    duration = len(samples) / rate
    if not phones:
        return 'empty'
    step = max(1, round(rate * .02))
    padded = np.pad(np.asarray(samples, dtype=np.float32), (0, (-len(samples)) % step))
    rms = np.sqrt(np.mean(padded.reshape(-1, step) ** 2, axis=1))
    active = rms > max(80, float(np.percentile(rms, 90)) * .08)
    covered = np.zeros(len(active), dtype=bool)
    last_end = 0.0
    for phone, start, end in phones:
        if not math.isfinite(start) or not math.isfinite(end) or start < -.02 or end <= start or end > duration + .08 or start < last_end - .03:
            return 'invalid-boundaries'
        last_end = end
        phone = re.sub(r'\d+$', '', phone.upper())
        if phone in ('SIL', '+SPN+', '+NSN+', '<SIL>', '<S>', '</S>'):
            continue
        if end - start > 1.2:
            return 'held-phone'
        # Small edge tolerance avoids treating decoder frame rounding as a gap.
        left, right = max(0, int((start - .04) / .02)), min(len(active), math.ceil((end + .04) / .02))
        covered[left:right] = True
    run = 0
    for missing in active & ~covered:
        run = run + 1 if missing else 0
        if run >= 18:
            return 'uncovered-speech'
    return None


def align(pcm: bytes, text: str) -> dict:
    """Return real phone/word boundaries in seconds relative to this PCM segment."""
    import numpy as np
    from scipy.signal import resample_poly
    from pocketsphinx import Decoder, get_model_path

    global _decoder, _phone_decoder
    if len(pcm) % 2 or not 0 < len(pcm) <= RATE * 2 * 45:
        raise ValueError("Alignment expects at most 45 seconds of mono 24 kHz int16 PCM")
    started = time.monotonic()
    samples = np.frombuffer(pcm, dtype="<i2")
    audio = np.clip(np.rint(resample_poly(samples.astype(np.float32), 2, 3)), -32768, 32767).astype("<i2").tobytes()
    duration = len(samples) / RATE
    if _decoder is None:
        _decoder = Decoder(samprate=16000, lm=None, loglevel="ERROR")
    words = re.findall(r"[a-z]+(?:'[a-z]+)*", re.sub(r"<\|.*?\|>|\((?:laugh|sigh|cough|clears throat)\)", " ", text.lower()))
    unknown = [w for w in words if not _decoder.lookup_word(w)]
    # Digits need the TTS engine's spoken normalization to force-align safely.
    forced = bool(words) and not unknown and not re.search(r"\d", text)

    def decode(decoder):
        decoder.start_utt()
        decoder.process_raw(audio, full_utt=True)
        decoder.end_utt()

    word_cues = []
    fallback_reason = None
    if forced:
        try:
            _decoder.set_align_text(" ".join(words))
            decode(_decoder)
            _decoder.set_alignment()
            decode(_decoder)
            alignment = _decoder.get_alignment()
            if alignment is None:
                raise RuntimeError("No phoneme alignment for this audio")
            phones = [(p.name, p.start / 100, (p.start + p.duration) / 100) for p in alignment.phones()]
            if not phones:
                raise RuntimeError("Empty phoneme alignment")
            issue = timing_issue(phones, samples)
            if issue:
                fallback_reason = 'forced-' + issue
                raise ValueError('Incomplete or implausible forced timing')
            word_cues = [{"word": w.name, "start": w.start / 100, "end": (w.start + w.duration) / 100}
                         for w in alignment if w.name not in ("<sil>", "<s>", "</s>")]
        except (RuntimeError, ValueError):
            # A known word list can still fail to match synthesized speech.
            # Discard the failed decoder state and align the same PCM acoustically.
            _decoder = None
            forced = False
            fallback_reason = fallback_reason or "forced-alignment-failed"
    if not forced:
        # The bundled lexicon cannot cover all names/numbers. Use acoustic
        # phoneme recognition for those segments, and label it as less accurate.
        if _phone_decoder is None:
            model = Path(get_model_path()) / "en-us" / "en-us-phone.lm.bin"
            # Narrow pruning can collapse the remaining clause into one held
            # phone. Keep enough acoustic hypotheses to cover the full clip.
            _phone_decoder = Decoder(samprate=16000, lm=None, allphone=str(model),
                                     beam=1e-48, pbeam=1e-48, loglevel="ERROR")
        decode(_phone_decoder)
        phones = [(p.word, p.start_frame / 100, (p.end_frame + 1) / 100) for p in _phone_decoder.seg()]
        issue = timing_issue(phones, samples)
        if issue:
            _phone_decoder = None
            raise AlignmentTimingError('acoustic-' + issue)
    cues = []
    for i, (phone, start, end) in enumerate(phones):
        phone = re.sub(r"\d+$", "", phone.upper())
        start, end = max(0, start), min(duration, end)
        if end <= start:
            continue
        if phone == "HH":
            following = phones[i + 1][0].upper() if i + 1 < len(phones) else "AH"
            poses = (PHONE_POSE.get(following, 10),)
        else:
            poses = DIPHTHONGS.get(phone, (PHONE_POSE.get(phone, 0),))
        for j, pose in enumerate(poses):
            cues.append({"start": round(start + (end - start) * j / len(poses), 4),
                         "end": round(start + (end - start) * (j + 1) / len(poses), 4),
                         "pose": pose, "phone": phone})
    return {"cues": cues, "words": word_cues, "duration": duration,
            "method": "forced-phoneme" if forced else "acoustic-phoneme",
            **({"fallback_reason": fallback_reason} if fallback_reason else {}),
            "alignment_ms": round((time.monotonic() - started) * 1000, 1)}


class AlignmentService:
    def __init__(self):
        self.pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))

    async def align(self, pcm, text):
        return await asyncio.wait_for(asyncio.get_running_loop().run_in_executor(self.pool, align, pcm, text), 30)

    def close(self):
        self.pool.shutdown(wait=False, cancel_futures=True)
