#!/usr/bin/env node
// tools/check.js - render the board headless and refuse anything broken.
//
//   node tools/check.js dist/platt-park-live-board-v4.html [--compare platt-park-live-board-v4.html]
//
// Loads the page from file:// with the repo's real beers.json, a fixed clock
// (America/Denver) and a fake weather answer, at six moments that exercise the
// scene logic. Any page error, a wrong tank count or a wrong scene fails the
// build. --compare renders both files at 2pm with animations frozen and fails
// if more than 0.5% of pixels differ - that is how the split proved lossless.
//
// Needs: npm i puppeteer-core pngjs pixelmatch; CHROME_PATH pointing at a Chrome.
const fs = require('fs'), path = require('path');
const puppeteer = require('puppeteer-core');

const args = process.argv.slice(2);
const target = path.resolve(args[0]);
const compareIdx = args.indexOf('--compare');
const compareTo = compareIdx >= 0 ? path.resolve(args[compareIdx + 1]) : null;
const repo = path.resolve(__dirname, '..');
const beers = JSON.parse(fs.readFileSync(path.join(repo, 'beers.json'), 'utf8'));
const chrome = process.env.CHROME_PATH || '/usr/bin/google-chrome';

// moment (Denver local) -> what must be true
const MOMENTS = [
  { at: '2026-09-19T09:00:00-06:00', name: 'sat 9am',    curtain: true,  night: true,  text: /doors/i },   // night runs until the 10:30 open
  { at: '2026-09-19T10:45:00-06:00', name: 'sat 10:45',  curtain: false, night: false },
  { at: '2026-09-19T14:00:00-06:00', name: 'sat 2pm',    curtain: false, night: false },
  { at: '2026-09-19T21:30:00-06:00', name: 'sat 9:30pm', curtain: false, night: true },
  { at: '2026-09-19T23:30:00-06:00', name: 'sat 11:30pm (late night)', curtain: false, night: true },
  { at: '2026-09-22T23:30:00-06:00', name: 'tue 11:30pm (goodnight)',  curtain: true,  night: true },
];

async function open(browser, file, iso, freeze, opt) {
  opt = opt || {};
  const page = await browser.newPage();
  await page.setViewport({ width: 1920, height: 1080 });
  const errors = [];
  page.on('pageerror', e => errors.push(String(e.message || e)));
  page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
  await page.setRequestInterception(true);
  page.on('request', r => {
    const u = r.url();
    if (u.includes('open-meteo')) return r.respond({ status: 200, contentType: 'application/json',
      headers: { 'Access-Control-Allow-Origin': '*' },
      body: JSON.stringify({ current: { temperature_2m: opt.temp == null ? 64 : opt.temp, weather_code: opt.code == null ? 1 : opt.code }, daily: { sunset: [iso.slice(0, 10) + 'T19:03'] } }) });
    if (u.includes('beers.json')) return r.respond({ status: 200, contentType: 'application/json',
      body: opt.beers ? JSON.stringify(opt.beers) : fs.readFileSync(path.join(repo, 'beers.json'), 'utf8') });
    if (u.includes('menu_state.json')) return r.respond({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ four_packs: '4-packs to go: Chela Morena $15 \u00b7 Pistachio $16 \u00b7 Plattmosphere $18 \u00b7 also at gatesdeli.com for pickup.' }) });
    if (r.method() === 'HEAD') return r.respond({ status: 200, headers: { etag: '"check"' }, body: '' });
    if (u.startsWith('http')) return r.abort();      // nothing else leaves the runner
    return r.continue();
  });
  await page.emulateTimezone('America/Denver');
  await page.evaluateOnNewDocument((iso, freeze) => {
    const fixed = new Date(iso).getTime(); const RD = Date;
    class FD extends RD { constructor(...a) { super(...(a.length ? a : [fixed])); } static now() { return fixed; } }
    window.Date = FD;
    try { localStorage.clear(); } catch (e) {}
    if (freeze) document.addEventListener('DOMContentLoaded', () => {
      const st = document.createElement('style');
      st.textContent = '*,*::before,*::after{animation-play-state:paused!important;transition:none!important}';
      document.head.appendChild(st);
    });
  }, iso, freeze);
  await page.goto('file://' + file, { waitUntil: 'networkidle0' });
  await new Promise(r => setTimeout(r, 2500));
  return { page, errors };
}

(async () => {
  const browser = await puppeteer.launch({ executablePath: chrome, args: ['--no-sandbox', '--disable-gpu', '--allow-file-access-from-files'], headless: true });
  let failed = 0;
  const say = (ok, msg) => { console.log((ok ? '  ok   ' : '  FAIL ') + msg); if (!ok) failed++; };

  for (const m of MOMENTS) {
    const { page, errors } = await open(browser, target, m.at, false);
    const st = await page.evaluate(() => ({
      units: document.querySelectorAll('.unit').length,
      curtain: document.body.classList.contains('curtained'),
      night: document.body.classList.contains('night'),
      curtainText: (document.querySelector('.curtain, #curtain') || {}).innerText || '',
      temp: (document.querySelector('#wxDeg') || {}).innerText || '',
    }));
    say(errors.length === 0, `${m.name}: no page errors` + (errors.length ? ' -> ' + errors.slice(0, 2).join(' | ') : ''));
    say(st.units === beers.beers.length, `${m.name}: ${st.units} tanks for ${beers.beers.length} beers`);
    say(st.curtain === m.curtain, `${m.name}: curtain ${st.curtain} (expected ${m.curtain})`);
    say(st.night === m.night, `${m.name}: night ${st.night} (expected ${m.night})`);
    if (m.text) say(m.text.test(st.curtainText), `${m.name}: curtain says "${st.curtainText.replace(/\s+/g, ' ').slice(0, 40)}"`);
    if (!m.curtain) say(/°/.test(st.temp), `${m.name}: weather in the header ("${st.temp}")`);
    await page.close();
  }

  /* ---- LAYOUT: the fixes from Oct 20 2026 hold in every state the wall can be in ----
     (band / no band, snow, heat, dusk, night, each season's map, a full wall, a short wall, sashes, NEW, long names) */
  const base = JSON.parse(fs.readFileSync(path.join(repo, 'beers.json'), 'utf8'));
  const clone = o => JSON.parse(JSON.stringify(o));
  const many = clone(base); while (many.beers.length < 16) { const b = clone(base.beers[many.beers.length % base.beers.length]); b.id += '-x' + many.beers.length; b.name += ' ' + many.beers.length; many.beers.push(b); }
  const few = clone(base); few.beers = few.beers.slice(0, 4);
  const odd = clone(base); odd.beers[0].sash = 'last keg'; odd.beers[1].tappedAt = Date.parse('2026-10-19T12:00:00-06:00');
    odd.beers[2].name = 'Grandma\u2019s Extra Long Pumpkin Pie Ale'; delete odd.beers[3].note; odd.beers[4].pick = true;
  const SCENES = [
    { name: 'tue 4pm band',            at: '2026-10-20T16:00:00-06:00' },
    { name: 'mon 6pm industry band',   at: '2026-10-19T18:00:00-06:00' },
    { name: 'wed 6pm pitcher band',    at: '2026-10-21T18:00:00-06:00' },
    { name: 'thu 3pm no band',         at: '2026-10-22T15:00:00-06:00' },
    { name: 'sat 10am weekend',        at: '2026-10-24T10:45:00-06:00' },
    { name: 'thu snow day',            at: '2026-10-22T15:00:00-06:00', code: 73, temp: 24 },
    { name: 'thu scorcher',            at: '2026-07-16T15:00:00-06:00', temp: 97 },
    { name: 'thu dusk',                at: '2026-10-22T18:55:00-06:00' },
    { name: 'fri 9:30pm night',        at: '2026-10-23T21:30:00-06:00' },
    { name: 'winter map',              at: '2027-01-14T15:00:00-07:00' },
    { name: 'spring map',              at: '2027-04-15T15:00:00-06:00' },
    { name: 'summer map',              at: '2027-07-15T15:00:00-06:00' },
    { name: '16 taps (dense)',         at: '2026-10-22T15:00:00-06:00', beers: many },
    { name: '4 taps',                  at: '2026-10-22T15:00:00-06:00', beers: few },
    { name: 'sash + NEW + long name',  at: '2026-10-20T16:00:00-06:00', beers: odd },
  ];
  for (const sc of SCENES) {
    const { page, errors } = await open(browser, target, sc.at, true, sc);
    await new Promise(r => setTimeout(r, 1200));
    const L = await page.evaluate(() => {
      const R = e => { if (!e) return null; const r = e.getBoundingClientRect(); return { l: r.left, r: r.right, t: r.top, b: r.bottom, w: r.width, h: r.height }; };
      const vis = e => e && getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().height > 0;
      const rail = R(document.querySelector('.rail'));
      const units = [...document.querySelectorAll('#floor .unit')];
      const prices = units.map(u => R(u.querySelector('.price .tag') || u.querySelector('.price'))).filter(Boolean);
      const rows = {}; units.forEach((u, i) => { const t = Math.round(R(u).t / 40); (rows[t] = rows[t] || []).push(prices[i]); });
      const rowSpread = Math.max(0, ...Object.values(rows).map(ps => { const bs = ps.filter(Boolean).map(p => p.b); return bs.length > 1 ? Math.max(...bs) - Math.min(...bs) : 0; }));
      const lowest = Math.max(...units.map(u => { const p = u.querySelector('.plate'); return Math.max(R(u.querySelector('.price')).b, ...[...p.children].filter(vis).map(c => R(c).b)); }));
      const names = units.map(u => { const n = u.querySelector('.name'), r = R(u); return { over: n.scrollWidth - n.clientWidth, nb: R(n).r - r.r, na: r.l - R(n).l, name: n.textContent }; });
      const qr = document.querySelector('img[src*="qr"]'), qcell = qr && R(qr.closest('.cell'));
      const ranger = R(document.querySelector('.ranger img'));
      const side = R(document.querySelector('.side'));
      const banner = document.getElementById('banner'), band = banner.classList.contains('show') ? R(banner) : null;
      const firstTop = Math.min(...units.map(u => R(u.querySelector('.tankwrap')).t));
      const cells = [['mostK', 'most'], ['railK', 'railMsg']].map(([a, b]) => { const k = document.getElementById(a), v = document.getElementById(b); return k && v && vis(k) && vis(v) ? R(v).l - R(k).r : 99; });
      const before = getComputedStyle(document.body, '::before');
      return { rail, lowest, rowSpread, names, qcell, ranger, side, band, firstTop, cellGap: Math.min(...cells),
               mapOpacity: +before.opacity, mapImg: before.backgroundImage, dark: document.body.classList.contains('dark'),
               curtained: document.body.classList.contains('curtained'), taste: units.filter(u => (u.querySelector('.taste') || {}).textContent).length };
    });
    const n = sc.name;
    say(errors.length === 0, `${n}: no page errors` + (errors.length ? ' -> ' + errors.slice(0, 2).join(' | ') : ''));
    if (L.curtained) { await page.close(); continue; }
    say(L.lowest <= L.rail.t - 24, `${n}: every beer card clears the rail by 24px+ (lowest ${Math.round(L.lowest)}, rail ${Math.round(L.rail.t)})`);
    say(L.rowSpread <= 8, `${n}: price tags line up across each row (spread ${Math.round(L.rowSpread)}px)`);
    const bad = L.names.filter(x => x.over > 2 || x.nb > 6 || x.na > 6);
    say(bad.length === 0, `${n}: every beer name fits its column` + (bad.length ? ' -> ' + bad.map(x => x.name).join(', ') : ''));
    if (L.band) say(L.band.b <= L.firstTop - 4, `${n}: the band clears the top row (band ${Math.round(L.band.b)}, tanks ${Math.round(L.firstTop)})`);
    say(L.side.b <= L.rail.t - 4, `${n}: Also Pouring clears the rail`);
    if (L.ranger && L.qcell) {
      const cx = (L.ranger.l + L.ranger.r) / 2, qx = (L.qcell.l + L.qcell.r) / 2;
      say(Math.abs(cx - qx) <= 30 && Math.abs(L.ranger.b - L.rail.t) <= 12 && L.ranger.r <= 1915,
          `${n}: ranger stands over the QR code (off by ${Math.round(cx - qx)}px, feet ${Math.round(L.ranger.b - L.rail.t)}px from the rail)`);
      say(L.ranger.t >= L.side.b - 4 || L.ranger.r <= L.side.l || L.ranger.l >= L.side.r, `${n}: ranger and Also Pouring don't overlap`);
    }
    say(L.cellGap >= 6, `${n}: bottom-bar labels keep their space (${Math.round(L.cellGap)}px)`);
    say(/url\(/.test(L.mapImg) && (!L.dark || L.mapOpacity >= 0.75), `${n}: topo map drawn at TV strength (opacity ${L.mapOpacity})`);
    say(L.taste >= 1, `${n}: taste lines showing (${L.taste})`);
    await page.close();
  }

  if (compareTo) {
    const { PNG } = require('pngjs'); const pixelmatch = require('pixelmatch');
    const shots = [];
    for (const f of [target, compareTo]) {
      const { page } = await open(browser, f, '2026-09-19T14:00:00-06:00', true);
      shots.push(PNG.sync.read(Buffer.from(await page.screenshot({ type: 'png' }))));
      await page.close();
    }
    const [a, b] = shots;
    const diff = pixelmatch(a.data, b.data, null, a.width, a.height, { threshold: 0.15 });
    const pct = diff / (a.width * a.height) * 100;
    say(pct < 0.5, `pixel diff vs ${path.basename(compareTo)}: ${pct.toFixed(3)}% of pixels`);
  }

  await browser.close();
  console.log(failed ? `\n${failed} check(s) failed - not publishing` : '\nall checks passed');
  process.exit(failed ? 1 : 0);
})().catch(e => { console.error('check crashed:', e); process.exit(2); });
