"""Opt-in buffered phoneme alignment; the default MicroSession is unchanged."""
import asyncio
import math
import time
from session import MicroSession


class LipSyncSession(MicroSession):
    def __init__(self, *args, alignment_service, **kwargs):
        super().__init__(*args, **kwargs)
        self.alignment_service = alignment_service
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
                    result = await self.alignment_service.align(pcm, seg.text)
                except Exception as error:
                    result = {"cues": [], "words": [], "method": "unavailable", "reason": type(error).__name__}
                reply = self._reply_of(seg.utt)
                if self.closed or reply is None or reply.cut:
                    return
                event = {"type": "lip_sync", "utt": seg.utt, "segment": seg.seg,
                         "samples": len(pcm) // 2, "sample_rate": 24000, **result}
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
