"""Start the isolated native voice stack; Ctrl-C stops only its own children."""
import argparse
import asyncio
import json
import signal
import socket
import subprocess
import time

import aiohttp

from test_speech import ROOT, VOICE, Services, free_port, pcm16, ready, start_asr, start_tts


async def start_stack(services, ui_port):
    # Refuse a busy UI port before allocating model memory.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", ui_port))
    asr, _ = await start_asr(services)
    print("Recognition and turn detector ready", flush=True)
    tts, _ = await start_tts(services)
    print("Speech output ready", flush=True)
    llm = free_port()
    process = services.start("gemma-service", [ROOT / "start-gemma-prototype", "--port", llm])
    await ready(process, llm, "/health", timeout=180)
    print("Conversation model ready", flush=True)
    process = services.start("voice-ui", [ROOT / ".venv/bin/python", ROOT / "mac_ui.py",
                                          "--host", "127.0.0.1", "--port", ui_port,
                                          "--voice", VOICE, "--no-phrase-cache", "--search", "off",
                                          "--sessions-dir", ""], extra_env={
        "ASR_URL": f"ws://127.0.0.1:{asr}/v1/transcribe",
        "TTS_URL": f"http://127.0.0.1:{tts}/v1/audio/speech",
        "LLM_URL": f"http://127.0.0.1:{llm}/v1/completions",
        "LLM_LORA": "speakrail", "LLM_BASE_MODEL": "speakrail-base",
        "SPEAKRAIL_TOKENIZER_DIR": str(ROOT / "tokenizer"), "SPEAKRAIL_CACHE_SESSION": "1",
        "NOTES": "1", "INTERJECT": "1", "SESSIONS_DIR": ""})
    await ready(process, ui_port, "/", timeout=90)
    return {"ui": ui_port, "asr": asr, "tts": tts, "llm": llm}


async def probe(port, interrupt=False):
    fixture = ROOT / "test-question.aiff"
    question = "Tell me about the history of Paris." if interrupt else "What is the capital of France?"
    subprocess.run(["say", "-v", "Samantha", "-o", str(fixture), question], check=True)
    pcm = pcm16(fixture)
    stop_pcm = None
    if interrupt:
        stop_fixture = ROOT / "test-stop.aiff"
        subprocess.run(["say", "-v", "Samantha", "-o", str(stop_fixture), "Stop talking."], check=True)
        stop_pcm = pcm16(stop_fixture)
    events, audio = [], bytearray()
    first_audio = None
    ended = asyncio.Event()
    brain_ready = asyncio.Event()
    start = time.monotonic()
    async with aiohttp.ClientSession() as http:
        async with http.get(f"http://127.0.0.1:{port}/ws", headers={"Origin": "https://untrusted.example"}) as r:
            assert r.status == 403
        async with http.ws_connect(f"http://127.0.0.1:{port}/ws") as ws:
            async def receiver():
                nonlocal first_audio
                seen = set()
                async for message in ws:
                    if message.type == aiohttp.WSMsgType.TEXT:
                        event = json.loads(message.data)
                        events.append({**event, "received_s": time.monotonic() - start})
                        if event["type"] == "error":
                            raise RuntimeError(event)
                        if event["type"] == "brain":
                            brain_ready.set()
                        if event["type"] == ("stop_audio" if interrupt else "reply_end"):
                            ended.set()
                    elif message.type == aiohttp.WSMsgType.BINARY:
                        if first_audio is None:
                            first_audio = time.monotonic() - start
                        utt = int.from_bytes(message.data[:2], "little")
                        if utt not in seen:
                            await ws.send_json({"cmd": "play_start", "utt": utt, "delay_ms": 0})
                            seen.add(utt)
                        audio.extend(message.data[4:])
            task = asyncio.create_task(receiver())
            try:
                await asyncio.wait_for(brain_ready.wait(), 30)
                initialization_s = time.monotonic() - start
                start = time.monotonic()
                stop_tick = None
                for tick in range(750):
                    if task.done():
                        task.result()
                    if ended.is_set():
                        break
                    pos = tick * 2560
                    chunk = pcm[pos:pos + 2560] if pos < len(pcm) else bytes(2560)
                    if interrupt and first_audio is not None and time.monotonic() - start > first_audio + 0.5:
                        if stop_tick is None:
                            stop_tick = tick
                        stop_pos = (tick - stop_tick) * 2560
                        chunk = stop_pcm[stop_pos:stop_pos + 2560] if stop_pos < len(stop_pcm) else bytes(2560)
                    await ws.send_bytes(chunk)
                    await asyncio.sleep(max(0, start + (tick + 1) * 0.08 - time.monotonic()))
                assert ended.is_set(), "No completed spoken reply within 60 seconds"
                await ws.send_json({"cmd": "stop"})
                await asyncio.wait_for(task, 10)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                label = "voice-interrupt" if interrupt else "voice-loop"
                (ROOT / f"{label}-events.json").write_text(json.dumps(events, indent=2) + "\n")
    reply = "".join(e.get("text", "") for e in events if e["type"] == "reply_delta")
    assert audio and (interrupt or "Paris" in reply), reply
    report = {"reply": reply, "first_audio_s_from_input_start": first_audio,
              "input_audio_s": len(pcm) / 32000,
              "end_of_input_to_first_audio_ms": (first_audio - len(pcm) / 32000) * 1000,
              "received_audio_s": len(audio) / 48000,
              "session_initialization_s": initialization_s,
              "decisions": [e for e in events if e["type"] == "decision"],
              "scope": "Real audio through original session engine; simulated playback acknowledgement, not a live microphone"}
    if interrupt:
        stops = [e for e in events if e["type"] == "stop_audio"]
        assert stop_tick is not None and stops
        report["stop_event"] = stops[-1]
        report["spoken_interrupt_to_stop_ms"] = (stops[-1]["received_s"] - stop_tick * 0.08) * 1000
    (ROOT / f"{label}-results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)


async def main(args):
    services = Services()
    stopped = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stopped.set)
    try:
        ports = await start_stack(services, args.port)
        print(f"Speakrail Mac prototype: http://127.0.0.1:{ports['ui']}/", flush=True)
        print("Local models only. Search/Claude tools/recording off. Ctrl-C stops this stack.", flush=True)
        if args.test:
            await probe(ports["ui"])
            await probe(ports["ui"], interrupt=True)
        else:
            while not stopped.is_set():
                if any(p.poll() is not None for p, _ in services.children):
                    raise RuntimeError("A prototype service stopped; see experiment logs")
                try:
                    await asyncio.wait_for(stopped.wait(), 1)
                except asyncio.TimeoutError:
                    pass
    finally:
        services.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18180)
    parser.add_argument("--test", action="store_true")
    asyncio.run(main(parser.parse_args()))
