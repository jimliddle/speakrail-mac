"""Local-only experimental Speakrail completions adapter, not a general API.

Bounded snapshots require an explicit session salt. Each request owns its KV state. GPU steps run on
the event loop and finish before yielding, so base/LoRA selection cannot leak
between requests. Prefill yields between bounded chunks.
"""
import argparse
import asyncio
import json
import math
import os
import sys

from aiohttp import web
import mlx.core as mx

from gemma_mlx import ROOT, SpeakrailModel

os.environ["SPEAKRAIL_TOKENIZER_DIR"] = str(ROOT / "tokenizer")
sys.path.insert(0, str(ROOT.parent / "app"))
import protocol as P


def validate(body):
    if not isinstance(body, dict):
        raise ValueError("Body must be an object")
    fields = {"model", "prompt", "max_tokens", "temperature", "allowed_token_ids", "logprobs",
              "return_tokens_as_token_ids", "logit_bias", "cache_salt", "stop_token_ids",
              "skip_special_tokens", "stream", "stream_options", "ignore_eos"}
    if set(body) - fields:
        raise ValueError(f"Unsupported fields: {sorted(set(body) - fields)}")
    if body.get("model") not in ("speakrail", "speakrail-base"):
        raise ValueError("Unknown model")
    def tokens(value, name, minimum, maximum):
        if not isinstance(value, list) or not minimum <= len(value) <= maximum:
            raise ValueError(f"{name}: invalid list length")
        if any(type(t) is not int or not 0 <= t < 262144 for t in value):
            raise ValueError(f"{name}: invalid token ID")
    tokens(body.get("prompt"), "prompt", 1, 8192)
    if type(body.get("max_tokens")) is not int or not 1 <= body["max_tokens"] <= 512:
        raise ValueError("max_tokens must be 1..512")
    if body.get("temperature", 0) != 0:
        raise ValueError("Prototype supports greedy decoding only")
    for key in ("stream", "ignore_eos", "skip_special_tokens", "return_tokens_as_token_ids"):
        if key in body and type(body[key]) is not bool:
            raise ValueError(f"{key} must be boolean")
    if body.get("skip_special_tokens", False):
        raise ValueError("Speakrail requires special tokens preserved")
    if "cache_salt" in body and (not isinstance(body["cache_salt"], str) or not 1 <= len(body["cache_salt"]) <= 128):
        raise ValueError("cache_salt must be a nonempty string of at most 128 characters")
    if "stream_options" in body and body["stream_options"] != {"include_usage": True}:
        raise ValueError("Unsupported stream_options")
    if "stop_token_ids" in body:
        tokens(body["stop_token_ids"], "stop_token_ids", 0, 32)
    if "allowed_token_ids" in body:
        tokens(body["allowed_token_ids"], "allowed_token_ids", 1, 20)
        if len(set(body["allowed_token_ids"])) != len(body["allowed_token_ids"]):
            raise ValueError("Duplicate allowed token")
        if body["max_tokens"] != 1 or body.get("stream", False):
            raise ValueError("Decision calls require one non-streamed token")
    if "logprobs" in body and (body["logprobs"] != 20 or not body.get("return_tokens_as_token_ids")):
        raise ValueError("Only Speakrail's token-ID logprobs contract is supported")
    if "logprobs" in body and "allowed_token_ids" not in body:
        raise ValueError("Logprobs require a decision call")
    bias = body.get("logit_bias", {})
    if not isinstance(bias, dict) or len(bias) > 64:
        raise ValueError("Invalid logit_bias")
    for token, value in bias.items():
        if not str(token).isdigit() or not 0 <= int(token) < 262144:
            raise ValueError("Invalid bias token")
        if type(value) not in (float, int) or not math.isfinite(value) or not -100 <= value <= 100:
            raise ValueError("Bias must be finite and between -100 and 100")
    return body


def create_app(model):
    app = web.Application(client_max_size=256 * 1024)
    stats = {"completed": 0, "cancelled": 0, "active": 0}

    async def health(request):
        return web.json_response({"ok": True, "experimental": True, "cache": model.prefix_cache.stats(),
                                  "models": ["speakrail", "speakrail-base"], **stats})

    async def completion(request):
        # Only the local Python controller is a client; don't expose to websites.
        if request.headers.get("Origin"):
            raise web.HTTPForbidden(text="Browser-origin calls are not enabled")
        try:
            body = validate(await request.json())
        except (ValueError, TypeError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
        if stats["active"] >= 4:
            return web.json_response({"error": "Prototype busy"}, status=429)
        stats["active"] += 1
        try:
            name, prompt = body["model"], body["prompt"]
            bias = {int(k): float(v) for k, v in body.get("logit_bias", {}).items()}
            logits, cache = await model.prefill_async(prompt, name, body.get("cache_salt"))
            if allowed := body.get("allowed_token_ids"):
                if bias:
                    logits = logits.at[mx.array(list(bias))].add(mx.array(list(bias.values())))
                logprobs = logits - mx.logsumexp(logits)
                selected = logprobs[mx.array(allowed)]
                mx.eval(selected)
                token = allowed[int(mx.argmax(selected))]
                raw = dict(zip(allowed, selected.tolist()))
                stats["completed"] += 1
                return web.json_response({"choices": [{"text": P.decode([token]), "finish_reason": "length",
                    "logprobs": {"tokens": [f"token_id:{token}"], "token_logprobs": [raw[token]],
                                 "top_logprobs": [{f"token_id:{k}": v for k, v in raw.items()}]}}]})

            stream = body.get("stream", False)
            response = web.StreamResponse(headers={"Content-Type": "text/event-stream"}) if stream else None
            if response:
                await response.prepare(request)
            output, emitted, count, stop = [], "", 0, None
            stops = set(body.get("stop_token_ids", []))
            if not body.get("ignore_eos", False):
                stops.update((1, 106))
            for i in range(body["max_tokens"]):
                if request.transport is None or request.transport.is_closing():
                    stats["cancelled"] += 1
                    return response or web.Response(status=499)
                if bias:
                    logits = logits.at[mx.array(list(bias))].add(mx.array(list(bias.values())))
                token = int(mx.argmax(logits))
                count += 1
                if token in stops:
                    stop = token
                    break
                output.append(token)
                text = P.decode(output).rstrip("\ufffd")
                if not text.startswith(emitted):
                    raise RuntimeError("Tokenizer produced a non-monotonic stream")
                delta = text[len(emitted):]
                emitted = text
                if response and delta:
                    await response.write(("data: " + json.dumps({"choices": [{"text": delta,
                                             "finish_reason": None}]}) + "\n\n").encode())
                await asyncio.sleep(0)
                if i + 1 < body["max_tokens"]:
                    model.select(name)
                    logits = model.model(mx.array([[token]]), cache=cache)[0, -1].astype(mx.float32)
                    mx.eval(logits)  # Finish before another request changes adapter selection.
            end = {"choices": [{"text": "" if stream else emitted,
                                "finish_reason": "stop" if stop is not None else "length", "stop_reason": stop}],
                   "usage": {"prompt_tokens": len(prompt), "completion_tokens": count}}
            if response:
                await response.write(("data: " + json.dumps(end) + "\n\ndata: [DONE]\n\n").encode())
                await response.write_eof()
            stats["completed"] += 1
            return response or web.json_response(end)
        except (ConnectionResetError, asyncio.CancelledError):
            stats["cancelled"] += 1
            raise
        finally:
            stats["active"] -= 1

    app.router.add_get("/health", health)
    app.router.add_post("/v1/completions", completion)
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18011)
    args = parser.parse_args()
    web.run_app(create_app(SpeakrailModel()), host="127.0.0.1", port=args.port,
                handler_cancellation=True)
