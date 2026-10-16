"""No models or microphone: real sample alignment and TTS adapter lifecycle.

python -m unittest discover -s tests -p test_lipsync.py
The real alignment checks skip if the optional PocketSphinx wheel is absent.
"""
import asyncio
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
import lipsync


@unittest.skipUnless(lipsync.available(), "optional PocketSphinx is not installed")
class RealAlignmentTests(unittest.TestCase):
    def test_bundled_speech_has_real_phonemes_and_silences(self):
        with wave.open(str(ROOT / "app/voices/female_a.wav")) as sample:
            pcm = sample.readframes(sample.getnframes())
        result = lipsync.align(pcm, (ROOT / "app/voices/female_a.txt").read_text())
        self.assertEqual(result["method"], "forced-phoneme")
        self.assertEqual(result["words"][0]["word"], "welcome")
        self.assertGreater(len(result["cues"]), 40)
        self.assertTrue(any(c["phone"] == "SIL" and c["pose"] == 0 for c in result["cues"]))
        self.assertTrue(any(c["phone"] == "M" and c["pose"] == 1 for c in result["cues"]))
        self.assertTrue(any(c["phone"] == "TH" and c["pose"] == 3 for c in result["cues"]))
        for cue in result["cues"]:
            self.assertGreater(cue["end"], cue["start"])
            self.assertLessEqual(cue["end"], len(pcm) / 48000)

    def test_names_and_digits_use_labeled_acoustic_alignment(self):
        with wave.open(str(ROOT / "app/voices/female_a.wav")) as sample:
            pcm = sample.readframes(sample.getnframes())
        result = lipsync.align(pcm, "Qzxnonword 12")
        self.assertEqual(result["method"], "acoustic-phoneme")
        self.assertTrue(result["cues"])


class FakeSession:
    """The adapter's interface to MicroSession, without a tokenizer or models."""
    def __init__(self):
        self.closed = False
        self.events = []
        self.replies = {}
        self.finished = []

    def _reply_of(self, utt): return self.replies.get(utt)
    def send(self, event): self.events.append(event)
    def _send_pcm(self, utt, pcm): self.events.append((utt, pcm))
    def _maybe_finished(self, reply): self.finished.append(reply.utt)
    def _kill_reply_gen(self, reply): reply.cut = True
    def on_tts_audio(self, seg, pcm):
        reply = self._reply_of(seg.utt)
        if reply.held: reply.held_pcm.append(pcm)
        else: self._send_pcm(seg.utt, pcm)
    def on_tts_done(self, seg): self._maybe_finished(self._reply_of(seg.utt))
    async def close(self): self.closed = True


spec = importlib.util.spec_from_file_location("isolated_lipsync_session", ROOT / "app/lipsync_session.py")
adapter = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"session": SimpleNamespace(MicroSession=FakeSession)}):
    spec.loader.exec_module(adapter)


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.gate = asyncio.Event()

        async def align(pcm, text):
            await self.gate.wait()
            return {"cues": [{"start": 0, "end": 0.01, "pose": 1}], "method": "forced-phoneme"}

        self.session = adapter.LipSyncSession(alignment_service=SimpleNamespace(align=align))
        self.reply = SimpleNamespace(utt=1, cut=False, held=False, held_pcm=[])
        self.session.replies[1] = self.reply

    def queue(self, number=0):
        seg = SimpleNamespace(utt=1, seg=number, text="Hello")
        self.last_segment = seg
        self.session.on_tts_audio(seg, b"\x00\x00" * 240)
        self.session.on_tts_done(seg)
        return self.session.alignment_tasks[(1, number)]

    async def test_cues_precede_exact_pcm_and_finish_waits_for_alignment(self):
        first, second = self.queue(0), self.queue(1)
        self.session._maybe_finished(self.reply)
        self.assertEqual(self.session.finished, [])
        self.gate.set()
        await asyncio.gather(first, second)
        self.assertEqual([e["segment"] for e in self.session.events if isinstance(e, dict)], [0, 1])
        self.assertEqual([type(e) for e in self.session.events], [dict, tuple, dict, tuple])
        self.assertEqual(self.session.events[0]["samples"], len(self.session.events[1][1]) // 2)
        self.assertEqual(self.session.finished, [])
        self.session.note_play_segment(1, 0, 200)
        self.session.note_play_segment(1, 1, 300)
        self.assertEqual(self.session.finished, [1])

    async def test_segment_ack_extends_timer_across_playback_gaps(self):
        self.gate.set()
        await self.queue()
        ended = []
        self.session._push = ended.extend
        self.reply.end_handle = asyncio.get_running_loop().call_later(0.01, ended.append, "early")
        self.session.note_play_segment(1, 0, 150)
        await asyncio.sleep(0.04)
        self.assertEqual(ended, [])
        await asyncio.sleep(0.15)
        self.assertEqual(ended, [("reply_end", self.reply)])

    async def test_invalid_and_stale_playback_ack_is_ignored(self):
        self.gate.set()
        await self.queue()
        self.session.note_play_segment(1, 0, float("nan"))
        self.session.note_play_segment(1, 0, -1)
        self.session.note_play_segment(1, 9, 100)
        self.assertEqual(self.session.playback_pending, {(1, 0)})
        self.session._kill_reply_gen(self.reply)
        self.session.note_play_segment(1, 0, 100)
        self.assertEqual(self.session.playback_pending, set())
        self.assertEqual(self.session.playback_end, {})

    async def test_speculation_holds_cues_until_matching_audio_is_committed(self):
        self.reply.held = True
        task = self.queue()
        self.gate.set(); await task
        self.assertEqual(self.session.events, [])
        self.session._send_pcm(1, self.reply.held_pcm.pop())
        self.assertEqual(self.session.events[0]["type"], "lip_sync")
        self.assertIsInstance(self.session.events[1], tuple)

    async def test_interrupt_discards_pending_audio_and_cues(self):
        task = self.queue()
        await asyncio.sleep(0)
        self.session._kill_reply_gen(self.reply)
        self.gate.set()
        await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(self.session.events, [])
        self.assertEqual(self.session.alignment_audio, {})

    async def test_alignment_failure_keeps_audio_and_reports_no_guessed_cues(self):
        async def fail(*args): raise RuntimeError("test")
        self.session.alignment_service.align = fail
        await self.queue()
        self.assertEqual(self.session.events[0]["method"], "unavailable")
        self.assertEqual(self.session.events[0]["cues"], [])
        self.assertIsInstance(self.session.events[1], tuple)

    async def test_pacing_precedes_alignment_and_updates_sample_count(self):
        from unittest.mock import AsyncMock
        self.session.speech_pace = .85
        paced = b"\x01\x00" * 300
        align = AsyncMock(return_value={"cues": [], "method": "forced-phoneme"})
        self.session.alignment_service.align = align
        with patch.object(adapter, "pace_pcm", AsyncMock(return_value=paced)) as pace:
            await self.queue()
        pace.assert_awaited_once_with(b"\x00\x00" * 240, .85)
        align.assert_awaited_once_with(paced, "Hello")
        self.assertEqual(self.session.events[0]["samples"], 300)
        self.assertEqual(self.last_segment.samples, 300)
        self.assertEqual(self.session.events[1][1], paced)

    async def test_pacing_failure_keeps_original_audio(self):
        from unittest.mock import AsyncMock
        self.gate.set()
        with patch.object(adapter, "pace_pcm", AsyncMock(side_effect=RuntimeError("test"))):
            await self.queue()
        self.assertEqual(self.session.events[0], {"type": "speech_pace_status", "available": False})
        self.assertEqual(self.session.events[2][1], b"\x00\x00" * 240)

    async def test_cancelling_a_queued_reply_preserves_prior_interjection(self):
        first = self.queue()
        second_reply = SimpleNamespace(utt=2, cut=False, held=False, held_pcm=[])
        self.session.replies[2] = second_reply
        seg = SimpleNamespace(utt=2, seg=0, text="Second")
        self.session.on_tts_audio(seg, b"\x00\x00" * 240)
        self.session.on_tts_done(seg)
        second = self.session.alignment_tasks[(2, 0)]
        await asyncio.sleep(0)
        self.session._kill_reply_gen(second_reply)
        self.gate.set()
        await asyncio.gather(first, second, return_exceptions=True)
        self.assertFalse(first.cancelled())
        self.assertEqual([e["utt"] for e in self.session.events if isinstance(e, dict)], [1])

    async def asyncTearDown(self):
        await self.session.close()


if __name__ == "__main__": unittest.main()
