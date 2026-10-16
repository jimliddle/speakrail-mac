"""Render the trial greeting locally without changing the voice reference."""
import asyncio
import argparse
import tempfile
import wave
from pathlib import Path
from test_speech import ROOT, Services, start_tts, synthesize


async def main(port=None):
    services = Services()
    try:
        if port is None:
            port, _ = await start_tts(services)
        text = (ROOT.parent / "app/voices/astra_intro.txt").read_text().strip()
        clauses = [clause.strip() for clause in text.split('. ') if clause.strip()]
        pcm = bytearray()
        with tempfile.TemporaryDirectory(prefix="astra-intro-") as directory:
            for index, clause in enumerate(clauses):
                if not clause.endswith(('.', '?', '!')):
                    clause += '.'
                filename = Path(directory) / f"clause-{index}.wav"
                await synthesize(port, clause, filename)
                if index:
                    pcm.extend(bytes(round(.35 * 24000) * 2))
                with wave.open(str(filename)) as sample:
                    pcm.extend(sample.readframes(sample.getnframes()))
        destination = ROOT.parent / "app/voices/astra_intro.wav"
        with wave.open(str(destination), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(24000)
            output.writeframes(pcm)
        print({"text": text, "audio_seconds": len(pcm) / 48000, "file": str(destination)})
    finally:
        services.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tts-port", type=int, help="reuse an already-running local TTS server")
    asyncio.run(main(parser.parse_args().tts_port))
