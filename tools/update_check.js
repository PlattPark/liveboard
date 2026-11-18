// How the wall decides to reload - tested in a real browser.
//
//   cd tools && npm i --no-audit --no-fund puppeteer-core@23        (the same install the render check uses)
//   python3 tools/board.py build && cp -r fonts ouray.svg beers.json maps menu_state.json dist/
//   CHROME_PATH=$(which google-chrome) node tools/update_check.js dist
//
// It serves the built board from a local server that behaves like GitHub Pages (every "publish" changes every
// file's ETag), drives the page's own 5-minute and 20-second checks, and counts real page loads. It covers what
// tools/check.js cannot see: that site publishes alone never reload the wall, that a new board build or a tap
// change reloads it exactly once, and that nothing reloads while the page it would load cannot be fetched.
// Not part of the publish gate - run it by hand after touching the updater (3-qol.js) or checkTaps (0-app.js).
const http = require('http'), fs = require('fs'), path = require('path');
const puppeteer = require('puppeteer-core');
const FILE = 'platt-park-live-board-v4.html';

function server(root) {
  const st = { deploy: 1, stamp: '', rangeStamp: '', failFull: false, offline: false, ignoreRange: false, beersPad: '', log: [] };
  const srv = http.createServer((req, res) => {
    const u = decodeURIComponent(req.url.split('?')[0]);
    const isPage = u.endsWith(FILE);
    const ranged = !!req.headers.range;
    if (st.offline || (isPage && st.failFull && !ranged && req.method === 'GET')) { st.log.push('DROP ' + req.method + ' ' + u); return req.socket.destroy(); }
    const f = path.join(root, u);
    if (!f.startsWith(root) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { res.writeHead(404); return res.end('nope'); }
    let body = fs.readFileSync(f);
    if (isPage) {
      let s = body.toString('utf8');
      const want = (ranged && st.rangeStamp) ? st.rangeStamp : st.stamp;
      if (want) s = s.replace(/<!-- built .+? - GENERATED/, '<!-- built ' + want + ' - GENERATED');
      body = Buffer.from(s, 'utf8');
    }
    if (u.endsWith('beers.json') && st.beersPad) body = Buffer.concat([body, Buffer.from(st.beersPad)]);
    const type = { '.html': 'text/html; charset=utf-8', '.json': 'application/json', '.svg': 'image/svg+xml', '.woff2': 'font/woff2', '.png': 'image/png' }[path.extname(f)] || 'application/octet-stream';
    const h = { 'Content-Type': type, 'Cache-Control': 'max-age=600', 'ETag': 'W/"' + (0x6afdf000 + st.deploy).toString(16) + '-' + body.length.toString(16) + '"', 'Accept-Ranges': 'bytes' };
    if (isPage) st.log.push(req.method + (ranged ? ' range' : ' full'));
    if (req.method === 'HEAD') { res.writeHead(200, h); return res.end(); }
    const m = /^bytes=(\d+)-(\d+)$/.exec(req.headers.range || '');
    if (m && !st.ignoreRange) {
      const a = +m[1], b = Math.min(+m[2], body.length - 1);
      h['Content-Range'] = 'bytes ' + a + '-' + b + '/' + body.length;
      res.writeHead(206, h); return res.end(body.subarray(a, b + 1));
    }
    res.writeHead(200, h); res.end(body);
  });
  return new Promise(r => srv.listen(0, '127.0.0.1', () => r({ srv, st, port: srv.address().port })));
}

const sleep = ms => new Promise(r => setTimeout(r, ms));

async function session(root, label) {
  const { srv, st, port } = await server(root);
  const browser = await puppeteer.launch({ executablePath: process.env.CHROME_PATH, headless: 'new',
    args: ['--no-sandbox', '--no-proxy-server', '--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1', '--window-size=1920,1080'] });
  const page = await browser.newPage();
  let loads = 0; const notes = [];
  page.on('load', () => { loads++; });
  page.on('console', m => { const t = m.text(); if (t.startsWith('[update]') || t.startsWith('[taps] change') || t.includes('now reachable')) notes.push(t); });
  await page.evaluateOnNewDocument(() => {
    window.__ivals = []; const si = window.setInterval;
    window.setInterval = function (fn, ms) { window.__ivals.push({ fn, ms }); return si.apply(this, arguments); };
    window.__fire = ms => window.__ivals.filter(i => i.ms === ms).forEach(i => { try { i.fn(); } catch (e) {} });
  });
  await page.goto('http://127.0.0.1:' + port + '/' + FILE, { waitUntil: 'load' });
  await sleep(1500);
  const api = {
    st, notes, label,
    reloads: () => loads - 1,
    fire: async ms => { try { await page.evaluate(m => window.__fire(m), ms); } catch (e) {} await sleep(1200); },
    clearFloor: async () => { try { await page.evaluate(() => sessionStorage.removeItem('ppb_reloaded')); } catch (e) {} },
    eval: async fn => { try { return await page.evaluate(fn); } catch (e) { return 'EVAL-FAILED ' + e.message; } },
    alive: async () => { const u = page.url(); let ok = false; try { ok = await page.evaluate(() => !!document.getElementById('floor') && document.querySelectorAll('#floor .vessel').length > 0); } catch (e) {} return ok && u.startsWith('http://127.0.0.1'); },
    close: async () => { await browser.close(); srv.close(); },
  };
  return api;
}

const results = [];
function expect(name, got, want) { const ok = JSON.stringify(got) === JSON.stringify(want); results.push(ok); console.log((ok ? '  ok   ' : '  FAIL ') + name + (ok ? '' : '  (got ' + JSON.stringify(got) + ', wanted ' + JSON.stringify(want) + ')')); }

(async () => {
  const NEW = path.resolve(process.argv[2] || 'dist');
  let s;

  s = await session(NEW, 'new');
  const stamp0 = await s.eval(() => window.__stamp);
  expect('page knows its own build stamp', /from src @/.test(String(stamp0)), true);
  for (let i = 0; i < 12; i++) { s.st.deploy++; await s.fire(300000); }
  expect('12 checks with a site publish between each: no reloads', s.reloads(), 0);
  expect('each check was a small ranged request', s.st.log.filter(l => l === 'GET range').length, 12);
  expect('...and never pulled the whole page', s.st.log.filter(l => l === 'GET full').length, 1);   // the first page load only

  // a new board build is published, but the full page cannot be fetched (network blip)
  const B1 = '2099-01-01T00:00Z from src @ aaaaaaa';
  s.st.stamp = B1; s.st.failFull = true;
  await s.fire(300000); await s.fire(300000);
  expect('new build + page not fetchable: no reload', s.reloads(), 0);
  expect('...and the board is still on screen', await s.alive(), true);
  s.st.failFull = false;
  await s.fire(300000); await sleep(1500);
  expect('new build + page fetchable: exactly one reload', s.reloads(), 1);
  expect('...the reloaded page is the new build', await s.eval(() => window.__stamp), B1);
  for (let i = 0; i < 4; i++) { s.st.deploy++; await s.fire(300000); }
  expect('...and it settles: no further reloads', s.reloads(), 1);

  // loop guard: another reason to reload arrives seconds after a reload
  s.st.stamp = '2099-01-02T00:00Z from src @ abababa';
  await s.fire(300000); await s.fire(300000);
  expect('second reload inside 90s is held back', s.reloads(), 1);
  await s.clearFloor(); await s.fire(300000); await sleep(1500);
  expect('...and goes through once the 90s have passed', s.reloads(), 2);

  // half-published: the probe sees a new stamp but the full page is still the old one
  await s.clearFloor();
  s.st.rangeStamp = '2099-02-02T00:00Z from src @ bbbbbbb';
  await s.fire(300000); await s.fire(300000);
  expect('probe says new, full page still old: no reload', s.reloads(), 2);
  s.st.stamp = s.st.rangeStamp; s.st.rangeStamp = '';
  await s.fire(300000); await sleep(1500);
  expect('once the full page matches: one reload', s.reloads(), 3);

  // a server that ignores Range and sends the whole page
  await s.clearFloor();
  s.st.ignoreRange = true;
  for (let i = 0; i < 3; i++) { s.st.deploy++; await s.fire(300000); }
  expect('range ignored, same build: no reload', s.reloads(), 3);
  s.st.stamp = '2099-03-03T00:00Z from src @ ccccccc';
  await s.fire(300000); await sleep(1500);
  expect('range ignored, new build: one reload', s.reloads(), 4);
  s.st.ignoreRange = false;

  // taps: beers.json flaps between two versions (a half-published site) - never the same twice in a row
  await s.clearFloor();
  for (let i = 0; i < 6; i++) { s.st.beersPad = i % 2 ? '' : ' '; await s.fire(20000); }
  expect('tap file flapping between two versions: no reload', s.reloads(), 4);
  // taps: a real change
  s.st.beersPad = '   '; s.st.failFull = true;
  await s.fire(20000); await s.fire(20000); await s.fire(20000);
  expect('tap list changed but page not fetchable: no reload', s.reloads(), 4);
  expect('...board still on screen', await s.alive(), true);
  s.st.failFull = false;
  await s.fire(20000); await sleep(1500);
  expect('tap list changed, page fetchable: one reload', s.reloads(), 5);
  const beersNow = await s.eval(() => SIM.beers.length);
  expect('...and the reloaded wall has beers on it', beersNow > 0, true);
  await s.clearFloor();
  for (let i = 0; i < 4; i++) await s.fire(20000);
  expect('...and no reload loop afterwards', s.reloads(), 5);
  // a fresh tap change right after: seen on check 1, acted on at check 2
  s.st.beersPad = '    ';
  await s.fire(20000);
  expect('new tap change: nothing on the first sighting', s.reloads(), 5);
  await s.fire(20000); await sleep(1500);
  expect('...reload on the second (about 40 seconds)', s.reloads(), 6);

  // the 3am refresh, with the network down and then up
  await s.clearFloor();
  s.st.offline = true;
  await s.eval(() => reloadSafely('3am refresh')); await sleep(1500);
  expect('3am refresh while offline: no reload', s.reloads(), 6);
  expect('...board still on screen (not the browser error page)', await s.alive(), true);
  for (let i = 0; i < 6; i++) { await s.fire(300000); await s.fire(20000); }
  expect('30 minutes fully offline: still no reload, board still up', [s.reloads(), await s.alive()], [6, true]);
  s.st.offline = false;
  await s.eval(() => reloadSafely('3am refresh')); await sleep(2000);
  expect('3am refresh with the network up: one reload', s.reloads(), 7);
  console.log('  page log: ' + s.notes.join(' | '));
  await s.close();

  const bad = results.filter(r => !r).length;
  console.log(bad ? bad + ' FAILED' : 'all ' + results.length + ' updater checks passed');
  process.exit(bad ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
