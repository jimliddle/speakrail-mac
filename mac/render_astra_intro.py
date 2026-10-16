"""Render the trial greeting locally without changing the voice reference."""
import asyncio
from test_speech import ROOT, Services, start_tts, synthesize


async def main():
    services = Services()
    try:
        port, _ = await start_tts(services)
        text = (ROOT.parent / "app/voices/astra_intro.txt").read_text().strip()
        print(await synthesize(port, text, "../app/voices/astra_intro.wav"))
    finally:
        services.close()


if __name__ == "__main__":
    asyncio.run(main())
