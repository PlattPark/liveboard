/* THE CARD (Nov 18 2026): one plain card in the tank space the wall isn't using.
   An odd number of beers leaves one cell of the grid empty - 11 beers, 12 spaces. That space can carry the one
   thing the house wants a guest to know this month (gift cards in December, the mug club, NYE tickets).

   It is data, not code. beers.json:
     "card": { "title": "Gift cards",
               "lines": ["Buy $50, get a $10 bonus card", "Buy $100, get a $25 bonus card"],
               "foot":  "Through Dec 24 · bonus cards good Jan 2 – Mar 31",
               "wire":  "gift cards · buy $50, get a $10 bonus card · buy $100, get $25 · through Dec 24",
               "from": "2026-11-27", "until": "2026-12-24" }
   No card in the file, outside its dates, an even number of beers (no free space), fifteen or more beers (cells too
   small), or the doors closed = nothing is drawn. The ticker line follows the same dates and needs no free space.
   Dates are Denver days, inclusive. Amounts ($50) are set in the price face automatically. */
(function(){
  function today(){
    try{ return new Intl.DateTimeFormat('en-CA',{timeZone:'America/Denver',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date()); }
    catch(e){ return new Date().toISOString().slice(0,10); }
  }
  function live(){
    var c=window.__card;
    if(!c || typeof c!=='object' || !c.title) return null;
    var d=today();
    if(c.from && d<String(c.from)) return null;
    if(c.until && d>String(c.until)) return null;
    return c;
  }
  window.__cardLive=live;
  function esc(s){ return String(s==null?'':s).replace(/[&<>"']/g,function(ch){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]; }); }
  function money(s,tag){ return esc(s).replace(/\$\d+(?:\.\d\d)?/g,'<'+tag+'>$&</'+tag+'>'); }

  function place(s){
    var floor=document.getElementById('floor'); if(!floor) return;
    var el=document.getElementById('promoCard');
    var c=live(), n=((s&&s.beers)||[]).length;
    var room = n>=7 && n<15 && n%2===1;                     // two rows, one cell left over, cells still card-sized
    if(!c || !room || document.body.classList.contains('curtained')){ if(el) el.remove(); return; }
    var html='<div class="promo-h">'+esc(c.title)+'</div>'
      +(Array.isArray(c.lines)?c.lines:[]).slice(0,3).map(function(l){ return '<div class="promo-l">'+money(l,'b')+'</div>'; }).join('')
      +(c.foot?'<div class="promo-f">'+esc(c.foot)+'</div>':'');
    if(!el){ el=document.createElement('div'); el.id='promoCard'; }
    el.className='promo'+(n>=13?' tight':'');
    if(el.__html!==html){ el.innerHTML=html; el.__html=html; }
    if(floor.lastElementChild!==el) floor.appendChild(el);   // always the last cell, whatever order the tanks arrived in
  }
  function wire(){
    var c=live(), line=(c&&c.wire)?money(c.wire,'em'):'';
    if(line!==(window.__cardWire||'')){ window.__cardWire=line; if(window.__buildWire) window.__buildWire(); }
  }
  var _r=render;
  render=function(s){ var out=_r(s); try{ place(s); wire(); }catch(e){ console.warn('[card]',e); } return out; };
})();
