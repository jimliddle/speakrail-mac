# Local service security

The native Mac launcher separates the browser UI from the model services.
Binding to loopback alone is not a browser security boundary: a page from another
site can still try to send requests to a local port.

## What changed

- Gemma and Breeze reject browser Origin and Fetch Metadata headers, invalid
  Host values and ambiguous security headers before processing a request.
- The native ASR HTTP parser applies the same checks before reading uploads or
  opening streams. The ASR WebSocket bridge checks the handshake before creating
  a recognition session.
- Model operations require `X-Speakrail-Client: local-controller`. The Python
  controller sends it; browsers are refused preflight access. This marker is
  public, not a password.
- The loopback UI accepts its own page, rejects cross-site operations and checks
  the actual listening port. Pages cannot be embedded in another site's frame.
  Opt-in memory retains its separate access token and confirmation rules.
- Startup checks reject an HTTP backend that accepts a foreign Origin on its
  health endpoint. This catches an old, unpatched executable; it is not a full
  security audit of an arbitrary service.

These checks do not protect against malicious software running as your user,
browser extensions with elevated permissions, or a compromised local page.
Do not expose these ports through a tunnel or bind them to a network interface.
Memory and recordings, when enabled, remain private local files, not encrypted
storage or a multi-user account system.

## Update an existing installation

Stop this stack in its launch terminal before rebuilding. Pull the `macos`
branch, then run:

```sh
./mac/setup-mac --with-lip-sync
./mac/start-voice-prototype
```

Without `--download-models`, setup does not download weights. It may fetch pinned
source dependencies or install packages missing from the local environments.
Existing model files and memory are not changed. Reopen the local launch URL;
memory access links change when their launcher creates a new token.

Setup applies `mac/patches/audio-local-access.patch` to the pinned audio.cpp
revision before building. `mac/patch_audio.py` accepts either pristine source or
the exact reviewed result. It refuses a different revision, staged edits,
unrelated tracked changes, symlinks and conflicting patch content. Repeated
setup does not overwrite local edits or apply the patch twice.

For a manual ASR launch, build the patched source and use
`services/asr/bridge.py --host 127.0.0.1 --local-controller-only` with your other
ASR arguments. The Mac launcher supplies this flag. The original Docker/NVIDIA
path is not covered by this release; do not assume it has these protections.
Start Breeze through `mac/breeze_local.py`, not directly through its upstream
API module. Its WebSocket listener remains disabled in the Mac launcher.

## Checks

From the repository root, after setup:

```sh
mac/.venv/bin/python -B -m unittest discover -s mac -p test_patch_audio.py -v
mac/.venv/bin/python -B -m unittest discover -s mac -p test_backend_security.py -v
mac/.venv/bin/python -B -m unittest discover -s mac -p test_native_security.py -v
PYTHONPATH=app mac/.venv/bin/python -B -m unittest discover -s tests -p test_local_browser.py -v
```

These use temporary fixtures, not model weights. The native test compiles the
actual patched HTTP parser with a small handler; it checks early rejection and
a valid chunked stream, not speech recognition accuracy. The Python tests check
HTTP, ASGI and WebSocket boundaries and legitimate controller requests.

The existing `node mac/test_preview_only.cjs` browser test also passed with the
guard enabled, including sample playback and settings at desktop/mobile sizes.
It needs the repository's Playwright environment and optional aligner. Full
model inference and Windows deployment were not repeated for this publication.
A fresh installation on a second Mac remains untested.

## Recovery

If startup reports a missing boundary, stop the affected stack and rebuild it.
Do not work around the error by removing the guard or enabling wildcard origins.
If setup reports source changes, preserve them and review the dependency checkout
before proceeding. An older checkout lacks these protections: keep it stopped
when rolling back. Do not delete shared weights or memory as part of rollback.
