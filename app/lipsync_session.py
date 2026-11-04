"""Opt-in buffered phoneme alignment; the default MicroSession is unchanged."""
import asyncio
import math
import time
from session import MicroSession
from speech_pacing import pace_pcm


def cut_clause(text, need=40, final=False, limit=160):
    """Bound whole tool replies and final tails as well as streamed text."""
    for i, char in enumerate(text[:limit]):
        if i + 1 < need or char not in '.?!;\n,':
            continue
        if char in '.:' and i and i + 1 < len(text) and text[i-1].isalnum() and text[i+1].isalnum():
            continue  # Domains, decimals and clock times are not clause boundaries.
        return text[:i+1].strip(), text[i+1:]
    if len(text) > limit:
        end = text.rfind(' ', 0, limit + 1)
        end = end if end > 0 else limit
        return text[:end].strip(), text[end:]
    return (text.strip(), '') if final else (None, text)


class LipSyncSession(MicroSession):
    def _cut(self, reply, final):
        need = self.m.first_clause_chars if reply.n_seg == 0 else self.m.next_clause_chars
        segment, reply.out_buf = cut_clause(reply.out_buf, need, final)
        return segment or None

    def __init__(self, *args, alignment_service, speech_pace=1.0, **kwargs):
        super().__init__(*args, **kwargs)
        self.alignment_service = alignment_service
        self.speech_pace = speech_pace
        self.alignment_audio = {}
        self.alignment_tasks = {}
        self.alignment_events = {}
        self.alignment_tail = None
        self.playback_pending = set()
        self.playback_end = {}

    def on_tts_audio(self, seg, pcm):
        reply = self._reply_of(seg.utt)
        if reply is None or reply.cut or self.closed:
            return
        key = (seg.utt, seg.seg)
        self.alignment_audio.setdefault(key, bytearray()).extend(pcm)

    def on_tts_done(self, seg):
        key = (seg.utt, seg.seg)
        if key not in self.alignment_audio:
            return super().on_tts_done(seg)
        previous = self.alignment_tail

        async def release():
            try:
                # Preserve exact segment order even if inference callbacks arrive
                # while an earlier segment is still being aligned.
                if previous is not None:
                    await asyncio.shield(asyncio.gather(previous, return_exceptions=True))
                pcm = bytes(self.alignment_audio[key])
                try:
                    pcm = await pace_pcm(pcm, self.speech_pace)
                except Exception:
                    self.send({"type": "speech_pace_status", "available": False})
                seg.samples = len(pcm) // 2
                try:
                    result = await self.alignment_service.align(pcm, seg.text)
                except Exception as error:
                    result = {"cues": [], "words": [], "method": "unavailable",
                              "reason": getattr(error, 'timing_reason', type(error).__name__)}
                reply = self._reply_of(seg.utt)
                if self.closed or reply is None or reply.cut:
                    return
                event = {"type": "lip_sync", "utt": seg.utt, "segment": seg.seg,
                         "samples": len(pcm) // 2, "sample_rate": 24000, **result}
                first_motion = next((c["start"] for c in result.get("cues", []) if c.get("pose")), None)
                if result.get('fallback_reason') or result.get('method') == 'unavailable':
                    print(f"[lip-timing] utt={seg.utt} segment={seg.seg} method={result.get('method')} "
                          f"reason={result.get('fallback_reason', result.get('reason', '-'))} "
                          f"duration_s={len(pcm) / 48000:.3f}", flush=True)
                self._line(f"    LIP_SYNC utt={seg.utt} segment={seg.seg} method={result.get('method')} "
                           f"first_motion_s={first_motion} fallback={result.get('fallback_reason', '-')} "
                           f"alignment_ms={result.get('alignment_ms', '-')} samples={len(pcm) // 2}")
                # A speculative reply can still be held. Send cues only when its
                # matching PCM is actually released by the normal controller.
                self.alignment_events[id(pcm)] = (seg.utt, event)
                self.alignment_audio.pop(key, None)
                super(LipSyncSession, self).on_tts_audio(seg, pcm)
                super(LipSyncSession, self).on_tts_done(seg)
            finally:
                self.alignment_audio.pop(key, None)
                self.alignment_tasks.pop(key, None)

        task = asyncio.create_task(release())
        self.alignment_tasks[key] = task
        self.alignment_tail = task

    def _send_pcm(self, utt, pcm):
        entry = self.alignment_events.pop(id(pcm), None)
        if entry is not None:
            self.playback_pending.add((utt, entry[1]["segment"]))
            self.send(entry[1])
        super()._send_pcm(utt, pcm)

    def note_play_segment(self, utt, segment, remaining_ms):
        key = (utt, segment)
        if key not in self.playback_pending or not math.isfinite(remaining_ms) or not 0 <= remaining_ms <= 300000:
            return
        self.playback_pending.remove(key)
        self.playback_end[utt] = max(self.playback_end.get(utt, 0), time.monotonic() + remaining_ms / 1000)
        reply = self._reply_of(utt)
        if reply is not None and reply is not getattr(self, "IJ", None):
            self._maybe_finished(reply)

    def _maybe_finished(self, reply):
        if any(utt == reply.utt for utt, _ in self.alignment_audio) or any(utt == reply.utt for utt, _ in self.playback_pending):
            return
        super()._maybe_finished(reply)
        # Buffered clauses can leave gaps. The original timer counts only PCM
        # duration from the first start, so it can retire a reply during its tail.
        handle = getattr(reply, "end_handle", None)
        if handle not in (None, True) and reply.utt in self.playback_end:
            handle.cancel()
            delay = max(0, self.playback_end[reply.utt] - time.monotonic())
            reply.end_handle = asyncio.get_running_loop().call_later(delay, lambda: self._push([("reply_end", reply)]))

    async def _reply_end(self, reply):
        self.playback_end.pop(reply.utt, None)
        await super()._reply_end(reply)

    def _kill_reply_gen(self, reply):
        super()._kill_reply_gen(reply)
        for key, task in list(self.alignment_tasks.items()):
            if key[0] == reply.utt:
                task.cancel()
                self.alignment_tasks.pop(key, None)
                self.alignment_audio.pop(key, None)
        for key in list(self.alignment_audio):
            if key[0] == reply.utt:
                self.alignment_audio.pop(key, None)
        self.alignment_events = {key: value for key, value in self.alignment_events.items() if value[0] != reply.utt}
        self.playback_pending = {key for key in self.playback_pending if key[0] != reply.utt}
        self.playback_end.pop(reply.utt, None)

    async def close(self):
        tasks = list(self.alignment_tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.alignment_audio.clear()
        self.alignment_events.clear()
        self.playback_pending.clear()
        self.playback_end.clear()
        await super().close()
