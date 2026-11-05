// Local static fixture: real avatar assets and event handlers, no model or microphone.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');

const root = path.resolve(__dirname, '../app/web/live');
const output = path.join(__dirname, 'activity-ui-results');
const report = {views: [], errors: []};
const server = http.createServer((req, res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname;
  if (pathname === '/') {
    const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
    res.setHeader('Content-Type', 'text/html');
    res.end(html);
    return;
  }
  const file = path.resolve(root, '.' + pathname.replace(/^\/static/, ''));
  if (!pathname.startsWith('/static/') || !file.startsWith(root + path.sep) || !fs.existsSync(file)) {
    res.writeHead(404); res.end(); return;
  }
  res.setHeader('Content-Type', ({'.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png', '.json': 'application/json'})[path.extname(file)] || 'application/octet-stream');
  fs.createReadStream(file).pipe(res);
});
const overlaps = (a, b) => a.x < b.x + b.width - 1 && a.x + a.width > b.x + 1 && a.y < b.y + b.height - 1 && a.y + a.height > b.y + 1;

(async () => {
  fs.mkdirSync(output, {recursive: true});
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({headless: true});
  try {
    const page = await browser.newPage();
    page.on('pageerror', error => report.errors.push(error.message));
    await page.route('**/*', route => {
      if (new URL(route.request().url()).hostname !== '127.0.0.1') return route.abort();
      return route.continue();
    });
    await page.goto(`http://127.0.0.1:${server.address().port}/`);
    await page.waitForFunction(() => avatar.ready);
    for (const [width, height] of [[1440, 900], [390, 844], [844, 390]]) {
      await page.setViewportSize({width, height});
      await page.evaluate(() => {
        onMessage({data: JSON.stringify({type: 'reset'})});
        showBot('The result needs budget approval. The full comparison and source references are available in details.', false);
        cardTool({name: 'claude_code', result: {task_id: 'fixture'}, ms: 3});
      });
      assert.match(await page.locator('.activity-label').textContent(), /Working/);
      await page.evaluate(() => cardTool({name: 'claude_code', result: {
        task_id: 'fixture', answer: ('Synthetic comparison\n\nBudget: needs approval.\nPrivacy: meets the requirement.\nSource: proposal.pdf, page 2.\n\n').repeat(60)
      }, ms: 250}));
      assert.equal(await page.locator('.activity-row').count(), 1);
      assert.equal(await page.locator('#result-panel').isVisible(), false);
      assert.equal(await page.locator('.tool').isVisible(), false);
      await page.waitForTimeout(300);
      const full = await page.locator('#blob').boundingBox();
      const captions = await page.locator('.subs').boundingBox();
      assert(!overlaps(full, captions), 'Captions must have their own space');
      await page.screenshot({path: path.join(output, `collapsed-${width}.png`), fullPage: true});
      await page.locator('.activity-row button').click();
      await page.waitForTimeout(400);
      const avatarBox = await page.locator('#blob').boundingBox();
      const detailBox = await page.locator('#result-panel').boundingBox();
      assert(!overlaps(avatarBox, detailBox), 'Details must not cover Astra');
      assert(!overlaps(await page.locator('.subs').boundingBox(), detailBox));
      if (width > 700) assert(avatarBox.width < full.width, 'Desktop avatar area must resize');
      else assert(detailBox.y >= avatarBox.y + avatarBox.height, 'Mobile details must sit below');
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      const pixels = await page.evaluate(() => {
        const {data, width, height} = ctx.getImageData(0, 0, canvas.width, canvas.height);
        let lit = 0, top = height, bottom = 0;
        for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
          const i = (y * width + x) * 4;
          if (data[i + 1] > 35 && data[i + 1] > data[i] * 1.2) { lit++; top = Math.min(top, y); bottom = Math.max(bottom, y); }
        }
        return {lit, top, bottom, height, width, expectedWidth: Math.round(canvas.clientWidth * Math.min(2, devicePixelRatio))};
      });
      assert(pixels.lit > 1000, 'Portrait must render');
      assert(pixels.top > 5 && pixels.bottom < pixels.height - 5, 'Portrait must not clip');
      assert.equal(pixels.width, pixels.expectedWidth, 'Canvas must resize with panel');
      const frame = await page.evaluate(() => canvas.toDataURL());
      await page.waitForTimeout(700);
      assert.notEqual(frame, await page.evaluate(() => canvas.toDataURL()), 'Idle portrait must animate');
      await page.locator('#result-content').evaluate(node => { node.scrollTop = node.scrollHeight; });
      assert(await page.locator('#result-content').evaluate(node => node.scrollTop > 1000));
      await page.locator('#result-content').evaluate(node => { node.scrollTop = 0; });
      await page.screenshot({path: path.join(output, `expanded-${width}.png`), fullPage: true});
      await page.keyboard.press('Escape');
      assert.equal(await page.locator('#result-panel').isVisible(), false);
      assert(await page.locator('.activity-row button').evaluate(node => node === document.activeElement));
      // A new result never reopens details after the user closes them.
      await page.evaluate(() => cardTool({name: 'get_weather', result: {temperature: '14 C', summary: 'Cloudy'}, ms: 20}));
      assert.equal(await page.locator('#result-panel').isVisible(), false);
      await page.evaluate(() => {
        $('go').hidden = true; $('controls').hidden = false;
        setState('listening');
        showBot('A longer spoken response remains in the caption area. '.repeat(30), false);
      });
      await page.waitForTimeout(300);
      const listeningAvatar = await page.locator('#blob').boundingBox();
      assert(!overlaps(listeningAvatar, await page.locator('.subs').boundingBox()));
      assert(await page.locator('.subs').evaluate(node => node.scrollHeight > node.clientHeight && node.scrollTop > 0));
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      await page.screenshot({path: path.join(output, `listening-${width}.png`), fullPage: true});
      await page.evaluate(() => { $('go').hidden = false; $('controls').hidden = true; setState('idle'); });
      report.views.push({width, height, avatarBox, detailBox, pixels});
    }
    await page.setViewportSize({width: 1440, height: 900});
    await page.evaluate(() => {
      const groups = ['UK', 'US'].map(region => ({region, requested_count: 3,
        results: [1, 2, 3].map(n => ({brief_id: `${region}:${n}`, title: `Synthetic ${region} story ${n}`, source: 'example.org', url: `https://example.org/${region}/${n}`}))}));
      cardSearch({turn: 99, query: 'UK and US news'});
      cardDone({turn: 99, n: 6, ms: 40, groups});
    });
    await page.locator('.activity-row button').first().click();
    assert.deepEqual(await page.locator('.news-results h3').allTextContents(), ['UK: 3 of 3', 'US: 3 of 3']);
    assert.equal(await page.locator('.news-results a[href]').count(), 6);
    await page.screenshot({path: path.join(output, 'news-details.png')});
    await page.locator('#close-details').click();
    await page.evaluate(() => cardTool({name: 'claude_code', result: {task_id: 'update'}, ms: 1}));
    await page.locator('.activity-row button').first().click();
    await page.evaluate(() => cardTool({name: 'claude_code', result: {task_id: 'update', error: 'Synthetic task failure'}, ms: 2}));
    assert(await page.locator('#result-panel').isVisible());
    assert.match(await page.locator('.card:not([hidden])').textContent(), /Synthetic task failure/);
    assert.equal(await page.locator('.activity-row button[aria-expanded="true"]').count(), 1);
    await page.evaluate(() => cardTool({name: 'calculator', result: {value: 12}, ms: 1}));
    assert.match(await page.locator('.card:not([hidden])').textContent(), /Synthetic task failure/,
      'Another result must not replace the one being read');
    await page.locator('#close-details').click();
    await page.evaluate(() => cardTool({name: 'record_note', result: {ok: true}, store: {notes: ['Synthetic note']}, ms: 1}));
    await page.getByRole('button', {name: 'View details: Memory', exact: true}).click();
    assert.match(await page.locator('#memcard').textContent(), /Synthetic note/);
    await page.evaluate(() => cardTool({name: 'record_note', result: {ok: true}, store: {notes: ['Updated note']}, ms: 1}));
    assert.equal(await page.locator('#memcard').count(), 1);
    assert.match(await page.locator('#memcard').textContent(), /Updated note/);
    await page.locator('#close-details').click();
    await page.evaluate(() => {
      cardSearch({turn: 100, query: '<img src=x onerror=alert(1)>'});
      cardDone({turn: 100, n: 1, ms: 1, results: [{title: '<script>bad()</script>', url: 'javascript:alert(1)', snippet: 'Result'}]});
    });
    await page.locator('.activity-row button').first().click();
    assert.equal(await page.locator('#result-content img, #result-content script').count(), 0);
    assert.equal(await page.locator('.card:not([hidden]) a[href]').count(), 0);
    await page.evaluate(() => {
      onMessage({data: JSON.stringify({type: 'lip_sync', utt: 1, method: 'unavailable', cues: []})});
    });
    assert(await page.locator('#avatar-notice').isVisible(), 'Real failure must remain visible');
    await page.evaluate(() => {
      onMessage({data: JSON.stringify({type: 'lip_sync', utt: 1, method: 'acoustic-phoneme', fallback_reason: 'forced-alignment-failed', cues: []})});
    });
    assert.equal(await page.locator('#avatar-notice').isVisible(), false, 'Successful fallback must be silent');
    await page.evaluate(() => {
      for (let i = 0; i < 20; i++) cardTool({name: 'calculator', result: {value: i}, ms: 1});
    });
    assert.equal(await page.locator('.activity-row').count(), 12);
    await page.evaluate(() => onMessage({data: JSON.stringify({type: 'reset'})}));
    assert.equal(await page.locator('.activity-row').count(), 0);
    assert.equal(await page.locator('#result-panel').isVisible(), false);
    assert.deepEqual(report.errors, []);
    console.log(JSON.stringify(report, null, 2));
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(resolve));
    fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
  }
})().catch(error => {console.error(error); server.close(); process.exitCode = 1;});

