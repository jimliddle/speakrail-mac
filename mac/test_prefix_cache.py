import asyncio
import json
import os
import time
import unittest
from unittest.mock import patch

os.environ["MLX_ENABLE_TF32"] = "0"
import mlx.core as mx
import numpy as np
from mlx_lm.models.cache import KVCache, RotatingKVCache

from prefix_cache import PrefixCache
from gemma_mlx import ROOT, SpeakrailModel
from probe_gemma import context, P


class SnapshotTests(unittest.TestCase):
    def make(self):
        caches = [KVCache(), RotatingKVCache(4)]
        for cache in caches:
            cache.update_and_fetch(mx.ones((1, 1, 6, 4)), mx.ones((1, 1, 6, 4)))
        return caches

    def test_session_model_exact_prefix_and_snapshot_isolation(self):
        store = PrefixCache()
        caches = self.make()
        ids = [1, 2, 3, 4, 5, 6]
        store.put("a", "session", ids, caches, mx.zeros(8))
        first, _, count = store.get("a", "session", ids + [7])
        self.assertEqual(count, 6)
        for cache in first:
            cache.update_and_fetch(mx.full((1, 1, 1, 4), 9), mx.full((1, 1, 1, 4), 9))
        second, _, _ = store.get("a", "session", ids)
        for cache in second:
            self.assertTrue(bool(mx.all(cache.state[0] == 1)))
            self.assertEqual(cache.offset, 6)
        self.assertIsNone(store.get("b", "session", ids))
        self.assertIsNone(store.get("a", "another", ids))
        self.assertIsNone(store.get("a", None, ids))
        self.assertIsNone(store.get("a", "session", ids[:-1]))
        self.assertIsNone(store.get("a", "session", [1, 9, 3, 4, 5, 6]))

    def test_limits_and_expiry(self):
        store = PrefixCache(max_entries=1, ttl=2)
        with patch("prefix_cache.time.monotonic", return_value=10):
            store.put("a", "s", [1], self.make(), mx.zeros(8))
            store.put("a", "s", [2], self.make(), mx.zeros(8))
            self.assertEqual(len(store.entries), 1)
        with patch("prefix_cache.time.monotonic", return_value=13):
            self.assertIsNone(store.get("a", "s", [2]))
        tiny = PrefixCache(max_bytes=1)
        tiny.put("a", "s", [1], self.make(), mx.zeros(8))
        self.assertEqual(tiny.nbytes, 0)


async def real_model():
    model = SpeakrailModel()
    prefix = context("", False).ids
    filler = P.encode("The discussion continues about daily routines and future plans. ")
    report = {"lengths": {}, "checks": []}
    for length in (1024, 4096):
        ids = prefix + (filler * (length // len(filler) + 1))[:length - len(prefix)]
        start = time.perf_counter()
        logits, _ = await model.prefill_async(ids, "speakrail", "test-session")
        cold_ms = (time.perf_counter() - start) * 1000
        start = time.perf_counter()
        cached, _ = await model.prefill_async(ids, "speakrail", "test-session")
        exact_ms = (time.perf_counter() - start) * 1000
        assert bool(mx.array_equal(logits, cached))
        extended = ids + P.encode(" What is the capital of France?") + [6]
        start = time.perf_counter()
        incremental, _ = await model.prefill_async(extended, "speakrail", "test-session")
        append_ms = (time.perf_counter() - start) * 1000
        full, _ = await model.prefill_async(extended, "speakrail", None)
        error = float(mx.max(mx.abs(incremental - full)))
        ai = int(mx.argmax(incremental[mx.array(P.IDLE_DECISIONS)]))
        bi = int(mx.argmax(full[mx.array(P.IDLE_DECISIONS)]))
        assert ai == bi, "Cache changed decision"
        # BF16 execution with different batch shapes is not bitwise identical.
        pa = mx.softmax(incremental[mx.array(P.IDLE_DECISIONS)])
        pb = mx.softmax(full[mx.array(P.IDLE_DECISIONS)])
        probability_error = float(mx.max(mx.abs(pa - pb)))
        assert probability_error < 0.02, probability_error
        report["lengths"][length] = {"initial_ms": cold_ms, "exact_hit_ms": exact_ms,
                                     "append_ms": append_ms, "max_logit_error": error,
                                     "max_decision_probability_error": probability_error}
    model.prefix_cache.entries.clear()
    ids = context("Hello", True).ids
    before = model.prefix_cache.hits
    await model.prefill_async(ids, "speakrail", "one")
    await model.prefill_async(ids, "speakrail-base", "one")
    await model.prefill_async(ids, "speakrail", "two")
    assert model.prefix_cache.hits == before
    report["checks"].append("No cross-model or cross-session reuse")
    baseline, _ = await model.prefill_async(ids, "speakrail", "one")
    a, b = await asyncio.gather(model.prefill_async(ids + [10], "speakrail", "one"),
                                model.prefill_async(ids + [11], "speakrail-base", "one"))
    again, _ = await model.prefill_async(ids, "speakrail", "one")
    assert bool(mx.array_equal(baseline, again))
    report["checks"].append("Concurrent branches do not mutate saved prompt")
    report["stats"] = model.prefix_cache.stats()
    (ROOT / "prefix-cache-results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(SnapshotTests)
    if not unittest.TextTestRunner().run(suite).wasSuccessful():
        raise SystemExit(1)
    asyncio.run(real_model())
