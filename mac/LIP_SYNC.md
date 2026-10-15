# Optional mesh face and lip-sync trial

The original orb is still the default. Select **Settings → Visualization →
Mesh face** to try the approved green wireframe portrait. The choice is saved
in this browser. You can switch visualizations during a conversation without
closing the microphone or restarting a model.

This is a **synchronized visual prototype**, not a production-quality talking
head. The 24-image contact sheet cannot supply the continuous lip, teeth,
tongue and cheek deformation of a rigged 3D face. In particular, crossfading
two raster mouth images can show ghosting. Judge this trial on actual speech
before adopting it. The timing layer is renderer-independent so a proper
blend-shape rig can replace the raster renderer later.

## Install and try

For a sample-only preview after installing the dependencies, run
`bash mac/preview-mesh` and open `http://127.0.0.1:18182/?visualizer=mesh`.
Use **Settings > Preview speech**, not the microphone button. This mode runs
without conversation models; Ctrl-C stops it. The microphone path in stub
mode is only a UI demonstration, not a real conversation.

In an existing Mac installation, from the repository root:

```sh
uv pip install --python mac/.venv/bin/python --no-deps --only-binary=:all: -r mac/requirements-lipsync.lock.txt
./mac/start-voice-prototype
```

For a new installation, `./mac/setup-mac --with-lip-sync` installs the optional
aligner along with the normal environments. Model-download flags and Breeze
licence acceptance are the same as in the main README.

Open **http://127.0.0.1:18180/?visualizer=mesh**. First select **Settings →
Preview speech**: this plays the existing 7.6-second voice sample with its
aligned mouth shapes, without opening a microphone or voice session.
**Preview pose** lets you inspect all 24 mouth shapes and expressions.

Then click **Allow microphone & start** for a real conversation. Start with
Mesh face selected to request aligned audio for that session. If you started
with the orb, switch to Mesh face, Stop, and Start again to enable alignment.
During an aligned session you can switch back and forth instantly. The URL
`?visualizer=blob` temporarily selects the original visualization without
overwriting the saved setting. `/live/` and its static assets work too.

## How the timing works

The optional path buffers each existing TTS clause, aligns the exact generated
PCM and its transcript with PocketSphinx, and sends phoneme boundaries before
the matching audio. It uses a separate CPU process and never contacts a
speech service. The original orb session retains the existing streaming path.
Speculative replies keep both their cues and audio hidden until committed;
interruption discards both.

The browser schedules the cues at the actual AudioBufferSource start time,
uses the device-output clock when available, and blends adjacent phoneme
poses over short overlaps. Bilabial closures and silence have their own
poses. Mouth movement follows playback through the tail after `reply_end`,
and does not start just because reply text arrived. No loudness-to-mouth
heuristic or equal-duration word estimate is used.

Each aligned audio segment also reports its scheduled playback end to the
server. This keeps the session from ending early when alignment leaves a
gap between clauses; the original streaming-orb protocol is unchanged.

There is a latency tradeoff: a complete clause must be synthesized before
alignment and playback can start. Additional alignment time depends on the
machine and clause. The included sample took about 0.3 seconds to align in
the development environment; that is not a Mac performance measurement.

The bundled alignment model is English. Words in its lexicon use transcript
forced alignment; names outside the lexicon and digits use a less accurate
audio-only phoneme recognizer and show a notice. Non-English speech is not
validated. Alignment errors leave the mouth at rest for that clause while
audio continues; the UI does not substitute invented lip timing. Other
expressions are driven by listening/thinking/error state or manual preview,
not inferred emotional meaning.

## Checks

```sh
mac/.venv/bin/python -m unittest discover -s tests -p test_lipsync.py -v
node --test tests/test_lip_sync_timeline.cjs
cd mac
npm install
npx playwright install chromium
npm run test:visualizer
```

The browser check starts the model-free stub server, uses a fake microphone,
and scripts real PCM and phoneme-cue packets. It covers the audible preview,
all 24 poses, text before audio, playback after generation ends, interruption,
live switching, persisted preferences, Stop cleanup, mobile layout and the
`/live/` path. Set `SPEAKRAIL_TEST_PYTHON` to a different Python environment
containing aiohttp, numpy, scipy and the optional PocketSphinx wheel. A URL
argument uses an already-running stub server instead.
