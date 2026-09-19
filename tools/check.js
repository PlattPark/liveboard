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

async function open(browser, file, iso, freeze) {
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
      body: JSON.stringify({ current: { temperature_2m: 64, weather_code: 1 }, daily: { sunset: ['2026-09-19T19:03'] } }) });
    if (u.includes('beers.json')) return r.respond({ status: 200, contentType: 'application/json',
      body: fs.readFileSync(path.join(repo, 'beers.json'), 'utf8') });
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
