"""Local pitch-preserving tempo adjustment before phoneme alignment."""
import asyncio

PACES = (0.75, 0.85, 1.0)


def speech_pace(value):
    pace = float(value)
    if pace not in PACES:
        raise ValueError("Speech pace must be 0.75, 0.85 or 1.0")
    return pace


async def pace_pcm(pcm, pace):
    pace = speech_pace(pace)
    if pace == 1.0:
        return pcm
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-v", "error", "-f", "s16le", "-ar", "24000", "-ac", "1", "-i", "pipe:0",
        "-af", f"atempo={pace}", "-f", "s16le", "pipe:1",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        output, _ = await asyncio.wait_for(process.communicate(pcm), 15)
        if process.returncode or not output or len(output) % 2:
            raise RuntimeError("Local speech pacing failed")
        return output
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
