"""Speech tempo, pitch and cancellation checks; no model or microphone."""
import asyncio
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import AsyncMock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
from speech_pacing import pace_pcm, speech_pace


class SpeechPacingTests(unittest.IsolatedAsyncioTestCase):
    def test_only_bounded_presets_are_accepted(self):
        for value in ("0.75", "0.85", "1"):
            self.assertEqual(speech_pace(value), float(value))
        for value in ("0", "nan", "inf", "-1", "2", "oops"):
            with self.assertRaises(ValueError):
                speech_pace(value)

    async def test_original_pace_is_unchanged(self):
        pcm = b"\x00\x00" * 100
        self.assertIs(await pace_pcm(pcm, 1), pcm)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is not installed")
    async def test_slower_audio_retains_pitch(self):
        tone = (np.sin(2 * np.pi * 440 * np.arange(24000) / 24000) * 16000).astype("<i2")
        for pace in (.75, .85):
            output = np.frombuffer(await pace_pcm(tone.tobytes(), pace), dtype="<i2")
            self.assertAlmostEqual(len(output) / 24000, 1 / pace, delta=.06)
            spectrum = np.abs(np.fft.rfft(output.astype(float)))
            pitch = np.fft.rfftfreq(len(output), 1 / 24000)[spectrum.argmax()]
            self.assertAlmostEqual(pitch, 440, delta=3)

    async def test_cancellation_terminates_owned_processor(self):
        entered = asyncio.Event()
        process = AsyncMock()
        process.returncode = None

        async def communicate(_):
            entered.set()
            await asyncio.Event().wait()

        def kill():
            process.returncode = -9

        process.communicate.side_effect = communicate
        from unittest.mock import Mock
        process.kill = Mock(side_effect=kill)
        with patch("speech_pacing.asyncio.create_subprocess_exec", return_value=process):
            task = asyncio.create_task(pace_pcm(b"\x00\x00" * 24000, .85))
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        process.kill.assert_called_once()
        process.wait.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
