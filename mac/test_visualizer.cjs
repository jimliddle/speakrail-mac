/* Model-free browser checks. Start app/server.py --stub, or let this test start
 * it with SPEAKRAIL_TEST_PYTHON (defaults to mac/.venv/bin/python).
 * Uses a fake microphone and scripted PCM/cues, never a physical microphone.
 */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const net = require('node:net');
const path = require('node:path');

async function freePort() {
  const server = net.createServer();
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  await new Promise(resolve => server.close(resolve));
  return port;
}
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

(async () => {
  let service;
  let url = process.argv[2];
  if (!url) {
    const port = await freePort();
    url = `http://127.0.0.1:${port}/`;
    service = spawn(process.env.SPEAKRAIL_TEST_PYTHON || path.join(__dirname, '.venv/bin/python'),
      [path.join(__dirname, '../app/server.py'), '--stub', '--port', String(port)], { stdio: ['ignore', 'ignore', 'pipe'] });
    service.stderr.on('data', data => process.stderr.write(data));
    service.on('error', error => { console.error(error); process.exitCode = 1; });
  }
  let browser;
  const report = { errors: [], checked: [] };
  try {
    for (let i = 0; i < 100; i++) {
      try { if ((await fetch(url)).ok) break; } catch {}
      if (service?.exitCode != null) throw new Error('Preview server exited');
      if (i === 99) throw new Error('Preview server did not start');
      await delay(100);
    }
    browser = await chromium.launch({ headless: true,
      ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}),
      args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', '--autoplay-policy=no-user-gesture-required',
        ...JSON.parse(process.env.CHROMIUM_TEST_ARGS || '[]')],
    });
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, permissions: ['microphone'] });
    await context.route('https://fonts.googleapis.com/**', route => route.fulfill({ body: '', contentType: 'text/css' }));
    const page = await context.newPage();
    page.on('pageerror', error => report.errors.push(error.message));
    let socket, socketCount = 0, socketURL;
    const playbackAcks = [];
    await page.routeWebSocket(/\/ws(?:\?|$)/, route => {
      socket = route; socketURL = route.url(); socketCount++;
      route.onMessage(message => {
        if (typeof message !== 'string') return;
        const command = JSON.parse(message);
        if (command.cmd === 'play_segment') playbackAcks.push(command);
        if (command.cmd === 'interrupt') route.send(JSON.stringify({ type: 'stop_audio', reason: 'test interrupt' }));
      });
      route.send(JSON.stringify({ type: 'ready' }));
      route.send(JSON.stringify({ type: 'lip_sync_status', available: true }));
    });
    const send = event => socket.send(JSON.stringify(event));
    function speech(utt, method = 'forced-phoneme') {
      const samples = 24000, packet = Buffer.alloc(4 + samples * 2);
      packet.writeUInt16LE(utt, 0);
      // Constant volume throughout: different mouth poses must come from cues.
      for (let i = 0; i < samples; i++) packet.writeInt16LE(Math.round(8000 * Math.sin(i * Math.PI * 2 * 180 / 24000)), 4 + i * 2);
      send({ type: 'lip_sync', utt, segment: 0, samples, sample_rate: 24000, method, cues: [
        { start: 0, end: 0.22, pose: 1 }, { start: 0.22, end: 0.75, pose: 10 }, { start: 0.75, end: 1, pose: 0 },
      ] });
      socket.send(packet);
    }
    await page.goto(url);
    assert.equal(await page.locator('#visualizer').inputValue(), 'mesh');
    await page.locator('#gear').click();
    await page.locator('#visualizer').selectOption('mesh');
    await page.waitForFunction(() => avatar.ready);
    for (let pose = 0; pose < 24; pose++) {
      await page.locator('#avatar-pose').selectOption(String(pose));
      await page.waitForFunction(pose => avatar.pose === pose, pose);
    }
    await page.locator('#avatar-pose').selectOption('auto');
    await page.locator('#avatar-preview').click();
    await page.waitForFunction(() => speechPreview?.start != null, null, { timeout: 30000 });
    assert(await page.evaluate(() => !running && !stream && speechPreview.context.state === 'running'));
    await page.locator('#avatar-preview').click();
    assert(await page.evaluate(() => speechPreview === null));
    report.checked.push('24 poses; real aligned speech preview without microphone or WebSocket');
    await page.locator('#gear').click();

    await page.locator('#go').click();
    await page.waitForFunction(() => running);
    assert(new URL(socketURL).searchParams.get('lipsync') === 'phoneme');
    send({ type: 'lip_sync', utt: 99, segment: 0, method: 'unavailable', cues: [] });
    await page.waitForFunction(() => !$('avatar-notice').hidden);
    assert.match(await page.locator('#avatar-notice').textContent(), /could not be aligned/);
    send({ type: 'reply_start' }); send({ type: 'reply_delta', text: 'This is synchronized speech.' });
    await page.waitForFunction(() => uiState === 'thinking');
    speech(1); send({ type: 'reply_end' });
    await page.waitForFunction(() => uiState === 'speaking' && avatar.pose === 1);
    assert(await page.locator('#avatar-notice').isHidden());
    await page.waitForFunction(() => avatar.pose === 10);
    assert(playbackAcks.some(ack => ack.utt === 1 && ack.segment === 0 && ack.remaining_ms > 0));
    // reply_end has already arrived, but audible playback still drives the face.
    assert.equal(await page.locator('#state').textContent(), 'speaking');
    await page.locator('#interrupt').click();
    await page.waitForFunction(() => uiState === 'listening' && avatar.pose === 16);
    assert(await page.evaluate(() => lipTimeline.tracks.length === 0 && audioWindows.length === 0));
    report.checked.push('phoneme-specific constant-volume poses; playback tail; interruption cleanup');

    speech(2, 'acoustic-phoneme'); send({ type: 'reply_end' });
    await page.waitForFunction(() => uiState === 'speaking');
    assert(await page.locator('#avatar-notice').isHidden(), 'Successful audio-only timing is not a user warning');
    report.checked.push('alignment failures visible; successful forced and acoustic timing silent');
    await page.locator('#gear').click();
    assert(await page.locator('#visualizer').isEnabled());
    await page.locator('#visualizer').selectOption('blob');
    assert(await page.evaluate(() => playCtx.state === 'running' && running));
    await page.locator('#visualizer').selectOption('mesh');
    await page.locator('#gear').click();
    await page.waitForFunction(() => uiState === 'listening');
    assert.equal(socketCount, 1);
    await page.locator('#stop').click();
    await page.waitForFunction(() => playCtx.state === 'closed' && micCtx.state === 'closed');
    assert(await page.evaluate(() => playCtx.state === 'closed' && micCtx.state === 'closed'
      && stream.getTracks().every(track => track.readyState === 'ended') && ws === null));
    report.checked.push('live switching preserves session; Stop releases audio devices');

    await page.reload();
    assert.equal(await page.locator('#visualizer').inputValue(), 'mesh');
    await page.waitForFunction(() => avatar.ready);
    for (const [width, height] of [[1440, 900], [390, 844], [844, 390]]) {
      await page.setViewportSize({ width, height });
      await page.waitForTimeout(220);
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      const pixels = await page.locator('#blob').evaluate(canvas => {
        const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
        let green = 0;
        for (let i = 0; i < data.length; i += 4) if (data[i + 1] > data[i] * 1.5 && data[i + 1] > 40) green++;
        return green;
      });
      assert(pixels > 1000, 'Portrait must actually be drawn');
      await page.screenshot({ path: path.join(__dirname, `mesh-preview-${width}.png`) });
      for (const [count, requested] of [[3, 3], [2, 3], [2, 2]]) {
        const groups = ['UK', 'US'].map((region, i) => ({region, requested_count: requested,
          results: Array.from({length: count}, (_, j) => ({brief_id: `${i}:${j}`, region,
            title: `Synthetic ${region} item ${j + 1}: a longer headline about a local transport project`,
            source: 'example.org', url: `https://example.org/${region}/${j}`}))}));
        await page.evaluate(groups => {
          cardSearch({turn: 99, query: 'UK and US news'});
          cardDone({turn: 99, n: groups.flatMap(g => g.results).length, ms: 100,
            groups, results: groups.flatMap(g => g.results)});
        }, groups);
        assert.equal(await page.locator('.news-card').count(), 1);
        assert.deepEqual(await page.locator('.news-results h3').allTextContents(),
          [`UK: ${count} of ${requested}`, `US: ${count} of ${requested}`]);
        assert.deepEqual(await page.locator('.news-results [data-brief-id]').evaluateAll(nodes => nodes.map(n => n.dataset.briefId)),
          groups.flatMap(g => g.results.map(r => r.brief_id)));
        const bounds = await page.locator('.news-card').boundingBox();
        const button = await page.locator('#go').boundingBox();
        assert(bounds.x >= 0 && bounds.y >= 0 && bounds.x + bounds.width <= width + 1 && bounds.y + bounds.height <= height + 1);
        assert(bounds.x + bounds.width <= button.x || bounds.x >= button.x + button.width ||
          bounds.y + bounds.height <= button.y || bounds.y >= button.y + button.height, 'News card must not cover Start');
        await page.locator('.news-results').evaluate(node => node.scrollTop = node.scrollHeight);
        assert(await page.locator('.news-results').evaluate(node => node.scrollHeight - node.clientHeight - node.scrollTop < 2));
        await page.locator('.news-results').evaluate(node => node.scrollTop = 0);
        await page.screenshot({path: path.join(__dirname, `news-card-${width}-${count}-of-${requested}.png`)});
      }
    }
    report.checked.push('regional cards: complete/partial counts, same-turn replacement, scroll access and Start-button clearance');
    await page.goto(url + '?visualizer=blob');
    assert.equal(await page.locator('#visualizer').inputValue(), 'mesh', 'Saved choice wins over URL');
    await page.locator('#gear').click();
    await page.locator('#visualizer').selectOption('blob');
    await page.reload();
    assert.equal(await page.locator('#visualizer').inputValue(), 'blob', 'Orb persists across reload');
    await page.goto(url + 'live/?visualizer=mesh');
    assert.equal(await page.locator('#visualizer').inputValue(), 'blob', 'Astra link respects saved orb');
    await page.locator('#gear').click();
    await page.locator('#visualizer').selectOption('mesh');
    await page.goto(url);
    assert.equal(await page.locator('#visualizer').inputValue(), 'mesh');
    await page.goto(url + 'live/?visualizer=mesh');
    await page.waitForFunction(() => avatar.ready);
    assert.equal((await page.request.get(url + 'live/avatar-preview')).status(), 200);
    await page.evaluate(() => localStorage.setItem('speakrail.visualizer', 'invalid'));
    await page.goto(url);
    assert.equal(await page.locator('#visualizer').inputValue(), 'mesh', 'Invalid preference falls back to Astra');
    await page.addInitScript(() => {
      Storage.prototype.getItem = () => { throw Error('Storage disabled'); };
      Storage.prototype.setItem = () => { throw Error('Storage disabled'); };
    });
    await page.reload();
    await page.waitForFunction(() => avatar.ready);
    assert.equal(await page.locator('#visualizer').inputValue(), 'mesh');
    await page.locator('#gear').click();
    await page.locator('#visualizer').selectOption('blob');
    assert.equal(await page.locator('#visualizer').inputValue(), 'blob', 'Switch works without storage');
    report.checked.push('Astra default; both choices persist; saved choice wins over URL; invalid/blocked storage; desktop/mobile canvas; /live/ route');
    assert.deepEqual(report.errors, []);
  } finally {
    if (browser) await browser.close();
    if (service) service.kill('SIGTERM');
    fs.writeFileSync(path.join(__dirname, 'visualizer-results.json'), JSON.stringify(report, null, 2) + '\n');
  }
  console.log(JSON.stringify(report, null, 2));
})().catch(error => { console.error(error); process.exitCode = 1; });
