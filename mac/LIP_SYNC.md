# Optional mesh face and lip-sync trial

The original orb is still the default. Select **Settings → Visualization →
Rigged face** to try the green 3D face. The choice is saved
in this browser. You can switch visualizations during a conversation without
closing the microphone or restarting a model.

This is a **motion prototype**, not the final character. It uses the CC0 MPFB
avatar from TalkingHead, rendered by local Three.js files. Authored speech
shapes deform the lips, teeth and tongue together. No avatar service is called.

**Settings → Appearance** selects between **Portrait** (the default face
appearance) and **Plain rig**. The choice is saved independently of the
Orb/Rigged face selection and can change during speech without restarting it.

Portrait projects the original woman's image onto the facial geometry. UVs
are registered at rest, including a local correction at the lip seam, so the
texture follows the mouth deformations. A masked curved surface retains
the hair silhouette without placing a second mouth behind the moving lips.
A shader covers the photographed eyes with sampled skin and a lid line during
blinks. Teeth and tongue retain their own geometry and subdued materials.
The original PNG is unchanged, and Settings still links to it for comparison.

This is a front-facing texture treatment, not a reconstructed 3D likeness.
Portrait permits only small head turns; its hair uses an approximate scalp
depth, not a full hair model. Large expressions can stretch the texture;
blink detail is approximate. Plain rig
restores the previous materials, hair mesh, wire overlay and subtle idle head
movement. A fully turnable version of the woman still needs a custom model.
The old contact sheet is retained as a reference but is no longer animated.
WebGL2 is required; loading or context failure falls back to the original orb.
The uncompressed rig is about 35 MiB and loads only when selected. The first
speech preview waits for it to load before scheduling audio.

## Idle and listening movement

The face now makes small head turns and pitch adjustments, with occasional
gaze shifts and blinks while idle. Listening eases back to a neutral head
orientation, with a steadier gaze and a small brow lift. It adds no tilt or turn.
Thinking has a different head orientation. Transitions ease instead of snapping between
poses. These are UI-state cues, not inferred emotions or semantic nods.

The head and neck bones drive the motion. The hair surface is attached to the
head bone at the frontal scalp depth; the bust is not translated, rotated or
scaled. The rig deforms the neck between the moving head and nearly stationary
shoulders. This replaces
the first motion attempt, which moved the whole composition and looked like
a rotating picture. Gaze uses a small masked texture offset around the irises.
The phoneme-driven lips remain independent of this motion.

The first hair layer sat behind the skull. Although attached to the right bone,
it moved differently from the face during turns. The curved surface corrects
that depth mismatch. Browser tests compare forehead and hairline displacement
in yaw and pitch and check for pixel changes at the crown.

To compare without a microphone, use **Settings → Preview pose → Listening**
or **Thinking**, then return to **Automatic** or **Rest** for idle. Other manual
poses remain still for inspection. Reduced-motion preferences disable head
movement, automatic gaze shifts and automatic blinks. Fixed expression previews
and speech articulation remain available.

## Install and try

### Astra conversation trial

Run `bash mac/start-astra-trial` from the repository root, then open
`http://127.0.0.1:18183/?visualizer=mesh` when the models are ready. This is a
separate local conversation server, not the sample-only page on port 18182.
Click **Allow microphone & start**, grant microphone permission, and speak.
**Interrupt** stops the reply; **Stop** ends the session and releases the
microphone. Ctrl-C in the launch terminal unloads this trial's model services.
Closing a tab or pressing Stop does not unload the models.

The conversation prompt names the assistant Astra. **Settings > Preview speech**
plays "Hi, I'm Astra, how is your day going today?" before starting a session.
The greeting is a separate locally generated sample; the original synthetic
voice reference is unchanged. It does not automatically play on connection.
Use `mac/.venv/bin/python mac/render_astra_intro.py` to regenerate it.

This launcher disables web search, local tools, hosted agents, session recordings
and optional listening notes (unsupported by the local completions adapter).
It retains the normal conversation history for the current connection. The
diagnostic service logs can contain transcribed speech and replies, so treat
`mac/*-ui.log` and the other runtime logs as private. The launcher does not
modify SwiftBar or the private voice-agent integration. A busy port is an error;
use `--port` to choose another one rather than stopping an unrelated service.

### Sample-only preview

For a sample-only preview after installing the dependencies, run
`bash mac/preview-mesh` and open `http://127.0.0.1:18182/?visualizer=mesh`.
Click **Preview speech** below the face (also available in Settings).
This mode runs without conversation models and does not offer microphone
sessions; Ctrl-C stops it. The separate `--stub` mode remains available for
testing the conversation UI.

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
Rigged face selected to request aligned audio for that session. If you started
with the orb, switch to Rigged face, Stop, and Start again to enable alignment.
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
npm run test:preview
npm run test:rig
npm run test:motion
```

The browser check starts the model-free stub server, uses a fake microphone,
and scripts real PCM and phoneme-cue packets. It covers the audible preview,
all 24 poses, text before audio, playback after generation ends, interruption,
live switching, persisted preferences, Stop cleanup, mobile layout and the
`/live/` path. Set `SPEAKRAIL_TEST_PYTHON` to a different Python environment
containing aiohttp, numpy, scipy and the optional PocketSphinx wheel. A URL
argument uses an already-running stub server instead.

The rig check verifies vertex deformation, shared skinning for the wire
overlay, matching mouth weights on teeth and tongue, immediate reset, reduced
motion, portrait texture loading, appearance switching/persistence, blink
pixels, desktop/mobile/landscape framing, subtitle clearance and fallback
after WebGL context loss. These checks do not establish
natural-looking speech. Safari and physical-microphone behaviour still need a
separate review. The preview uses the generated Astra greeting; its licence is
separate from the CC0 avatar.

With the Astra trial running, `node mac/test_astra_live.cjs` checks its identity,
three spoken turns, name recall, live phoneme animation and Stop cleanup using
synthetic microphone audio. It writes only synthetic test artifacts under
`mac/test-tmp`. `tests/test_astra.py` checks the persona and capability prompt
without loading models.

Motion unit tests cover bounded movement, eased entry/exit, frame-rate
independence, resuming after a background pause and reduced-motion reset.
Browser checks also compare idle pixels with blinking disabled, verify the
listening state and skull-attached hair, and check that listening does not
activate speech shapes. Geometry checks require the head to move independently
of the bust, allowing only subpixel collar deformation from the stock skin
weights. Pixel changes alone do not establish natural motion.

To refresh the vendored runtime after installing the pinned dev dependencies,
run `npm run vendor:avatar` from `mac`. Sources, hashes and licences are in
`app/web/live/assets/mesh-face/README.md` and `mac/THIRD_PARTY.md`.
