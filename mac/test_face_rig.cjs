const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const fs = require('node:fs');
const path = require('node:path');
const net = require('node:net');

(async () => {
  const probe = net.createServer();
  probe.listen(0, '127.0.0.1');
  await once(probe, 'listening');
  const port = probe.address().port;
  await new Promise(resolve => probe.close(resolve));
  const server = spawn(path.join(__dirname, '.venv/bin/python'),
    [path.join(__dirname, 'mac_ui.py'), '--preview-only', '--port', String(port)], { stdio: 'ignore' });
  const closed = once(server, 'close');
  const url = `http://127.0.0.1:${port}/`;
  const report = { errors: [], failedRequests: [], views: [] };
  let browser;
  try {
    for (let i = 0; i < 100; i++) {
      try { if ((await fetch(url)).ok) break; } catch {}
      if (i === 99) throw new Error('Preview server did not start');
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    browser = await chromium.launch();
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce' });
    page.on('pageerror', e => report.errors.push(e.message));
    page.on('requestfailed', r => report.failedRequests.push(r.url()));
    await page.route('https://fonts.googleapis.com/**', r => r.fulfill({ body: '', contentType: 'text/css' }));
    await page.goto(url);
    await page.waitForFunction(() => avatar.ready, null, { timeout: 60000 });
    report.geometry = await page.evaluate(() => {
      const a = avatar, v = new a.THREE.Vector3();
      const mesh = a.targets.find(m => m.name === 'Human');
      const targetCanvas = document.createElement('canvas');
      targetCanvas.width = 600; targetCanvas.height = 700;
      const c = targetCanvas.getContext('2d');
      const draw = pose => a.draw(c, 0, 600, 700, { previewPose: pose });
      draw(0);
      const rest = [];
      for (let i = 0; i < mesh.geometry.attributes.position.count; i++) {
        mesh.getVertexPosition(i, v); rest.push(v.clone());
      }
      const displacement = () => {
        let max = 0;
        for (let i = 0; i < rest.length; i++) {
          mesh.getVertexPosition(i, v); max = Math.max(max, v.distanceTo(rest[i]));
        }
        return max;
      };
      draw(10);
      const mouth = displacement();
      const teeth = a.targets.find(m => m.name.includes('teeth'));
      const tongue = a.targets.find(m => m.name.includes('tongue'));
      const wire = a.model.getObjectByName('Human_wire');
      const speechWeights = [mesh, teeth, tongue].map(m => m.morphTargetInfluences[m.morphTargetDictionary.viseme_aa]);
      const sharedWire = wire.morphTargetInfluences === mesh.morphTargetInfluences && wire.skeleton === mesh.skeleton;
      draw(15);
      const blink = displacement();
      a.resetMouth();
      const cleared = a.targets.every(m => m.morphTargetInfluences.every(x => x === 0));
      draw(0);
      const head = a.head.quaternion.clone();
      a.draw(c, 20000, 600, 700);
      return { mouth, blink, speechWeights, sharedWire, cleared, reducedMotionStable: head.equals(a.head.quaternion) };
    });
    assert(report.geometry.mouth > .005, 'Mouth vertices move, not just a pose label');
    assert(report.geometry.blink > .001, 'Eyelids deform');
    assert.deepEqual(report.geometry.speechWeights, [.65, .65, .65]);
    assert(report.geometry.sharedWire && report.geometry.cleared && report.geometry.reducedMotionStable);
    for (const [width, height] of [[1440, 900], [390, 844], [844, 390]]) {
      await page.setViewportSize({ width, height });
      await page.waitForTimeout(300);
      const view = await page.evaluate(() => {
        const canvas = document.querySelector('#blob'), c = canvas.getContext('2d');
        const { data } = c.getImageData(0, 0, canvas.width, canvas.height);
        let count = 0, minY = Infinity, maxY = 0, minX = Infinity, maxX = 0;
        for (let y = 0; y < canvas.height; y++) for (let x = 0; x < canvas.width; x++) {
          const i = (y * canvas.width + x) * 4;
          if (data[i + 1] > 45 && data[i + 1] > data[i] * 1.2) {
            count++; minY = Math.min(y, minY); maxY = Math.max(y, maxY); minX = Math.min(x, minX); maxX = Math.max(x, maxX);
          }
        }
        const rect = canvas.getBoundingClientRect(), button = document.querySelector('#go').getBoundingClientRect();
        const scale = canvas.width / rect.width;
        return { count, minY: minY / scale, maxY: maxY / scale, minX: minX / scale, maxX: maxX / scale,
          width: rect.width, faceBottom: rect.top + maxY / scale, buttonTop: button.top };
      });
      assert(view.count > 1000, 'Nonblank green face');
      assert(view.minY > 25 && view.minX > 8 && view.maxX < width - 8, 'Hair/head has top and side clearance');
      assert(view.faceBottom + 5 < view.buttonTop, 'Face does not overlap primary control');
      report.views.push({ width, height, ...view });
      await page.screenshot({ path: path.join(__dirname, `rig-${width}.png`) });
      await page.locator('#go').click();
      await page.waitForFunction(() => speechPreview?.start != null);
      await page.waitForTimeout(800);
      const layout = await page.evaluate(() => {
        const button = document.querySelector('#go').getBoundingClientRect();
        const subtitles = document.querySelector('.subs').getBoundingClientRect();
        return { buttonBottom: button.bottom, subtitleTop: subtitles.top };
      });
      assert(layout.buttonBottom + 4 < layout.subtitleTop, 'Speech captions and controls do not overlap');
      await page.screenshot({ path: path.join(__dirname, `rig-speaking-${width}.png`) });
      await page.locator('#go').click();
    }
    await page.setViewportSize({ width: 900, height: 900 });
    await page.locator('#gear').click();
    await page.locator('#avatar-pose').selectOption('10');
    await page.waitForTimeout(200);
    await page.locator('#gear').click();
    await page.screenshot({ path: path.join(__dirname, 'rig-mouth-aa.png') });
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    report.motion = await page.evaluate(async () => {
      previewPose = null;
      await new Promise(r => requestAnimationFrame(r));
      const canvas = document.querySelector('#blob');
      const before = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
      await new Promise(r => setTimeout(r, 700));
      const after = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
      let changed = 0;
      for (let i = 0; i < before.length; i += 4) if (Math.abs(before[i + 1] - after[i + 1]) > 8) changed++;
      return { changedPixels: changed };
    });
    assert(report.motion.changedPixels > 100, 'Idle motion changes rendered pixels');
    await page.evaluate(() => avatar.renderer.forceContextLoss());
    await page.waitForFunction(() => document.body.dataset.visualizer === 'blob');
    await page.evaluate(() => { document.querySelector('#visualizer').value = 'mesh'; applyVisualizer(); });
    await page.waitForFunction(() => avatar.ready, null, { timeout: 60000 });
    assert(await page.evaluate(() => !avatar.renderer.getContext().isContextLost()), 'Selection recovers with a new WebGL context');
    assert.deepEqual(report.errors, []);
    assert.deepEqual(report.failedRequests, []);
    await page.route('**/mpfb.glb', r => r.fulfill({ status: 503, body: 'Asset unavailable' }));
    await page.reload();
    await page.waitForFunction(() => document.body.dataset.visualizer === 'blob');
    assert(await page.locator('#avatar-notice').isVisible(), 'Load failure explains fallback');
    assert.deepEqual(report.errors, []);
    console.log(JSON.stringify(report, null, 2));
    console.log('PASS: geometry, teeth/tongue, wire skinning, reset, reduced motion, framing, speech controls, pixel motion, WebGL loss fallback');
  } finally {
    fs.writeFileSync(path.join(__dirname, 'face-rig-results.json'), JSON.stringify(report, null, 2));
    if (browser) await browser.close();
    server.kill('SIGTERM');
    await closed;
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
