"""Local alignment regression: failed forced timing must not mute the first mouth cues."""
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
import wave

import sys
ROOT = Path(__file__).resolve().parents[1]
ASTRA = ROOT / 'app'
sys.path.insert(0, str(ASTRA))
import lipsync


@unittest.skipUnless(lipsync.available(), 'PocketSphinx not installed')
class AlignmentTests(unittest.TestCase):
    def setUp(self):
        with wave.open(str(ASTRA / 'voices/astra_intro.wav')) as sample:
            self.assertEqual(sample.getframerate(), 24000)
            self.pcm = sample.readframes(sample.getnframes())

    def test_forced_failure_falls_back_on_same_audio_and_resets_failed_decoder(self):
        decoder = Mock()
        decoder.lookup_word.return_value = 'HH'
        decoder.set_alignment.side_effect = RuntimeError('Failed to set up sub-word alignment')
        with patch.object(lipsync, '_decoder', decoder):
            result = lipsync.align(self.pcm, 'Hello there')
            self.assertIsNone(lipsync._decoder)
        self.assertEqual(result['method'], 'acoustic-phoneme')
        self.assertEqual(result['fallback_reason'], 'forced-alignment-failed')
        first = next(c for c in result['cues'] if c['pose'])
        self.assertLess(first['start'], .5)
        self.assertEqual(result['words'], [])
        self.assertGreater(len(result['cues']), 10)

    def test_next_clause_can_use_forced_alignment_again(self):
        lipsync._decoder = None
        result = lipsync.align(self.pcm, (ASTRA / 'voices/astra_intro.txt').read_text())
        self.assertEqual(result['method'], 'forced-phoneme')
        self.assertTrue(result['words'])
        self.assertNotIn('fallback_reason', result)

    def test_unknown_names_still_use_acoustic_timing(self):
        result = lipsync.align(self.pcm, 'Qwen 4')
        self.assertEqual(result['method'], 'acoustic-phoneme')
        self.assertTrue(result['cues'])

    def test_reused_acoustic_decoder_covers_long_and_following_short_clips(self):
        for pcm in (self.pcm * 3, self.pcm):
            result = lipsync.align(pcm, 'Unknown 123')
            self.assertEqual(result['method'], 'acoustic-phoneme')
            self.assertGreater(result['cues'][-1]['end'], len(pcm) / 48000 - .1)
            self.assertTrue(all(c['end'] - c['start'] <= 1.2
                                for c in result['cues'] if c['pose']))

    def test_timing_failure_reason_survives_worker_serialization(self):
        import pickle
        import sys
        with patch.dict(sys.modules, {lipsync.__name__: lipsync}):
            error = pickle.loads(pickle.dumps(lipsync.AlignmentTimingError('acoustic-held-phone')))
        self.assertEqual(error.timing_reason, 'acoustic-held-phone')

    def test_total_alignment_failure_remains_explicit(self):
        decoder = Mock()
        decoder.lookup_word.return_value = None
        phone = Mock()
        phone.start_utt.side_effect = RuntimeError('Acoustic alignment unavailable')
        with patch.object(lipsync, '_decoder', decoder), patch.object(lipsync, '_phone_decoder', phone):
            with self.assertRaises(RuntimeError):
                lipsync.align(self.pcm, 'Unknown')

    def test_nonempty_partial_forced_alignment_falls_back_before_playback(self):
        decoder = Mock()
        decoder.lookup_word.return_value = 'HH'
        decoder.get_alignment.return_value = SimpleNamespace(phones=lambda: [
            SimpleNamespace(name='HH', start=0, duration=10), SimpleNamespace(name='AH', start=10, duration=10)])
        with patch.object(lipsync, '_decoder', decoder):
            result = lipsync.align(self.pcm, 'Hello there')
            self.assertIsNone(lipsync._decoder)
        self.assertEqual(result['method'], 'acoustic-phoneme')
        self.assertEqual(result['fallback_reason'], 'forced-uncovered-speech')
        self.assertGreater(max(c['end'] for c in result['cues']), len(self.pcm) / 48000 - .2)

    def test_held_forced_phone_falls_back(self):
        decoder = Mock()
        decoder.lookup_word.return_value = 'HH'
        decoder.get_alignment.return_value = SimpleNamespace(phones=lambda: [
            SimpleNamespace(name='AH', start=0, duration=round(len(self.pcm) / 480))])
        with patch.object(lipsync, '_decoder', decoder):
            result = lipsync.align(self.pcm, 'Hello there')
        self.assertEqual(result['fallback_reason'], 'forced-held-phone')
        self.assertEqual(result['method'], 'acoustic-phoneme')

    def test_validation_keeps_real_silence_and_rejects_voiced_tail_without_cues(self):
        import numpy as np
        rate = lipsync.RATE
        speech = np.sin(np.arange(rate) * 2 * np.pi * 200 / rate) * 2000
        self.assertEqual(lipsync.timing_issue([('AH', 0, .2)], speech), 'uncovered-speech')
        silent_tail = np.concatenate([speech[:rate//5], np.zeros(rate)])
        self.assertIsNone(lipsync.timing_issue([('AH', 0, .2), ('SIL', .2, 1.2)], silent_tail))
