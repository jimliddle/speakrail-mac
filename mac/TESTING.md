# Tests

The original port was tested on an M5 Max with 128 GB memory on 9 October
2026. These are small tests on one machine. They do not establish minimum
hardware requirements or reliability across accents, room noise and long calls.

## Run the tests

Run setup first, including the model downloads. From `mac/`:

```sh
.mlx-venv/bin/python test_gemma_mlx.py
.mlx-venv/bin/python test_architecture.py
MLX_ENABLE_TF32=0 .mlx-venv/bin/python test_prefix_cache.py
MLX_ENABLE_TF32=0 .mlx-venv/bin/python test_http_model.py
.venv/bin/python test_speech.py --mode full
./start-voice-prototype --test --port 18181
```

The speech and full-loop tests start their own services and stop them when
finished. Stop other model workloads when measuring latency. The full-loop
test uses macOS's installed Samantha voice to ask a question and interrupt
a longer answer. It acknowledges playback over the socket; it does not
measure sound coming out of a speaker.

For the browser test, start the voice app in another terminal, then:

```sh
npm install
npx playwright install chromium
node test_browser.cjs http://127.0.0.1:18180/
```

This generates its own synthetic microphone input using `say` and FFmpeg.
It checks the reply, non-silent Web Audio playback, Stop cleanup, mobile
controls, settings, canvas animation and page overflow at 1440x900 and
390x844. It does not open the real microphone. Browser-test npm packages and
generated files are ignored by Git. Playwright manages its own browser cache.

## Results from the original trial

| Test | Result |
| --- | --- |
| Int4 conversion | All 16 values and scales preserved; invalid inputs rejected |
| Small random architecture comparison | Transformers/MLX full and incremental logits within 1e-6 |
| Real-model decisions | Listen, speak, yield and continue examples passed |
| Prefix snapshots | Session/model isolation, branch isolation, bounds and expiry passed |
| Cached vs uncached growing histories | Identical logits in the two tested cases |
| HTTP client | Decisions, streaming, special stops, cancellation, interleaved base/LoRA requests passed |
| Reference voice ASR | Zero word errors, with and without a peek |
| ASR peek | About 191 ms round trip; final transcript unchanged |
| Breeze synthesis | Generated sentence transcribed without word errors |
| Breeze cancellation | Cancelled stream released the service; next request succeeded |
| Full voice loop | Correct spoken answer to the capital-of-France question |
| Spoken interruption | Audio stopped through the controller's early-start undo path |
| Chromium | Correct reply, non-silent playback, Stop released audio devices |

Timing details:

- First Breeze request: 819 ms to first audio; repeated request: 153 ms.
- 3.76 seconds of warm speech generated in 1.35 seconds.
- After 1.51 seconds of session initialisation, the short full-loop reply
  began about 928 ms after input ended.
- An earlier probe sent audio before initialisation and took 4.27 seconds
  from input end to first output. Starting the models and starting a voice
  session both have warm-up costs.
- Spoken interruption stopped the controller about 1.16 seconds after the
  interruption began. This was one example, not a turn-taking benchmark.
- A 4,096-token prompt took 2.85 seconds to prefill, about 15 ms for an exact
  cache hit and 53 ms for a short append. The earlier 1,024-token append took
  316 ms. Compilation and warm-up affect these measurements.

Raw audio, transcripts, screenshots and logs from the trial are not published.
The scripts generate local results files so the tests can be repeated.
The packaged setup script has been checked in plan mode; a complete install
on a second, clean Mac has not been tested.

## What remains untested

Long conversations, noisy microphones, room echo, other languages, smaller
Macs, simultaneous agent workloads and the Claude Bridge through this Mac
launcher. A successful local trial is not evidence for those cases.
