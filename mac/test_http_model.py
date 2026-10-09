"""Exercise the real MLX backend through Speakrail's opt-in cached HTTP client."""
import asyncio
import json
import os
import statistics
import time

import aiohttp
from aiohttp import web

from gemma_mlx import ROOT, SpeakrailModel
from mlx_server import create_app, P
from llm_engine import Engine
from probe_gemma import context


async def run():
    model = SpeakrailModel()
    runner = web.AppRunner(create_app(model), handler_cancellation=True)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    c = context("What is the capital of France?", True)
    engine = Engine(url)
    assert engine.cache_salt
    report = {"load": model.audit, "checks": []}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as http:
            await engine.warm(http, c.ids)
            timings = []
            for _ in range(5):
                tid, probs, raw, ms = await engine.decide(http, c.ids, P.IDLE_DECISIONS)
                assert tid == P.SPEAK and abs(sum(probs.values()) - 1) < 1e-6
                assert set(raw) == set(P.IDLE_DECISIONS)
                timings.append(ms)
            report["checks"].append("original Engine warm/decide and normalized probabilities")
            report["warm_short_decision_ms"] = timings
            report["warm_short_median_ms"] = statistics.median(timings)
            c.call(P.SPEAK)
            start = time.perf_counter()
            stream = engine.stream(http, c.ids, 60, [P.SPEAK, P.TOOL_RESPONSE_OPEN], {100: -100})
            pieces = []
            first_ms = None
            async for delta in stream:
                if first_ms is None:
                    first_ms = (time.perf_counter() - start) * 1000
                pieces.append(delta)
            text = "".join(pieces)
            assert "Paris" in text and stream.stop == P.SPEAK and stream.n_tokens > 1
            report.update(reply=text, stream_first_delta_ms=first_ms, stream_stop_id=stream.stop,
                          stream_completion_tokens=stream.n_tokens)
            report["checks"].append("original Engine SSE reply, usage and stop ID")
            stream = engine.stream(http, c.ids, 2, [P.TOOL_RESPONSE_OPEN], {P.TOOL_RESPONSE_OPEN: 100})
            assert "".join([s async for s in stream]) == ""
            assert stream.stop == P.TOOL_RESPONSE_OPEN
            report["checks"].append("tool-response special stop token preserved")

            good = {"model": "speakrail", "prompt": c.ids, "max_tokens": 1}
            for override in ({"prompt": "not token IDs"}, {"prompt": [-1]}, {"model": "other"},
                             {"max_tokens": 999999}, {"temperature": 0.7}, {"skip_special_tokens": True},
                             {"allowed_token_ids": []}, {"unexpected": True}):
                async with http.post(url + "/v1/completions", json={**good, **override}) as response:
                    assert response.status == 400, override
            async with http.post(url + "/v1/completions", json=good,
                                 headers={"Origin": "https://untrusted.example"}) as response:
                assert response.status == 403
            report["checks"].append("eight invalid requests rejected; browser origins refused")

            long_reply = context("Count from one to one hundred, without stopping.", True)
            long_reply.call(P.SPEAK)
            body = {"model": "speakrail", "prompt": long_reply.ids, "max_tokens": 512, "stream": True,
                    "logit_bias": {"100": -100}, "stop_token_ids": [P.SPEAK]}
            before = await (await http.get(url + "/health")).json()
            response = await http.post(url + "/v1/completions", json=body)
            await response.content.readline()
            response.close()
            for _ in range(40):
                await asyncio.sleep(0.05)
                health = await (await http.get(url + "/health")).json()
                if health["active"] == 0:
                    break
            assert health["active"] == 0 and health["cancelled"] > before["cancelled"]
            report["checks"].append("disconnect cancels streamed generation and clears active request")

            # A base-model request during a stream must not change its LoRA state.
            expected = report["reply"]
            stream = engine.stream(http, c.ids, 60, [P.SPEAK], {100: -100})
            pieces = []
            async for delta in stream:
                pieces.append(delta)
                if len(pieces) == 1:
                    base = Engine(url, lora=None)
                    await base.decide(http, context("Hello", True).ids, P.IDLE_DECISIONS)
            assert "".join(pieces) == expected
            report["checks"].append("base request interleaved with LoRA stream preserves reply")

            report["long_context_ms"] = {}
            prefix = context("", False).ids
            filler = P.encode("The discussion continues about daily routines and future plans. ")
            for length in (1024, 4096):
                ids = prefix + (filler * (length // len(filler) + 1))[:length - len(prefix) - 1] + [6]
                _, _, _, ms = await engine.decide(http, ids, P.IDLE_DECISIONS)
                report["long_context_ms"][str(len(ids))] = ms
            health = await (await http.get(url + "/health")).json()
            assert health["cache"]["hits"] > 0, health
            report["cache"] = health["cache"]
            report["checks"].append("opt-in client session salt produces cache hits")
            report["scope"] = "Actual Gemma and HTTP with bounded session/model prefix cache; no ASR/TTS"
    finally:
        await runner.cleanup()
    (ROOT / "http-model-results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    os.environ["SPEAKRAIL_CACHE_SESSION"] = "1"
    asyncio.run(run())
