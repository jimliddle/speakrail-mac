# Speakrail Mac

An unofficial Apple Silicon port of [Speakrail](https://github.com/speakrail/speakrail). It uses Speakrail's original conversation controller,
models and browser UI, with Metal and MLX in place of the NVIDIA backends.

## Status

This is experimental. Tested on an Apple M5 Max with 128 GB unified memory.
Local speech recognition, conversation and speech output work together.
Automated tests include real model inference, synthetic microphone input,
browser audio playback and spoken interruption. It has also been tried in
conversation. Other Apple Silicon generations and memory sizes have not
been tested.

This version runs as a standalone voice assistant. Claude Bridge, hosted
models and general web search
are disabled by the Mac launcher. Do not use the original Docker instructions
for the native Mac path.

## Quick Start

Prerequisites: Apple Silicon macOS, Xcode Command Line Tools, Git, CMake,
FFmpeg and [uv](https://docs.astral.sh/uv/). Python 3.12 is used in three
isolated environments. Allow approximately **50 GB free disk for setup**;
the tested installation occupied about 24 GB after download-cache cleanup.
There is no validated minimum memory specification yet.

```sh
git clone --branch macos https://github.com/jimliddle/speakrail-mac.git
cd speakrail-mac

# First read the licensing section below, particularly Breeze's restrictions.
./mac/setup-mac --download-models --accept-breeze-noncommercial-license
./mac/start-voice-prototype
```

Open **http://127.0.0.1:18180/** in Chrome initially and click
**Allow microphone & start**. Give the session a couple of seconds to warm up.
Use headphones for the first trial. Try a short question, a follow-up, a
mid-sentence pause, and "Stop talking" during a longer response.

The setup script downloads specific versions of the dependencies, builds
audio.cpp, creates Python environments inside the repository and optionally
downloads the models. It does not install system packages or a background service. Inspect
its commands without making changes with `./mac/setup-mac --plan`.
The installer has not yet been tested on a second, clean Mac. The working
installation was built and tested in stages.

**Interrupt** cuts a reply. **Stop** ends microphone capture and playback;
models stay loaded. Ctrl-C in the launch terminal shuts down the stack.
Use `--port 18181` if port 18180 is occupied.

## Architecture

| Component | Native Mac path |
| --- | --- |
| Recognition and turn head | Voxtral Mini 4B realtime Q8, audio.cpp Metal, original Speakrail ASR bridge |
| Conversation and decisions | Gemma 4 12B QAT with Speakrail LoRA/token rows, narrow MLX completion server |
| Speech synthesis | Breeze TTS 2 MLX 8-bit through the pinned Mac-compatible Breeze implementation |
| Interaction | Original browser UI, notes, interjections, speculative responses and ducking |

The Gemma loader preserves the packed int4 weights rather than requantising
them. Prefix caching is bounded and separated by session and base/LoRA model.
The server currently caps prompts at 8,192 tokens and output at 512 tokens,
uses greedy sampling, and is not a general purpose vLLM replacement.
Pre rendered phrase caching is disabled.

## Local Inference, Not Network Isolated

**Gemma is local, it is not a connection to Google's Gemini service.**
All three inference servers listen on loopback. Session recording is off by
default. The main UI rejects foreign browser origins and allows one session
at a time. This is a local prototype, not a remotely exposed service.

Some original tools remain enabled: calculator, time, session notes/lists,
and **weather via Open-Meteo**. Weather sends the requested location and then
coordinates to that service; general web search being off does not disable
weather. Weather data attribution: [Open-Meteo](https://open-meteo.com/),
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
The browser also requests Google Fonts for typography. Neither is hosted
model inference. Model downloads require internet access during setup.

The upstream Claude Bridge source remains, but the Mac launcher does not enable it or connect to an account.

## Test Results

Results from short tests on the M5 Max:

| Probe | Result |
| --- | --- |
| Bundled sample transcription | No word errors in two runs |
| Warm TTS time to first audio | About 153 ms |
| Full-loop input end to first output, after session warm-up | About 928 ms |
| Spoken interruption to controller stop | About 1.16 seconds |
| Browser | Synthetic microphone, non-silent playback, desktop/mobile checks passed |

First-use latency is higher. These are not acoustic speaker-latency measurements
or an evaluation of accuracy across accents, noise and long conversations.
See [Mac testing](mac/TESTING.md), [port changes](mac/PORTING.md) and
[upstream documentation](README.upstream.md).

## Licensing and Credits

Speakrail and this port's source changes are distributed under **Apache-2.0**.
The original [LICENSE](LICENSE) and [NOTICE](NOTICE) are retained. Credit for
the original controller, training work, models and UI belongs to the
Speakrail authors and their dependencies; this fork adds the native Mac path.

**The complete voice stack is not unrestricted for commercial use.** Breeze
TTS 2 model weights, derivatives and generated speech are subject to the
**BreezeBlue Research and Non-Commercial License**. The bundled upstream
`app/voices/female_a.wav` reference is synthetic Breeze output and has those
terms too. A separate licence is required for commercial use. This differs
from the Apache-licensed serving source code.

Read the [Breeze licence](mac/licenses/BREEZE-MODEL-LICENSE.txt) and the
[third-party summary](mac/THIRD_PARTY.md). We publish no model weights,
downloaded tokenizers, virtual environments, generated test audio, recordings
or private test logs. Downloaded components retain their own terms.

## Removal

Stop the launch terminal, then delete the clone. Models, downloaded sources,
environments and runtime artifacts are contained under `mac/`. No SwiftBar
item, LaunchAgent or system-wide model configuration is installed.
