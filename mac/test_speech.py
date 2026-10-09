"""Real local speech probes, with owned-process cleanup and no microphone access."""
import argparse
import asyncio
import contextlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import time
import wave

import aiohttp
import numpy as np

ROOT = Path(__file__).resolve().parent
VOICE = ROOT.parent / "app/voices/female_a.wav"


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Services:
    def __init__(self):
        self.children = []

    def start(self, name, command, cwd=ROOT, extra_env=None):
        env = {k: v for k, v in os.environ.items()
               if not any(s in k.upper() for s in ("TOKEN", "API_KEY", "SECRET"))}
        env.update(HF_HOME=str(ROOT / "hf-home"), HF_HUB_OFFLINE="1",
                   TRANSFORMERS_OFFLINE="1", MLX_ENABLE_TF32="0", PYTHONUNBUFFERED="1")
        env.update(extra_env or {})
        log = open(ROOT / f"{name}.log", "w")
        process = subprocess.Popen([str(x) for x in command], cwd=cwd, env=env,
                                   stdout=log, stderr=subprocess.STDOUT)
        self.children.append((process, log))
        return process

    def close(self):
        for process, _ in reversed(self.children):
            if process.poll() is None:
                process.terminate()
        for process, log in reversed(self.children):
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
            log.close()


async def ready(process, port, path=None, timeout=180):
    start = time.monotonic()
    async with aiohttp.ClientSession() as http:
        while time.monotonic() - start < timeout:
            if process.poll() is not None:
                raise RuntimeError(f"Service exited {process.returncode}; see its log")
            try:
                if path:
                    async with http.get(f"http://127.0.0.1:{port}{path}",
                                        timeout=aiohttp.ClientTimeout(total=2)) as response:
                        if response.status == 200:
                            return time.monotonic() - start
                else:
                    _, writer = await asyncio.open_connection("127.0.0.1", port)
                    writer.close()
                    await writer.wait_closed()
                    return time.monotonic() - start
            except (OSError, asyncio.TimeoutError, aiohttp.ClientError):
                pass
            await asyncio.sleep(0.25)
    raise TimeoutError(f"Service on {port} not ready in {timeout}s")


async def start_asr(services):
    port, bridge_port = free_port(), free_port()
    config = {"host": "127.0.0.1", "port": port, "backend": "metal", "device": 0,
              "threads": 4, "lazy_load": False, "busy_timeout_ms": 0,
              "models": [{"id": "voxtral-rt", "family": "voxtral_realtime",
                          "path": str(ROOT / "models/voxtral/voxtral-mini-4b-realtime-2602-q8_0.gguf"),
                          "task": "asr", "mode": "streaming", "session_options": {
                              "voxtral_realtime.turn_head": str(ROOT / "models/turn_head/turn_head.vxth"),
                              "voxtral_realtime.stream_chunk_samples": "128"}}]}
    path = ROOT / "asr-mac-config.json"
    path.write_text(json.dumps(config, indent=2) + "\n")
    process = services.start("asr-native", [ROOT / "audio.cpp/build/mac-eval/bin/audiocpp_server",
                                            "--config", path])
    seconds = await ready(process, port, "/health")
    bridge = services.start("asr-bridge", [ROOT / ".venv/bin/python", ROOT.parent / "services/asr/bridge.py",
                                          "--host", "127.0.0.1", "--port", bridge_port,
                                          "--acpp", f"127.0.0.1:{port}", "--model", "voxtral-rt",
                                          "--head", ROOT / "models/turn_head/turn_head.vxth.json"])
    await ready(bridge, bridge_port)
    return bridge_port, seconds


async def start_tts(services):
    port = free_port()
    process = services.start("tts-mlx", [ROOT / ".tts-venv/bin/python", "-m", "breeze_infer.api",
                                         ROOT / "models/breeze-mlx-8bit", "--backend", "mlx",
                                         "--host", "127.0.0.1", "--port", port, "--ws-port", "disabled",
                                         "--voices-dir", ROOT / "test-voices", "--chunk-first", "1",
                                         "--chunk-max", "1"], cwd=ROOT / "breeze-mlx-candidate")
    seconds = await ready(process, port, "/health", timeout=240)
    return port, seconds


async def synthesize(port, text, filename=None, abort=False):
    data = aiohttp.FormData()
    data.add_field("text", text)
    data.add_field("ref_text", VOICE.with_suffix(".txt").read_text().strip())
    data.add_field("ref_audio", VOICE.read_bytes(), filename=VOICE.name, content_type="audio/wav")
    data.add_field("seed", "42")
    data.add_field("cfg_scale", "1.0")
    start = time.monotonic()
    pcm = bytearray()
    first = None
    chunks = 0
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as http:
        async with http.post(f"http://127.0.0.1:{port}/v1/audio/speech", data=data) as response:
            if response.status != 200:
                raise RuntimeError(f"TTS {response.status}: {await response.text()}")
            sr = int(response.headers.get("X-Sample-Rate", 24000))
            async for chunk in response.content.iter_any():
                if first is None:
                    first = time.monotonic() - start
                pcm.extend(chunk)
                chunks += 1
                if abort:
                    response.close()
                    break
    elapsed = time.monotonic() - start
    assert pcm and len(pcm) % 2 == 0 and sr == 24000
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
    assert np.sqrt(np.mean(samples ** 2)) > 0.005
    if filename:
        with wave.open(str(ROOT / filename), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sr)
            wav.writeframes(pcm)
    return {"text": text, "first_audio_ms": first * 1000, "elapsed_s": elapsed,
            "audio_s": len(samples) / sr, "generation_rtf": elapsed / (len(samples) / sr),
            "chunks": chunks, "aborted": abort, "file": filename}


def pcm16(path):
    return subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ar", "16000",
                           "-ac", "1", "-f", "s16le", "pipe:1"], check=True,
                          capture_output=True).stdout


def words(text):
    return re.findall(r"[a-z0-9']+", text.lower())


def wer(reference, actual):
    a, b = words(reference), words(actual)
    prev = list(range(len(b) + 1))
    for i, token in enumerate(a, 1):
        row = [i]
        for j, other in enumerate(b, 1):
            row.append(min(row[-1] + 1, prev[j] + 1, prev[j - 1] + (token != other)))
        prev = row
    return prev[-1] / max(1, len(a))


async def transcribe(port, path, peek=False):
    pcm = pcm16(path) + bytes(16000 * 2)
    events = []
    start = time.monotonic()
    url = f"http://127.0.0.1:{port}/v1/transcribe?sample_rate=16000&turn_probs=true"
    async with aiohttp.ClientSession() as http, http.ws_connect(url) as ws:
        async def receive():
            async for message in ws:
                if message.type == aiohttp.WSMsgType.TEXT:
                    event = json.loads(message.data)
                    events.append({**event, "received_s": time.monotonic() - start})
                    if event["type"] == "error":
                        raise RuntimeError(event)
                    if event["type"] == "session.ended":
                        return
        task = asyncio.create_task(receive())
        try:
            for pos in range(0, len(pcm), 2560):
                await ws.send_bytes(pcm[pos:pos + 2560])
                if peek and pos == 2560 * 50:
                    await ws.send_json({"type": "peek", "id": "probe", "frames": 8})
                await asyncio.sleep(max(0, start + (pos + 2560) / 32000 - time.monotonic()))
            await ws.send_json({"type": "input_audio.end"})
            await asyncio.wait_for(task, 30)
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
    transcripts = [ev for ev in events if ev["type"] == "transcript"]
    turns = [ev for ev in events if ev["type"] == "turn"]
    peeks = [ev for ev in events if ev["type"] == "transcript.peek"]
    assert transcripts and turns and any(ev["type"] == "session.ended" for ev in events)
    assert all(len(ev["p"]) == 5 and all(0 <= p <= 1 for p in ev["p"]) for ev in turns)
    if peek:
        assert peeks and not any("error" in ev for ev in peeks), peeks
    return {"text": "".join(ev["text"] for ev in transcripts).strip(), "events": events,
            "first_transcript_s": transcripts[0]["received_s"], "turn_events": len(turns),
            "peek": peeks, "elapsed_s": time.monotonic() - start}


async def main(mode):
    services = Services()
    report = {}
    try:
        port, seconds = await start_asr(services)
        print(f"ASR ready in {seconds:.2f}s", flush=True)
        reference = VOICE.with_suffix(".txt").read_text().strip()
        for peek in (False, True):
            result = await transcribe(port, VOICE, peek)
            result["word_error_rate"] = wer(reference, result["text"])
            report["asr_peek" if peek else "asr"] = result
            print({k: v for k, v in result.items() if k != "events"}, flush=True)
            assert result["word_error_rate"] <= 0.15
        report["asr_startup_s"] = seconds
        report["reference"] = reference
        report["peek_preserves_transcript"] = report["asr"]["text"] == report["asr_peek"]["text"]
        assert report["peek_preserves_transcript"]
        if mode == "full":
            tts, seconds = await start_tts(services)
            report["tts_startup_s"] = seconds
            print(f"TTS ready in {seconds:.2f}s", flush=True)
            phrase = "The capital of France is Paris. What would you like to explore next?"
            for label in ("cold", "warm"):
                result = await synthesize(tts, phrase, f"tts-{label}.wav")
                report[f"tts_{label}"] = result
                print(result, flush=True)
            result = await transcribe(port, ROOT / "tts-warm.wav")
            result["word_error_rate"] = wer(phrase, result["text"])
            report["tts_recognized"] = result
            print({k: v for k, v in result.items() if k != "events"}, flush=True)
            assert result["word_error_rate"] < 0.2
            report["tts_abort"] = await synthesize(tts, "This is a deliberately long answer. " * 12, abort=True)
            await asyncio.sleep(1)
            report["tts_after_abort"] = await synthesize(tts, "Yes, I have stopped. How can I help?", "tts-after-abort.wav")
            print(report["tts_after_abort"], flush=True)
    finally:
        services.close()
        (ROOT / "speech-results.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["asr", "full"], default="asr")
    asyncio.run(main(parser.parse_args().mode))
