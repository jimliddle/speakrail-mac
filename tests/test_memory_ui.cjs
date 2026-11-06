// Real standalone server and editor, synthetic data, no inference or physical microphone.
const {chromium} = require('node:module').createRequire(require('node:path').resolve(__dirname,'../mac/package.json'))('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const root = path.resolve(__dirname, '..');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
(async () => {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'speakrail-memory-test-'));
  const reservation = net.createServer();
  reservation.listen(0, '127.0.0.1'); await once(reservation, 'listening');
  const port = reservation.address().port;
  await new Promise(resolve => reservation.close(resolve));
  let key = require('node:crypto').randomBytes(32).toString('hex');
  let child, browser;
  async function start() {
    child = spawn(process.env.PYTHON || 'python3', [path.join(root,'app/server.py'), '--stub', '--no-notes',
      '--port', String(port), '--memory-dir', temp], {env:{...process.env, UI_HOST:'127.0.0.1',
      SEARCH:'off', FIREWORKS_API_KEY:'', SPEAKRAIL_MEMORY_KEY:key}, stdio:['ignore','pipe','pipe']});
    let ready = false, error = '';
    child.stdout.on('data', b => { if (b.toString().includes('open http')) ready = true; });
    child.stderr.on('data', b => { error += b.toString(); });
    for (let i=0;i<100&&!ready;i++) {
      if (child.exitCode!==null) throw Error('Test server exited: '+error.replaceAll(key,'[redacted]'));
      await delay(100);
    }
    assert(ready,'Test server readiness timeout');
  }
  async function stop() {
    if (child && child.exitCode===null) { const ended=once(child,'exit'); child.kill('SIGTERM'); await ended; }
  }
  try {
    await start();
    browser = await chromium.launch({headless:true,args:['--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream']});
    const context = await browser.newContext({permissions:['microphone']});
    await context.route('**/*', route => new URL(route.request().url()).hostname==='127.0.0.1' ? route.continue() : route.abort());
    const page = await context.newPage();
    const errors=[]; page.on('pageerror', e=>errors.push(e.message));
    const origin=`http://127.0.0.1:${port}`;
    assert.equal((await context.request.get(origin+'/memory')).status(),403);
    await page.goto(origin+'/#memory-key='+key);
    await page.locator('#memory-open').waitFor({state:'attached'});
    assert(!page.url().includes(key));
    await page.locator('#gear').click();
    await page.locator('#memory-open').click();
    await page.waitForFunction(()=>document.querySelector('#memory-file').options.length===2);
    for (const [width,height] of [[1440,900],[390,844],[844,390]]) {
      await page.setViewportSize({width,height});
      const box=await page.locator('#memory-dialog').boundingBox();
      assert(box.x>=0&&box.y>=0&&box.x+box.width<=width&&box.y+box.height<=height);
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
      const output=path.join(root,'artifacts/memory-ui'); fs.mkdirSync(output,{recursive:true});
      await page.screenshot({path:path.join(output,`editor-${width}.png`)});
    }
    await page.setViewportSize({width:1440,height:900});
    await page.locator('#memory-file').selectOption('profile');
    await page.locator('#memory-text').fill('Synthetic user likes short replies.');
    await page.locator('#memory-save').click();
    await page.waitForFunction(()=>document.querySelector('#memory-status').textContent.startsWith('Saved'));
    await page.locator('#memory-new').click();
    await page.locator('#memory-text').fill('<img src=x onerror=alert(1)> Synthetic telescope note');
    await page.locator('#memory-save').click();
    await page.waitForFunction(()=>document.querySelector('#memory-file').options.length===3);
    assert.equal(await page.locator('#memory-dialog img').count(),0);
    await page.keyboard.press('Escape');
    assert(!await page.locator('#memory-dialog').isVisible());
    await stop(); key = require('node:crypto').randomBytes(32).toString('hex'); await start();
    assert.equal((await context.request.get(origin+'/memory')).status(),403);
    const authenticated = page.waitForResponse(response=>response.url().endsWith('/memory/connect')&&response.status()===200);
    await page.goto(origin+'/#memory-key='+key);
    await authenticated;
    await page.locator('#memory-open').waitFor({state:'attached'});
    const data=await (await context.request.get(origin+'/memory')).json();
    assert(data.files.some(f=>f.text.includes('Synthetic telescope')));
    assert(data.files.some(f=>f.id==='profile'&&f.text.includes('short replies')));
    await page.locator('#gear').click(); await page.locator('#memory-open').click();
    await page.waitForFunction(()=>document.querySelector('#memory-file').options.length===3);
    await page.locator('#memory-file').selectOption(data.files.find(f=>f.text.includes('Synthetic telescope')).id);
    page.once('dialog', d=>d.accept()); await page.locator('#memory-delete').click();
    await page.waitForFunction(()=>document.querySelector('#memory-file').options.length===2);
    await page.locator('#memory-close').click(); await page.locator('#gear').click();
    await page.locator('#go').click();
    await page.waitForFunction(()=>running);
    await page.locator('#gear').click(); await page.locator('#memory-open').click();
    await page.waitForFunction(()=>document.querySelector('#memory-text').readOnly);
    assert(await page.locator('#memory-save').isDisabled());
    await page.locator('#memory-close').click(); await page.locator('#stop').click();
    await page.waitForFunction(()=>!running);
    assert.deepEqual(errors,[]);
    console.log('Standalone memory UI: auth, layout, edit/save/delete, restart persistence and active-session gate passed.');
  } finally {
    if(browser) await browser.close();
    await stop(); fs.rmSync(temp,{recursive:true,force:true});
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
