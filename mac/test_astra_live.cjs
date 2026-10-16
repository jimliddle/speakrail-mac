// Requires the isolated Astra launcher. Never captures the physical microphone.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const url = process.argv[2] || 'http://127.0.0.1:18183/?visualizer=mesh';
  const root = path.join(__dirname, 'test-tmp');
  fs.mkdirSync(root, { recursive: true });
  const cases = [
    { question: 'What is your name?', expected: /Astra/i },
    { question: 'My name is Jamie. Please remember it.', expected: /Jamie/i },
    { question: 'What is my name?', expected: /Jamie/i },
  ];
  for (const [index, item] of cases.entries()) {
    const file = path.join(root, `astra-question-${index}.aiff`);
    execFileSync('say', ['-v', 'Samantha', '-o', file, item.question]);
    item.audio = execFileSync('ffmpeg', ['-v', 'error', '-i', file, '-ar', '16000', '-ac', '1', '-f', 's16le', 'pipe:1']).toString('base64');
  }
  const browser = await chromium.launch({ args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'] });
  const report = { errors: [], turns: [], syntheticMicrophone: true };
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, permissions: ['microphone'] });
    page.on('pageerror', error => report.errors.push(error.message));
    if (process.env.ASTRA_TEST_VERBOSE) page.on('websocket', socket => socket.on('framereceived', frame => {
      if (typeof frame.payload !== 'string') return;
      const event = JSON.parse(frame.payload);
      if (['word', 'error', 'reply_start', 'reply_end', 'stop_audio', 'decision'].includes(event.type)) console.log(JSON.stringify(event));
    }));
    await page.route('https://fonts.googleapis.com/**', r => r.fulfill({ body: '', contentType: 'text/css' }));
    await page.goto(url);
    await page.waitForFunction(() => avatar.ready);
    await page.evaluate(() => {
      window.astraEvents = [];
      const handle = onMessage;
      onMessage = event => {
        if (typeof event.data === 'string') window.astraEvents.push(JSON.parse(event.data));
        handle(event);
      };
    });
    await page.locator('#go').click();
    await page.waitForFunction(() => running && worklet != null);
    await page.evaluate(() => { worklet.port.onmessage = null; });
    await page.waitForFunction(() => window.astraEvents.some(e => e.type === 'brain'), null, { timeout: 60000 });
    const system = await page.evaluate(() => window.astraEvents.find(e => e.type === 'brain').system);
    assert(system.startsWith('You are Astra,'));
    assert(!system.includes('Nova') && system.includes('Web search is unavailable'));
    assert(await page.evaluate(() => window.astraEvents.some(e => e.type === 'lip_sync_status' && e.available)));
    for (const [index, item] of cases.entries()) {
      const offset = await page.evaluate(() => window.astraEvents.length);
      // Send the fixture at microphone cadence, then silence until actual playback ends.
      await page.evaluate(({ audio }) => {
        const bytes = Uint8Array.from(atob(audio), c => c.charCodeAt(0));
        let position = 0;
        window.astraMouthMoved = false;
        window.astraFeed = setInterval(() => {
          if (!ws || ws.readyState !== WebSocket.OPEN) return;
          const chunk = new Uint8Array(2560);
          chunk.set(bytes.subarray(position, position + 2560));
          position += 2560;
          ws.send(chunk);
          if (botSpeaking && avatar.targets.some(m => Object.entries(m.morphTargetDictionary).some(
            ([name, i]) => name.startsWith('viseme_') && m.morphTargetInfluences[i] > .05))) window.astraMouthMoved = true;
        }, 80);
      }, { audio: item.audio, offset });
      try {
        await page.waitForFunction(offset => window.astraEvents.slice(offset).some(e => e.type === 'reply_end'), offset, { timeout: 90000 });
        // reply_end means generation finished, not that the speaker has finished.
        await page.waitForFunction(() => !botSpeaking && !replyPending && outputTime(playCtx) >= playCursor,
          null, { timeout: 30000 });
        await page.waitForTimeout(300);
      } catch (error) {
        report.incompleteTurn = await page.evaluate(offset => window.astraEvents.slice(offset), offset);
        throw error;
      } finally {
        await page.evaluate(() => clearInterval(window.astraFeed));
      }
      const events = await page.evaluate(offset => window.astraEvents.slice(offset), offset);
      const reply = events.filter(e => e.type === 'reply_delta').map(e => e.text).join('');
      const cues = events.filter(e => e.type === 'lip_sync').reduce((sum, e) => sum + e.cues.length, 0);
      const mouthMoved = await page.evaluate(() => window.astraMouthMoved);
      report.turns.push({ question: item.question, reply, cues, mouthMoved });
      console.log(JSON.stringify(report.turns.at(-1)));
      assert.match(reply, item.expected);
      assert(cues > 0 && mouthMoved, 'Real spoken reply has aligned and visible mouth movement');
      assert(!events.some(e => e.type === 'error'), JSON.stringify(events.filter(e => e.type === 'error')));
      await page.screenshot({ path: path.join(root, `astra-turn-${index}.png`) });
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(300);
    assert(await page.locator('#controls button').evaluateAll(buttons => buttons.every(b => {
      const r = b.getBoundingClientRect(); return r.x >= 0 && r.right <= innerWidth;
    })));
    await page.screenshot({ path: path.join(root, 'astra-mobile-live.png') });
    await page.locator('#stop').click();
    assert(await page.evaluate(() => !running && ws === null && stream.getTracks().every(t => t.readyState === 'ended')));
    report.stopReleasesMicrophone = true;
    assert.deepEqual(report.errors, []);
  } finally {
    await browser.close();
    fs.writeFileSync(path.join(root, 'astra-live-results.json'), JSON.stringify(report, null, 2));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
