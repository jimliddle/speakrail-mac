"""Breeze TTS 2 worker: text segments in, 24 kHz PCM chunks out (80 ms), killable per utterance."""
from __future__ import annotations

import asyncio
import os
import queue
import re
import threading
import time


class Segment:
    __slots__ = ("utt", "seg", "text", "samples", "done", "t_queued", "t_first")

    def __init__(self, utt: int, seg: int, text: str):
        self.utt, self.seg, self.text = utt, seg, text
        self.samples = 0
        self.done = False
        self.t_queued = time.monotonic()
        self.t_first = None


TAG_RE = re.compile(r"<\|[a-z_]+:[a-z_]+\|>")


def strip_tags(text: str) -> str:
    """Remove <|category:value|> control tags (never spoken, never displayed)."""
    return " ".join(TAG_RE.sub("", text).split())


class BreezeWorker(threading.Thread):
    """Breeze TTS 2 over its streaming API (:7860): one multipart request per segment,
    raw 24 kHz int16 PCM streamed back in 80 ms chunks. `ref` is a wav whose
    transcript sits next to it as .txt (voice clone; the server caches the reference codes by content hash).
    Vocal events go inline in the text: (laugh) (sigh) (cough) (clears throat)."""

    def __init__(self, ref: str, loop: asyncio.AbstractEventLoop, on_audio, on_segment_done,
                 url: str = os.environ.get("TTS_URL", "http://127.0.0.1:7860/v1/audio/speech"), seed: int = 42, instruction: str | None = None,
                 cfg_scale: float = 1.0):
        super().__init__(daemon=True, name="breeze-tts")
        self.ref, self.loop = ref, loop
        self.on_audio, self.on_segment_done = on_audio, on_segment_done
        self.url, self.seed, self.instruction, self.cfg_scale = url, seed, instruction, cfg_scale
        self.device = "cuda"
        self.q: queue.Queue[Segment | None] = queue.Queue()
        self.killed_utts: set[int] = set()
        self.current: Segment | None = None
        self.resp = None
        self.sample_rate = 24000
        self.ready = threading.Event()
        self.stats = {"segments": 0, "ttfa_ms": [], "rtf": [], "silent_lead": []}
        self.ref_bytes = open(ref, "rb").read()
        self.ref_text = open(ref.rsplit(".", 1)[0] + ".txt").read().strip()

    def say(self, seg: Segment):
        self.q.put(seg)

    def stop(self):
        self.q.put(None)

    def kill(self, utt: int):
        self.killed_utts.add(utt)
        keep = []
        try:
            while True:
                s = self.q.get_nowait()
                if s is not None and s.utt != utt:
                    keep.append(s)
        except queue.Empty:
            pass
        for s in keep:
            self.q.put(s)
        cur, resp = self.current, self.resp
        if cur is not None and cur.utt == utt and resp is not None:
            try:
                resp.close()                          # drops the stream -> the TTS server aborts the request
            except Exception:
                pass

    def _stream(self, seg: Segment):
        import requests
        data = {"text": seg.text, "ref_text": self.ref_text, "seed": str(self.seed), "cfg_scale": str(self.cfg_scale)}
        if self.instruction:
            data["instruction"] = self.instruction
        files = {"ref_audio": ("ref.wav", self.ref_bytes, "audio/wav")}
        for _ in range(75):                               # 409 = the request we just killed is still releasing (~20-50 ms)
            r = requests.post(self.url, data=data, files=files, stream=True, timeout=(5, 60))
            if r.status_code != 409 or seg.utt in self.killed_utts:
                break
            r.close(); time.sleep(0.02)
        with r:
            self.resp = r
            r.raise_for_status()
            for pcm in r.iter_content(chunk_size=None):
                if seg.utt in self.killed_utts:
                    return
                if pcm:
                    yield pcm

    def run(self):
        t0 = time.time()
        try:                                              # warm: encodes + caches the reference on the server
            for _ in self._stream(Segment(-1, 0, "Hello there, warming up.")):
                pass
            print(f"[tts] breeze ready ({self.ref.rsplit('/', 1)[-1]}) in {time.time()-t0:.1f}s, sr={self.sample_rate}", flush=True)
        except Exception as e:
            print(f"[tts] breeze warmup failed: {e!r}", flush=True)
        self.ready.set()
        while True:
            seg = self.q.get()
            if seg is None:
                return
            if seg.utt in self.killed_utts:
                continue
            self.current = seg
            t_start = time.monotonic()
            try:
                for pcm in self._stream(seg):
                    if seg.t_first is None:
                        seg.t_first = time.monotonic()
                        self.stats["ttfa_ms"].append((seg.t_first - t_start) * 1000)
                        self.stats["silent_lead"].append(0)
                    seg.samples += len(pcm) // 2
                    self.loop.call_soon_threadsafe(self.on_audio, seg, pcm)
            except Exception as e:
                if seg.utt not in self.killed_utts:
                    print(f"[tts] breeze error on {seg.text!r}: {e!r}", flush=True)
            self.resp = None
            seg.done = True
            dur = seg.samples / self.sample_rate
            if dur > 0:
                self.stats["rtf"].append((time.monotonic() - t_start) / dur)
            self.stats["segments"] += 1
            self.current = None
            self.loop.call_soon_threadsafe(self.on_segment_done, seg)
