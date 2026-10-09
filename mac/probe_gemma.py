"""Real-model checks, with no microphone, external tools or hosted inference."""
import json
import math
import os
import sys
import time

import mlx.core as mx

from gemma_mlx import ROOT, SpeakrailModel

os.environ["SPEAKRAIL_TOKENIZER_DIR"] = str(ROOT / "tokenizer")
sys.path.insert(0, str(ROOT.parent / "app"))
import protocol as P
from tokens_v1 import TOKENS, CHANNEL_OPEN

SYSTEM = ("You are Nova, a voice assistant in a live spoken conversation with one user. "
          "Keep answers short and plain, in spoken words. Wait for the user to finish. "
          "If the user asks for quiet, say nothing until they release you.")


def context(text, complete=False):
    c = P.Context()
    c.start(SYSTEM, [])
    for word in text.split():
        c.word(word)
    if complete:
        c.input_token("<complete>")
    return c


def run():
    for tid, token, *_ in TOKENS:
        assert P.encode(token) == [tid], (token, tid)
    model = SpeakrailModel()
    print("LOAD", json.dumps(model.audit), flush=True)
    cases = [
        ("unfinished", context("I would like to ask you about"), "idle", {P.LISTEN}),
        ("complete question", context("What is the capital of France?", True), "idle", {P.SPEAK}),
    ]
    overlap = context("Tell me about London.", True)
    overlap.call(P.SPEAK)
    overlap.reply_text("London is the capital of England and")
    overlap.cut_reply()
    overlap.word("Stop.")
    cases.append(("explicit interruption", overlap, "overlap", {P.YIELD}))
    backchannel = context("Tell me about London.", True)
    backchannel.call(P.SPEAK)
    backchannel.reply_text("London is the capital of England and")
    backchannel.cut_reply()
    backchannel.word("mm-hmm")
    backchannel.input_token("<user_bc>")
    cases.append(("listener acknowledgement", backchannel, "overlap", {P.CONTINUE}))
    records = []
    for label, c, options, expected in cases:
        tid, raw, ms = model.decision(c.ids, P.DECISION_SETS[options])
        z = sum(math.exp(x) for x in raw.values())
        rec = {"case": label, "tokens": len(c.ids), "decision": P.DECISION_NAME[tid],
               "expected": [P.DECISION_NAME[t] for t in expected], "matches_expectation": tid in expected,
               "ms": ms, "probabilities": {P.DECISION_NAME[k]: math.exp(v) / z for k, v in raw.items()}}
        records.append(rec)
        print(json.dumps(rec), flush=True)
    c = cases[1][1]
    adapted, adapted_lp, _ = model.decision(c.ids, P.IDLE_DECISIONS)
    _, base_lp, _ = model.decision(c.ids, P.IDLE_DECISIONS, name="speakrail-base")
    _, restored_lp, _ = model.decision(c.ids, P.IDLE_DECISIONS)
    effect = max(abs(adapted_lp[t] - base_lp[t]) for t in adapted_lp)
    restore_error = max(abs(adapted_lp[t] - restored_lp[t]) for t in adapted_lp)
    assert effect > 0.01, "Adapter had no observable effect"
    assert restore_error < 0.01, "Switching to base polluted the adapter state"
    c.call(P.SPEAK)
    model.select("speakrail")
    started = time.perf_counter()
    logits, cache = model.prefill(c.ids)
    output = []
    first_ms = None
    stop = None
    for i in range(80):
        logits = logits.at[CHANNEL_OPEN].add(-100)
        token = int(mx.argmax(logits))
        if first_ms is None:
            first_ms = (time.perf_counter() - started) * 1000
        if token in (P.SPEAK, P.TOOL_RESPONSE_OPEN, 1):
            stop = token
            break
        output.append(token)
        logits = model.model(mx.array([[token]]), cache=cache)[0, -1].astype(mx.float32)
    seconds = time.perf_counter() - started
    text = P.decode(output)
    assert text.strip(), "Empty generation"
    result = {"load": model.audit, "cases": records, "adapter_logprob_delta": effect,
              "adapter_restore_max_error": restore_error, "reply": text, "reply_stop_id": stop,
              "reply_tokens": len(output), "first_token_ms": first_ms, "reply_seconds": seconds,
              "peak_memory_gb": mx.get_peak_memory() / 1e9,
              "scope": "Short real-model smoke tests; not full-duplex or audio validation"}
    (ROOT / "gemma-probe.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    run()
