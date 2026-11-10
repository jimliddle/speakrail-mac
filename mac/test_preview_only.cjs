const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const net = require('node:net');
const path = require('node:path');

(async () => {
  const portProbe = net.createServer();
  portProbe.listen(0, '127.0.0.1');
  await once(portProbe, 'listening');
  const port = portProbe.address().port;
  await new Promise(resolve => portProbe.close(resolve));
  const server = spawn(path.join(__dirname, '.venv/bin/python'),
    [path.join(__dirname, 'mac_ui.py'), '--preview-only', '--conversation-url', 'http://127.0.0.1:18183/?visualizer=mesh', '--port', String(port)], { stdio: 'ignore' });
  const closed = once(server, 'close');
  const url = `http://127.0.0.1:${port}/`;
  let browser;
  try {
    let ready = false;
    for (let i = 0; i < 100; i++) {
      try { ready = (await fetch(url)).ok; } catch {}
      if (ready) break;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert(ready, 'Preview server started');
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    const errors = [];
    let sockets = 0;
    page.on('pageerror', error => errors.push(error.message));
    page.on('websocket', () => sockets++);
    await page.route('https://fonts.googleapis.com/**', route => route.fulfill({ body: '', contentType: 'text/css' }));
    await page.addInitScript(() => {
      window.micRequests = 0;
      navigator.mediaDevices.getUserMedia = () => {
        window.micRequests++;
        throw new Error('Preview must not request a microphone');
      };
    });
    for (const route of ['', 'live/']) {
      await page.goto(url + route);
      assert.equal(await page.locator('#go').textContent(), 'Preview speech');
      assert(await page.locator('#conversation-link').isVisible());
      assert.equal(await page.locator('#conversation-link').getAttribute('href'), 'http://127.0.0.1:18183/?visualizer=mesh');
      const controller = { headers: { 'X-Speakrail-Client': 'local-controller' } };
      const original = await (await page.request.get(url + route + 'avatar-preview?pace=1', controller)).json();
      const relaxed = await (await page.request.get(url + route + 'avatar-preview?pace=0.85', controller)).json();
      assert(relaxed.duration > original.duration * 1.1, 'Relaxed pace actually slows the PCM');
      assert.equal(relaxed.method, 'forced-phoneme');
      assert(Math.abs(Buffer.from(relaxed.pcm, 'base64').length / 48000 - relaxed.duration) < .001);
      assert(relaxed.cues.some(c => c.pose === 0 && c.start > .3 && c.end - c.start > .2), 'Greeting has a closed-mouth pause between phrases');
      assert.equal((await page.request.get(url + route + 'avatar-preview?pace=0', controller)).status(), 400);
      await page.locator('#go').click();
      await page.waitForFunction(() => speechPreview?.start != null);
      assert(await page.evaluate(() => speechPreview.end - speechPreview.start > 3));
      assert.equal(await page.locator('#bot').textContent(), "Hi, I'm Astra. How is your day going today?");
      assert.equal(await page.locator('#go').textContent(), 'Stop preview');
      assert(await page.evaluate(() => !running && !stream && micRequests === 0));
      assert.equal((await page.request.get(url + route + 'ws', controller)).status(), 409);
      await page.locator('#gear').click();
      assert(await page.locator('#avatar-preview').isEnabled());
      await page.locator('#avatar-preview').click();
      await page.waitForFunction(() => speechPreview === null);
      assert.equal(await page.locator('#go').textContent(), 'Preview speech');
      await page.locator('#avatar-preview').click();
      await page.waitForFunction(() => speechPreview?.start != null);
      await page.waitForFunction(() => speechPreview === null, null, { timeout: 15000 });
      assert.equal(await page.locator('#go').textContent(), 'Preview speech');
      assert.equal(await page.locator('#avatar-preview').textContent(), 'Preview speech');
    }
    await page.locator('#gear').click();
    for (const [width, height] of [[1440, 900], [390, 844]]) {
      await page.setViewportSize({ width, height });
      await page.waitForTimeout(200);
      assert(await page.locator('#conversation-link').evaluate(link => {
        const r = link.getBoundingClientRect(); return r.x >= 0 && r.right <= innerWidth && r.bottom <= innerHeight;
      }));
      await page.screenshot({ path: path.join(__dirname, `preview-only-${width}.png`) });
    }
    assert.equal(sockets, 0);
    assert.deepEqual(errors, []);
    console.log('PASS: primary preview, settings toggle, natural end, no microphone/WebSocket, root and /live/');
  } finally {
    if (browser) await browser.close();
    server.kill('SIGTERM');
    await closed;
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
