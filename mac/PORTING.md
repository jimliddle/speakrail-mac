# Mac Port Changes

Baseline: upstream Speakrail `49798e8e72c8a8429cb4d005840a6af389ececb7`.
Port date: 2026-10-09. Maintainer: Jim Liddle. Source additions use Apache-2.0.

The original app, model download manifest, training assets and upstream
history are retained. This is a native serving adaptation, not a new voice
assistant or replacement training effort.

## Additions

- `gemma_mlx.py`: loads the exact patched int4 QAT weights, tied embeddings,
  trained token rows and LoRA through MLX; no requantisation.
- `mlx_server.py`: implements the specific token-ID completions/decision/SSE
  protocol the original controller needs, including model selection and stops.
- `prefix_cache.py`: memory-only, eight-entry/2-GiB/300-second cache, explicit
  session/model partitioning, clone-on-use, exact-prefix reuse only.
- `local_stack.py`, `mac_ui.py`, launch scripts: loopback-only owned-process
  startup/cleanup, one UI session, foreign-origin WebSocket refusal. No daemon.
- `setup.py`, `sources.json`, dependency snapshots and fetch scripts:
  reproducible pinned inputs without committing models or installed libraries.
- Real-model and browser probes: documented separately in `TESTING.md`.

## Modified Upstream Files

- `app/llm_engine.py`: per-Engine random session salt, only when
  `SPEAKRAIL_CACHE_SESSION=1`; unchanged behaviour without that flag.
- `app/web/live/index.html`: search selector reflects the Mac launcher's
  disabled general web search. Weather is a distinct tool and remains enabled.
- `app/web/live/live.js`: disabled search persistence; ignore late messages
  after Stop, close the socket/audio contexts, protect against an old socket
  closing a newly started session.
- `app/web/live/live.css`: wrap active controls on narrow screens.
- Original README moved to `README.upstream.md` and labelled as NVIDIA
  instructions; new README covers this fork. Original licence retained;
  NOTICE extended without removing upstream notices.

No source from audio.cpp or Breeze's serving repositories is vendored here.
Their pinned source checkouts are created locally by setup and retain their
licences. The shipped upstream synthetic voice reference is retained under
its original non-commercial terms, not relicensed as Apache source code.

## Boundaries

This checkpoint predates personal-harness integration. The Mac launcher does
not enable Claude Bridge or a hosted frontier model, and it strips inherited
API-key/token/secret environment variables from service subprocesses.
That is not a network sandbox: weather and Google Fonts can access the
internet. No claim of complete offline operation is made.

Apple Silicon inference is experimental. Long-session reliability,
simultaneous heavy agents and memory pressure need further testing. The main
launcher caps the conversation backend rather than promising unbounded context.
