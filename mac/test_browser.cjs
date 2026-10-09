const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');

(async () => {
  const root = __dirname;
  const url = process.argv[2] || 'http://127.0.0.1:18180/';
  // Synthetic input only; this test never captures the real microphone.
  const question = path.join(root, 'browser-question.aiff');
  const fixture = path.join(root, 'browser-input.wav');
  execFileSync('say', ['-v', 'Samantha', '-o', question, 'What is the capital of France?']);
  execFileSync('ffmpeg', ['-y', '-v', 'error', '-i', question, '-af',
    'adelay=3000|3000,apad=pad_dur=45', '-ar', '48000', '-ac', '1', fixture]);
  const browser = await chromium.launch({ headless: true, args: [
    '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream',
    `--use-file-for-fake-audio-capture=${path.join(root, 'browser-input.wav')}`,
  ] });
  const report = { errors: [], views: [] };
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, permissions: ['microphone'] });
    // Keep this test offline, including optional upstream Google Fonts.
    await context.route('https://fonts.googleapis.com/**', r => r.fulfill({ body: '', contentType: 'text/css' }));
    const page = await context.newPage();
    page.on('pageerror', e => report.errors.push(e.message));
    await page.goto(url);
    await page.locator('#go').click();
    await page.waitForFunction(() => document.querySelector('#bot').textContent.includes('Paris'), null, { timeout: 60000 });
    report.reply = await page.locator('#bot').textContent();
    await page.waitForFunction(() => playCtx && playCtx.state === 'running' && lvl.botTarget > 0.005,
      null, { timeout: 30000 });
    report.browser_audio_playing = true;
    await page.screenshot({ path: path.join(root, 'browser-desktop.png') });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(400);
    const controlsFit = await page.locator('#controls button').evaluateAll(buttons => buttons.every(b => {
      const r = b.getBoundingClientRect();
      return r.x >= 0 && r.right <= innerWidth && r.y >= 0;
    }));
    assert(controlsFit, 'Active mobile controls must stay inside the viewport');
    await page.screenshot({ path: path.join(root, 'browser-mobile-active.png') });
    await page.locator('#stop').click();
    await page.locator('#go').waitFor({ state: 'visible' });
    await page.waitForTimeout(500);
    assert.equal(await page.locator('#state').textContent(), 'idle');
    assert(await page.evaluate(() => playCtx.state === 'closed' && micCtx.state === 'closed'
      && stream.getTracks().every(track => track.readyState === 'ended') && ws === null));
    report.stop_releases_audio = true;
    for (const [width, height] of [[1440, 900], [390, 844]]) {
      await page.setViewportSize({ width, height });
      await page.waitForTimeout(400);
      const first = await page.locator('#blob').evaluate(canvas => {
        const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
        let opaque = 0, sum = 0;
        for (let i = 3; i < data.length; i += 4) { opaque += data[i] > 0; sum += data[i]; }
        return { opaque, sum };
      });
      await page.waitForTimeout(500);
      const layout = await page.evaluate(() => {
        const canvas = document.querySelector('#blob');
        const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
        let sum = 0;
        for (let i = 3; i < data.length; i += 4) sum += data[i];
        return { overflow: document.documentElement.scrollWidth > innerWidth, sum };
      });
      assert(first.opaque > 100 && first.sum !== layout.sum, 'Canvas must be visible and animated');
      assert(!layout.overflow, 'Horizontal page overflow');
      await page.locator('#gear').click();
      assert(await page.locator('#panel').isVisible());
      assert(await page.locator('#search').isDisabled());
      await page.waitForTimeout(250);
      await page.screenshot({ path: path.join(root, `browser-${width}.png`) });
      await page.locator('#gear').click();
      report.views.push({ width, height, canvas_animated: true, no_horizontal_overflow: true });
    }
    assert.deepEqual(report.errors, []);
    report.synthetic_microphone = true;
  } finally {
    await browser.close();
    fs.writeFileSync(path.join(root, 'browser-results.json'), JSON.stringify(report, null, 2) + '\n');
  }
  console.log(JSON.stringify(report, null, 2));
})().catch(e => { console.error(e); process.exitCode = 1; });
