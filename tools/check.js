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
  const eleven = clone(base); while (eleven.beers.length < 11) { const b = clone(base.beers[eleven.beers.length % base.beers.length]); b.id += '-e' + eleven.beers.length; eleven.beers.push(b); } eleven.beers = eleven.beers.slice(0, 11);
  const twelve = clone(eleven); { const b = clone(base.beers[0]); b.id += '-t'; b.name = 'Grandma\u2019s Pumpkin Pie'; twelve.beers.push(b); }
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
    { name: '11 taps (six across)',    at: '2026-10-20T16:00:00-06:00', beers: eleven },
    { name: '12 taps (six across)',    at: '2026-10-22T15:00:00-06:00', beers: twelve },
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
      const priceGap = Math.min(999, ...Object.values((() => { const g = {}; units.forEach(u => { const t = Math.round(R(u).t / 40); (g[t] = g[t] || []).push(R(u.querySelector('.price'))); }); return g; })()).map(ps => { ps.sort((a, c) => a.l - c.l); let m = 999; for (let i = 1; i < ps.length; i++) m = Math.min(m, ps[i].l - ps[i - 1].r); return m; }));
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
      return { priceGap, rail, lowest, rowSpread, names, qcell, ranger, side, band, firstTop, cellGap: Math.min(...cells),
               mapOpacity: +before.opacity, mapImg: before.backgroundImage, dark: document.body.classList.contains('dark'),
               curtained: document.body.classList.contains('curtained'), taste: units.filter(u => (u.querySelector('.taste') || {}).textContent).length };
    });
    const n = sc.name;
    say(errors.length === 0, `${n}: no page errors` + (errors.length ? ' -> ' + errors.slice(0, 2).join(' | ') : ''));
    if (L.curtained) { await page.close(); continue; }
    say(L.lowest <= L.rail.t - 24, `${n}: every beer card clears the rail by 24px+ (lowest ${Math.round(L.lowest)}, rail ${Math.round(L.rail.t)})`);
    const minGap = (sc.beers && sc.beers.beers.length >= 15) ? 10 : 14;   // a full eight-across wall: the column width sets the gap
    say(L.priceGap >= minGap, `${n}: neighbouring price tags keep ${minGap}px+ apart (${Math.round(L.priceGap)}px)`);
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

  // ---- Nov 2026: the tap-count sweep. Every tap count 4-16, with the longest names the wall has really poured,
  // drawn normally AND with text forced ~5% wider (stand-in for the ProDesk's Windows Chrome). Nothing may spill
  // out of its card, sit under the ticker or Also Pouring, or crowd the next price tag. This is the test that
  // would have caught every layout break since September.
  {
    const fs = require('fs');
    let live = { beers: [], recent: [], also: [] };
    try { live = JSON.parse(fs.readFileSync(path.join(path.dirname(target), 'beers.json'), 'utf8')); } catch (e) {}
    const fixtures = [
      { name: 'Creature Comforts Tropicalia', style: 'IPA', wall: 'guest tap · IPA · Athens GA', note: 'tropical, bright, bitter finish', abv: 6.6, price: 8.5, price10: 5.25, color: '#d69a2b', vessel: 'keg-half', vesselLabel: '1/2 BBL', capacityOz: 1984, remainingOz: 1500 },
      { name: 'Half Acre Original Reaper', style: 'Stout', wall: 'guest tap · Stout · Chicago', note: 'roast, cocoa, dry', abv: 6, price: 8.5, price10: 5.25, color: '#2a1810', vessel: 'keg-half', vesselLabel: '1/2 BBL', capacityOz: 1984, remainingOz: 1200 },
      { name: "Grandma's Pumpkin Pie", style: 'Spiced Ale', wall: 'Spiced Ale · Nitro', note: 'pumpkin pie spice, contains lactose', abv: 5.5, price: 8, price10: 5, color: '#d9a05a', vessel: 'tank10', vesselLabel: '10 BBL', capacityOz: 39680, remainingOz: 20000 }
    ];
    const pool = [...(live.beers || []), ...(live.recent || []), ...fixtures].filter(b => b && b.name && b.price)
      .sort((a, b) => b.name.length - a.name.length);
    for (const wide of [false, true]) for (let n = 4; n <= 16; n++) {
      const data = JSON.parse(JSON.stringify(live)); data.beers = [];
      for (let i = 0; i < n; i++) { const b = JSON.parse(JSON.stringify(pool[i % pool.length])); b.id = String(b.id || 'b') + '-s' + i; data.beers.push(b); }
      const page = await browser.newPage(); await page.setViewport({ width: 1920, height: 1080 }); await page.setRequestInterception(true);
      page.on('request', r => { const u = r.url();
        if (u.includes('beers.json')) return r.respond({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
        if (u.includes('menu_state')) return r.respond({ status: 200, contentType: 'application/json', body: '{}' });
        if (u.startsWith('http')) return r.abort(); r.continue(); });
      await page.goto('file://' + path.resolve(target) + '?preview', { waitUntil: 'networkidle0' }); await new Promise(r => setTimeout(r, 1500));
      if (wide) { await page.addStyleTag({ content: '.plate *{letter-spacing:.045em !important}' }); await page.evaluate(() => window.__fitText && window.__fitText()); await new Promise(r => setTimeout(r, 300)); }
      const L = await page.evaluate(() => { const R = e => e.getBoundingClientRect(); const units = [...document.querySelectorAll('#floor .unit')];
        const rail = R(document.querySelector('.rail')); const sideEl = document.querySelector('.side'); const side = sideEl ? R(sideEl) : null; const issues = []; const rows = {};
        const span = e => { const g = document.createRange(); g.selectNodeContents(e); return g.getBoundingClientRect(); };
        units.forEach(u => { const ur = R(u); const pl = u.querySelector('.plate'); const nm = pl.querySelector('.name'); const tag = pl.querySelector('.price .tag') || pl.querySelector('.price'); const tr = R(tag);
          (rows[Math.round(ur.top / 40)] = rows[Math.round(ur.top / 40)] || []).push(tr);
          const nr = span(nm); if (nr.left < ur.left - 2 || nr.right > ur.right + 2) issues.push('name spills: ' + nm.textContent);
          if (tr.left < ur.left - 2 || tr.right > ur.right + 2) issues.push('price spills: ' + nm.textContent);
          [pl.querySelector('.note'), pl.querySelector('.taste')].forEach(e => { if (!e || !e.textContent.trim()) return; const er = span(e); if (er.left < ur.left - 2 || er.right > ur.right + 2) issues.push('line spills: ' + e.textContent.slice(0, 25)); });
          if (tr.bottom > rail.top - 6) issues.push('price under the ticker: ' + nm.textContent);
          { const last = [pl.querySelector('.taste'), pl.querySelector('.note'), nm].find(e => e && e.textContent.trim()); if (last && span(last).bottom > tr.top - 3) issues.push('text runs into its price: ' + nm.textContent); }
          if (side && ur.right > side.left - 4 && ur.top < side.bottom) issues.push('card under Also Pouring: ' + nm.textContent); });
        Object.values(rows).forEach(ts => { ts.sort((a, b) => a.left - b.left); for (let i = 1; i < ts.length; i++) if (ts[i].left - ts[i - 1].right < 8) issues.push('price tags ' + Math.round(ts[i].left - ts[i - 1].right) + 'px apart'); });
        return { issues: [...new Set(issues)], n: units.length }; });
      say(L.issues.length === 0 && L.n === n, `sweep ${wide ? 'wide text ' : ''}${n} taps: every card fits${L.issues.length ? ' - ' + L.issues.slice(0, 3).join(' | ') : ''}`);
      await page.close();
    }
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
