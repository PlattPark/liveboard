// cellar_levels.gs - Platt Park Brewing
//
// This file lives at script.google.com on Colby's account ("Cellar levels (Computa)"), deployed as a web app.
// The copy in the repo is the source: paste it into Code.gs, then Deploy > Manage deployments > edit > New version.
//
// It serves the newest week of Greg's inventory sheet as JSON. Computa reads it every half hour
// (computa.py, cellar_sync) and sets the tank levels on the wall. One Google Sheet per month ("November 26"),
// one tab per week ("wk 1".."wk 5"): column B = Starting, C = serving tank number, D = barrels in it, I = end bbls.
//
// WHICH TAB IS "THIS WEEK" (rewritten Nov 18 2026)
// It used to be the highest-numbered tab with numbers in it. Greg's November file had last month's final count
// left in its wk5 tab, so the script served the Nov 2 levels while two newer counts sat in wk 1 and wk 2.
// Now a week only counts if it FOLLOWS ON from the week before it: its Starting column has to match the previous
// week's end column, beer by beer. The first week of a file has to follow on from the last good week of the month
// before. The answer is the last week in that chain. Leftovers break the chain and are never served; an empty
// week in the middle is skipped, not fatal.

var MONTHS = ["january","february","march","april","may","june","july","august","september","october","november","december"];

function doGet(e) {
  var out;
  try { out = readCellar(); } catch (err) { out = {error: String(err)}; }
  return ContentService.createTextOutput(JSON.stringify(out)).setMimeType(ContentService.MimeType.JSON);
}

// Every spreadsheet named like "November 26" (month name + two-digit year), newest month first.
function monthlyFiles() {
  var files = [];
  var it = DriveApp.searchFiles("mimeType = 'application/vnd.google-apps.spreadsheet'");
  while (it.hasNext()) {
    var f = it.next();
    var m = f.getName().trim().toLowerCase().match(/^([a-z]+)\s+(\d{2})$/);
    if (!m || MONTHS.indexOf(m[1]) < 0) continue;
    files.push({file: f, order: (2000 + parseInt(m[2], 10)) * 12 + MONTHS.indexOf(m[1])});
  }
  files.sort(function (a, b) { return b.order - a.order; });
  return files.map(function (x) { return x.file; });
}

// The week tabs of one file as plain rows, in week order: [{name: "wk 2", n: 2, rows: [...]}, ...]
function weeksOf(ss) {
  var weeks = [];
  ss.getSheets().forEach(function (sh) {
    var m = sh.getName().trim().toLowerCase().match(/^wk\s*(\d+)/);
    if (!m) return;
    var count = Math.max(sh.getLastRow() - 2, 1);
    var rows = sh.getRange(3, 1, count, 9).getValues().map(function (r) {           // A..I from row 3
      return {name: String(r[0] || "").trim(), starting: r[1], sv: String(r[2] === 0 ? "0" : (r[2] || "")).trim(), bbls: r[3],
              fv: String(r[4] || "").trim(), fvbbls: r[5], kegs: r[6], casks: r[7], end: r[8]};
    }).filter(function (r) { return r.name && r.name.toLowerCase().indexOf("total") !== 0; });
    weeks.push({name: sh.getName(), n: parseInt(m[1], 10), rows: rows});
  });
  weeks.sort(function (a, b) { return a.n - b.n; });
  return weeks;
}

// A week counts once Greg has entered any serving-tank number in column D.
function hasLevels(rows) {
  return rows.some(function (r) { return typeof r.bbls === "number" && r.bbls > 0; });
}

// Does `next` follow on from `prev`? Its Starting numbers are prev's end numbers, beer by beer.
function followsOn(prev, next) {
  var ends = {};
  prev.forEach(function (r) { if (typeof r.end === "number") ends[r.name.toLowerCase()] = r.end; });
  var seen = 0, same = 0;
  next.forEach(function (r) {
    var e = ends[r.name.toLowerCase()];
    if (typeof r.starting !== "number" || typeof e !== "number") return;
    if (r.starting === 0 && e === 0) return;                      // an empty line agrees with anything
    seen++;
    if (Math.abs(r.starting - e) < 0.06) same++;
  });
  return seen >= 3 && same / seen >= 0.7;
}

// The last week of a file that is part of the chain. `before` = the rows the file's first week must follow on
// from (the month before's last good week), or null to take the first filled week on trust.
function lastGoodWeek(weeks, before, notes, label) {
  var prev = before, best = null;
  weeks.forEach(function (w) {
    if (!hasLevels(w.rows)) return;                               // not filled in yet (or skipped that week)
    if (prev && !followsOn(prev, w.rows)) {
      notes.push(label + " " + w.name + " has numbers that don't follow on from the week before it - not used");
      return;
    }
    best = w; prev = w.rows;
  });
  return best;
}

function readCellar() {
  var files = monthlyFiles();
  if (!files.length) return {error: "no monthly inventory sheet found"};
  var notes = [];
  var cur = files[0], old = files.length > 1 ? files[1] : null;
  var oldWeek = old ? lastGoodWeek(weeksOf(SpreadsheetApp.openById(old.getId())), null, [], old.getName()) : null;
  var week = lastGoodWeek(weeksOf(SpreadsheetApp.openById(cur.getId())), oldWeek ? oldWeek.rows : null, notes, cur.getName());
  var from = cur;
  if (!week && oldWeek) { week = oldWeek; from = old; notes.push(cur.getName() + " has no usable week yet - serving " + old.getName() + " " + oldWeek.name); }
  if (!week) return {error: "no week with serving-tank levels in " + cur.getName(), notes: notes};
  var out = {sheet: from.getName(), tab: week.name, updated: from.getLastUpdated().toISOString(), levels: week.rows, notes: notes};
  Logger.log(JSON.stringify(out));
  return out;
}
