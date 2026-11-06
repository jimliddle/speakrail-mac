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

## Lip-sync recovery and cards: 4 November 2026

The publication checks passed on the same Mac:

- 32 Python tests under `tests/`, including real bundled-sample alignment,
  failed and partial forced alignment, held phones, decoder reuse, clause
  limits, pacing, interruption and playback acknowledgements.
- Three launcher checks with mocked model services. The standalone launcher's
  capability settings are unchanged.
- Seven JavaScript animation and lip-timeline tests.
- The Chromium visualizer check, including real greeting alignment, scripted
  speech packets, silent successful fallback, visible alignment failure,
  persisted avatar choices, blocked browser storage, interruption and Stop.
- Grouped-card fixtures with complete and partial counts at 1440x900, 390x844
  and 844x390. Checks cover selected IDs, replacement of same-turn cards,
  scrolling and Start-button clearance. Screenshots were inspected locally.

Run these checks from the repository root:

```sh
mac/.venv/bin/python -B -m unittest discover -s tests -p 'test_*.py'
mac/.venv/bin/python -B -m unittest discover -s mac -p test_avatar_launcher.py
node --test tests/test_lip_sync_timeline.cjs tests/test_avatar_motion.cjs
node mac/test_visualizer.cjs
```

The UI accepts optional `groups` in a `search_done` event. Each group supplies
`region`, `requested_count` and `results`; each result includes its title,
source, URL and stable `brief_id`. An integration must send the same selected
items it speaks. These tests exercise that display contract, not Tavily or a
news-ranking system. General web search remains disabled in the Mac launcher.

Earlier full-playback tests in the separate local harness exercised six
synthetic stories, including a deliberately broken final-clause alignment.
The recovered clause had continuous timings; its previous acoustic decode had
held one phone for almost six seconds. Those tests motivated these fixes but
do not substitute for a fresh standalone model-stack or clean-install test.
Private harness configuration, transcripts and raw test artifacts are not
part of this repository.

## Results layout checks

From the repository root, run `node mac/test_activity_ui.cjs` after installing
the browser-test dependencies described above. This serves the bundled UI and
avatar assets on a temporary loopback port; it does not start models, access a
microphone, or call a search service.

Synthetic events exercise long agent answers, weather results, grouped news,
failed tools, session notes, and reset. The checks cover desktop, portrait mobile
and landscape layouts, canvas pixels and animation, caption and panel scrolling,
Escape and focus restoration, safe source links, and the 12-entry activity limit.
Screenshots and a report go to the ignored `mac/activity-ui-results/` directory.
The existing visualizer test also checks grouped news in the new details panel.

On 5 November 2026, both browser suites passed at 1440x900, 390x844 and 844x390.
The generated screenshots were inspected locally. The 32 Python tests, three
mocked launcher checks and seven JavaScript animation/timeline tests also passed.

These UI tests do not establish live agent or research performance.

## Local memory: 6 November 2026

The standalone publication checks passed with synthetic data:

- 52 Python tests under `tests/`, including 20 memory tests. They cover storage
  permissions, revisions, size limits, expiry, confirmation, authenticated API
  access, Host/Origin checks, session exclusion, reset and speculative replies.
- Five mocked launcher checks, including opt-in forwarding and owner-only
  access-key logs. They do not start inference services.
- Seven existing JavaScript animation and speech-timing checks.
- The real standalone server in stub mode, tested through Chromium: access
  cookie, editor layout at three viewport sizes, save/edit/delete, persistence
  after server restart, and read-only editing while a voice session is active.
- The existing avatar/results browser test, with synthetic tool output.
- All 24 existing model-free conversation-controller scenarios passed their
  assertions with memory off. That older fixture emitted pending-task cleanup
  warnings; this is not a clean shutdown or long-session reliability result.

From the repository root, after installing the existing Mac test dependencies:

```sh
mac/.venv/bin/python -B -m unittest discover -s tests -p 'test_*.py'
mac/.venv/bin/python -B -m unittest discover -s mac -p test_avatar_launcher.py
PYTHON="$PWD/mac/.venv/bin/python" node tests/test_memory_ui.cjs
node mac/test_activity_ui.cjs
mac/.venv/bin/python tests/test_session.py
```

The memory browser test starts and stops its own model-free server, uses a
temporary memory directory, blocks external browser requests and removes the
test files. Screenshots go to ignored `artifacts/memory-ui/`. It never reads
an existing user's memory directory or opens a physical microphone.

Before the standalone port, a separate local integration passed synthetic
speech save/confirm, close/reopen, recall, update/confirm and delete/confirm
through the actual ASR and TTS stack. The public session tests exercise the
ported handlers without model calls. A fresh full-model standalone memory
run, clean installation, other accents and long sessions remain untested.
No private recordings, notes, paths or harness configuration are published.

## Remaining Checks

Long conversations, noisy microphones, room echo, other languages, smaller
Macs, simultaneous agent workloads and the Claude Bridge through this Mac
launcher. A successful local trial is not evidence for those cases.
