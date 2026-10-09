"""Bounded, memory-only snapshots. Reuse exact prefixes; never rewind a ring cache."""
from collections import OrderedDict
import time

import mlx.core as mx


def clone_cache(cache):
    return [type(c).from_state(tuple(mx.array(x) for x in c.state), c.meta_state) for c in cache]


class PrefixCache:
    def __init__(self, max_entries=8, max_bytes=2 * 1024**3, ttl=300):
        self.entries = OrderedDict()
        self.max_entries, self.max_bytes, self.ttl = max_entries, max_bytes, ttl
        self.hits = self.misses = self.reused_tokens = 0

    def prune(self):
        now = time.monotonic()
        for key in list(self.entries):
            if now - self.entries[key][3] >= self.ttl:
                del self.entries[key]
        while self.entries and (len(self.entries) > self.max_entries or self.nbytes > self.max_bytes):
            self.entries.popitem(last=False)

    @property
    def nbytes(self):
        return sum(entry[4] for entry in self.entries.values())

    def get(self, model, salt, ids):
        self.prune()
        if not salt:
            self.misses += 1
            return None
        ids = tuple(ids)
        matches = [k for k in self.entries if k[:2] == (model, salt) and ids[:len(k[2])] == k[2]]
        if not matches:
            self.misses += 1
            return None
        key = max(matches, key=lambda k: len(k[2]))
        cache, logits, count, _, size = self.entries[key]
        self.entries[key] = (cache, logits, count, time.monotonic(), size)
        self.entries.move_to_end(key)
        self.hits += 1
        self.reused_tokens += count
        return clone_cache(cache), mx.array(logits), count

    def put(self, model, salt, ids, cache, logits):
        if not salt:
            return
        size = sum(c.nbytes for c in cache) + logits.nbytes
        if size > self.max_bytes:
            return
        snapshot, last = clone_cache(cache), mx.array(logits)
        mx.eval([c.state for c in snapshot], last)
        self.entries[(model, salt, tuple(ids))] = (snapshot, last, len(ids), time.monotonic(), size)
        self.entries.move_to_end((model, salt, tuple(ids)))
        self.prune()

    def stats(self):
        self.prune()
        return {"entries": len(self.entries), "bytes": self.nbytes, "hits": self.hits,
                "misses": self.misses, "reused_tokens": self.reused_tokens}
