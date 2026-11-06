/* 4-fittext.js - Platt Park live board (Nov 2026)
   Why this exists: the wall's type sizes used to be hand-picked numbers per layout (5 / 6 / 8 across). Every time a
   beer was added or removed across a layout boundary - or the TV's Windows Chrome drew text a little wider than the
   test browser - something overflowed. This measures every card ON THE DEVICE and shrinks what doesn't fit, so the
   CSS sizes are a ceiling, never a promise.

   Rules, per card:
     name   one line; shrink to a floor. If it still doesn't fit (very long guest names), allow two balanced lines.
     style  (the .note line) one line if possible, shrink to a floor, then wrap.
     taste  at most two lines; shrink to a floor.
     price  the tag never wider than its card: shrink it, and if it still doesn't fit drop the ABV, then the "10oz" label.
   Runs whenever the beer list redraws, on resize, and once fonts have loaded. window.__fitText() runs it on demand. */
(function () {
  var floor = document.getElementById('floor');
  if (!floor) return;
  var busy = false, queued = false;

  function px(el) { return parseFloat(getComputedStyle(el).fontSize) || 16; }
  function lineH(el) { var lh = parseFloat(getComputedStyle(el).lineHeight); return isNaN(lh) ? px(el) * 1.15 : lh; }
  // Measure the TEXT, not the box: a name/line box always fills its column, so its own width says nothing.
  // Ranges report screen pixels (after the board's scaling), so the card is measured the same way.
  function textW(el) { var r = document.createRange(); r.selectNodeContents(el); var w = 0; var rs = r.getClientRects();
    for (var i = 0; i < rs.length; i++) w = Math.max(w, rs[i].width); return w; }
  var curRoomPx = 0;
  function fitsWidth(el) { return textW(el) <= curRoomPx + 0.5; }
  function lines(el) { return Math.round(el.scrollHeight / lineH(el)); }

  function reset(el) { if (el) { el.style.fontSize = ''; el.style.whiteSpace = ''; el.style.letterSpacing = ''; } }

  function shrinkOneLine(el, room, floorPx) {
    el.style.whiteSpace = 'nowrap';
    var s = px(el), guard = 80;
    while (!fitsWidth(el) && s > floorPx && guard--) { s -= 0.5; el.style.fontSize = s + 'px'; }
    return fitsWidth(el);
  }
  function shrinkLines(el, room, maxLines, floorPx) {
    el.style.whiteSpace = 'normal';
    var s = px(el), guard = 80;
    while ((lines(el) > maxLines || !fitsWidth(el)) && s > floorPx && guard--) { s -= 0.5; el.style.fontSize = s + 'px'; }
  }

  function fitTag(price, room) {
    var tag = price.querySelector('.tag') || price;
    tag.style.transform = ''; tag.style.transformOrigin = '';
    tag.querySelectorAll('.abv, .dot, .p10').forEach(function (e) { e.style.display = ''; });
    function natural() { return tag.offsetWidth; }          // layout width in board pixels, unaffected by transforms
    if (natural() <= room) return;
    var abv = tag.querySelector('.abv');                     // 1) drop the ABV (it's on the QR menu)
    if (abv && natural() * 0.8 > room) {
      abv.style.display = 'none';
      var d = abv.previousElementSibling; if (d && d.classList.contains('dot')) d.style.display = 'none';
    }
    if (natural() * 0.78 > room) tag.querySelectorAll('.p10').forEach(function (e) { e.style.display = 'none'; });   // 2) then the "10oz" word
    var s = Math.min(1, room / natural());                   // 3) scale whatever is left to fit exactly
    if (s < 1) { tag.style.transform = 'scale(' + Math.max(0.6, s).toFixed(3) + ')'; tag.style.transformOrigin = 'center bottom'; }
  }

  function fitCard(u, dense) {
    var plate = u.querySelector('.plate'); if (!plate) return;
    var room = plate.clientWidth - 4;                       // board pixels, for the price tag
    if (room <= 0) return;
    var pr = plate.getBoundingClientRect();
    curRoomPx = pr.width - 4 * (pr.width / plate.clientWidth);   // the same room in screen pixels, for text
    var name = plate.querySelector('.name'), note = plate.querySelector('.note'), taste = plate.querySelector('.taste'), price = plate.querySelector('.price');
    [name, note, taste].forEach(reset);
    if (name && name.textContent.trim()) {
      if (!shrinkOneLine(name, room, dense ? 13 : 21)) { reset(name); shrinkLines(name, room, 2, dense ? 12 : 17); name.style.height = 'auto'; }
      else name.style.height = '';
    }
    if (note && note.textContent.trim()) {
      if (!shrinkOneLine(note, room, dense ? 11 : 15)) { reset(note); shrinkLines(note, room, 2, dense ? 10 : 14); }
    }
    if (taste && taste.textContent.trim()) shrinkLines(taste, room, 2, dense ? 10 : 13);
    if (price) fitTag(price, room);
  }

  function fitAll() {
    if (busy) { queued = true; return; }
    busy = true;
    try {
      var dense = floor.classList.contains('dense');
      floor.querySelectorAll('.unit').forEach(function (u) { fitCard(u, dense); });
    } catch (e) { /* never let fitting break the board */ }
    busy = false;
    if (queued) { queued = false; requestAnimationFrame(fitAll); }
  }

  var pending = 0;
  function schedule() { if (pending) return; pending = requestAnimationFrame(function () { pending = 0; fitAll(); }); }

  new MutationObserver(function (muts) {
    for (var i = 0; i < muts.length; i++) {                 // ignore our own style tweaks
      if (muts[i].type !== 'attributes') { schedule(); return; }
    }
  }).observe(floor, { childList: true, subtree: true, characterData: true });
  window.addEventListener('resize', schedule);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(schedule);
  setTimeout(schedule, 300); setInterval(schedule, 60000);  // belt and braces: refit once a minute
  window.__fitText = fitAll;
})();
