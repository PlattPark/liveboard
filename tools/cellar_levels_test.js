// Runs tools/cellar_levels.gs against fake Drive/Sheets objects built from Greg's real November numbers.
const fs = require('fs'), vm = require('vm');
const src = fs.readFileSync(require('path').join(__dirname, 'cellar_levels.gs'), 'utf8');
const E = '';
const row = (name, starting, sv, bbls, fv, fvbbls, kegs, casks, end) => [name, starting, sv, bbls, fv, fvbbls, kegs, casks, end];
const wk1 = [row('',0,E,E,E,E,E,E,0), row('Tropic',22.2,8,2,7,19,E,E,21), row('Astronaut',11.4,3,8.2,E,E,1,E,8.7), row('Wit',6.6,1,4,E,E,E,E,4), row('Phaded',8,5,6.7,E,E,E,E,6.7),
  row('Chela',1.3,E,E,E,E,1.6,E,0.8), row('PP Porter',10,E,E,2,10,E,E,10), row('Platty Lite',18.8,6,16.2,1,20,2,E,37.2), row('Cream',22.5,4,18.9,E,E,E,E,18.9), row('Pumpkin',4.9,2,4.5,E,E,E,E,4.5),
  row('Nadare',2.3,E,E,E,E,2,E,1), row('Pistachio',3.4,7,1.9,E,E,1,E,2.4), row('Berliner',E,E,E,5,10,E,E,10), row('Plattmo',20.1,E,E,'3.8',28,E,E,28)];
const wk2 = [row('',0,E,E,E,E,E,E,0), row('Tropic',21,8,7,E,E,2,E,8), row('Astronaut',8.7,3,6.8,E,E,1,E,7.3), row('Wit',4,1,3.6,E,E,E,E,3.6), row('Phaded',6.7,5,5.8,E,E,E,E,5.8),
  row('Chela',0.8,E,E,E,E,E,E,0), row('PP Porter',10,E,E,2,10,E,E,10), row('Platty Lite',37.2,6,14.4,1,20,2,E,35.4), row('Cream',18.9,4,18.2,E,E,E,E,18.2), row('Pumpkin',4.5,2,3.6,E,E,E,E,3.6),
  row('Nadare',1,E,E,E,E,0.5,E,0.25), row('Pistachio',2.4,7,1.3,E,E,1,E,1.8), row('Berliner',10,E,E,5,10,E,E,10), row('Plattmo',28,E,E,'3.8',28,E,E,28)];
const empty = [row('',E,E,E,E,E,E,E,0), row('',E,E,E,E,E,E,E,0)];
const octWk5 = [row('',0,E,E,E,E,E,E,0), row('Tropic',24,8,3.2,7,19,E,E,22.2), row('Astronaut',12.4,E,E,E,E,E,E,11.4), row('Wit',4.6,1,4.3,E,E,E,E,6.6), row('Phaded',8.8,5,8,E,E,E,E,8),
  row('Chela',1.3,E,E,E,E,E,E,1.3), row('PP Porter',0,E,E,2,10,E,E,10), row('Platty Lite',21.55,6,17.8,E,E,E,E,18.8), row('Cream',24.7,4,2.5,E,E,E,E,22.5), row('Pumpkin',5.4,2,4.9,E,E,E,E,4.9),
  row('Nadare',3.4,3,2.3,E,E,E,E,2.3), row('Pistachio',4,7,3.4,E,E,E,E,3.4), row('Berliner',10,E,E,E,E,E,E,10), row('Plattmo',3,9,1.1,E,E,E,E,20.1)];
const octWk4 = octWk5.map(r => { const c = r.slice(); if (c[0]) { c[8] = c[1]; c[1] = +(c[1] + 1).toFixed(2); } return c; });   // a week whose end = wk5's starting
const sheet = (name, rows) => ({ getName: () => name, getLastRow: () => rows.length + 2,
  getRange: (r, c, n, w) => ({ getValues: () => rows.slice(0, n).map(x => x.slice(c - 1, c - 1 + w)) }) });
const file = (name, updated, tabs) => ({ getName: () => name, getId: () => name, getLastUpdated: () => new Date(updated), _tabs: tabs });
function run(files) {
  const byId = Object.fromEntries(files.map(f => [f.getId(), f]));
  const ctx = { DriveApp: { searchFiles: () => { let i = 0; return { hasNext: () => i < files.length, next: () => files[i++] }; } },
    SpreadsheetApp: { openById: id => ({ getSheets: () => byId[id]._tabs.map(([n, rows]) => sheet(n, rows)) }) },
    ContentService: { createTextOutput: t => ({ setMimeType: () => t }), MimeType: { JSON: 'json' } }, Logger: { log() {} } };
  vm.createContext(ctx); vm.runInContext(src, ctx);
  return JSON.parse(vm.runInContext('doGet()', ctx));
}
const october = file('October 26', '2026-11-02T18:43:19Z', [['wk 1', octWk4.map(r => { const c = r.slice(); if (c[0]) { c[8] = c[1]; c[1] = +(c[1] + 1).toFixed(2); } return c; })], ['wk 2', empty], ['wk 3', empty], ['wk4', octWk4], ['wk5', octWk5]]);
const noise = [file('Sales/Invoice Tracker', '2026-11-18T00:00:00Z', []), file('7.11.25 Inventory', '2025-07-11T00:00:00Z', [])];
let pass = 0, fail = 0;
const check = (name, got, want) => { const ok = JSON.stringify(got) === JSON.stringify(want); ok ? pass++ : fail++; console.log((ok ? '  ok   ' : '  FAIL ') + name + (ok ? '' : '\n        got  ' + JSON.stringify(got) + '\n        want ' + JSON.stringify(want))); };
const lv = (o, n) => (o.levels.find(r => r.name === n) || {}).bbls;

let o = run([october, file('November 26', '2026-11-16T19:58:54.111Z', [['wk 1', wk1], ['wk 2', wk2], ['wk 3', empty], ['wk4', empty], ['wk5', octWk5]]), ...noise]);
check('November as it is today: wk 2 is served, not the leftovers in wk5', [o.sheet, o.tab, lv(o, 'Platty Lite'), lv(o, 'Cream'), lv(o, 'Pistachio'), o.updated], ['November 26', 'wk 2', 14.4, 18.2, 1.3, '2026-11-16T19:58:54.111Z']);
check('...and it says why wk5 was passed over', o.notes.some(n => /wk5/.test(n) && /not used/.test(n)), true);
check('the rows keep the shape Computa reads', Object.keys(o.levels[0]), ['name', 'starting', 'sv', 'bbls', 'fv', 'fvbbls', 'kegs', 'casks', 'end']);
check('serving tank numbers come through as text', o.levels.find(r => r.name === 'Tropic').sv, '8');

const nov = file('November 26', '2026-11-16T19:58:54.111Z', [['wk 1', wk1], ['wk 2', wk2], ['wk 3', empty], ['wk4', empty], ['wk5', octWk5]]);
o = run([nov, file('December 26', '2026-12-07T15:00:00Z', [['wk 1', empty], ['wk 2', empty]])]);
check('a new month with nothing in it yet: last month’s final count stays', [o.sheet, o.tab, o.updated], ['November 26', 'wk 2', '2026-11-16T19:58:54.111Z']);

o = run([nov, file('December 26', '2026-12-07T15:00:00Z', [['wk 1', wk1], ['wk 2', wk2], ['wk 3', empty], ['wk4', empty], ['wk5', octWk5]])]);
check('a new month that is a copy of the old file, nothing filled in: still last month’s final count', [o.sheet, o.tab], ['November 26', 'wk 2']);

const decWk1 = wk2.map(r => { const c = r.slice(); if (c[0]) { c[1] = c[8]; if (typeof c[3] === 'number') c[3] = +(c[3] - 0.5).toFixed(1); c[8] = typeof c[8] === 'number' ? +(c[8] - 0.5).toFixed(2) : c[8]; } return c; });
o = run([nov, file('December 26', '2026-12-07T19:00:00Z', [['wk 1', decWk1], ['wk 2', wk2], ['wk 3', empty], ['wk4', empty], ['wk5', octWk5]])]);
check('week one filled in, old numbers still sitting in wk 2 and wk5: week one is served', [o.sheet, o.tab, lv(o, 'Platty Lite')], ['December 26', 'wk 1', 13.9]);

const wk3 = wk2.map(r => { const c = r.slice(); if (c[0]) { c[1] = c[8]; if (typeof c[3] === 'number') c[3] = +(c[3] - 1).toFixed(1); } return c; });
o = run([october, file('November 26', '2026-11-30T19:00:00Z', [['wk 1', wk1], ['wk 2', wk2], ['wk 3', empty], ['wk4', wk3], ['wk5', octWk5]])]);
check('a skipped week in the middle is stepped over', [o.tab, lv(o, 'Platty Lite')], ['wk4', 13.4]);

o = run([file('November 26', '2026-11-16T19:58:54.111Z', [['wk 1', wk1], ['wk 2', wk2]])]);
check('only one file exists: its first filled week is taken on trust and the chain runs from there', [o.sheet, o.tab], ['November 26', 'wk 2']);
o = run(noise);
check('no monthly file at all: an error, not a guess', !!o.error, true);
console.log(`\n${pass} passed, ${fail} failed`); process.exit(fail ? 1 : 0);
