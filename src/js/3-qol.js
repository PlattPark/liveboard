
window.__BUILD='2026-09-11.2845';
(function(){
  var T0=Date.now();
  function checkUpdate(){
    // ask only for headers - GitHub Pages sends an ETag - and reload when it changes.
    // ~200 bytes per check instead of the whole page.
    try{ fetch(location.href,{method:'HEAD',cache:'no-store'}).then(r=>{
      var tag=r.headers.get('etag')||r.headers.get('last-modified'); if(!tag) return;
      if(!window.__pageTag){ window.__pageTag=tag; return; }
      if(tag!==window.__pageTag){ location.reload(); }
    }).catch(function(){}); }catch(e){}
    if(Date.now()-T0>20*3600*1000) location.reload();   // never run a page longer than a day
  }
  setInterval(checkUpdate,5*60*1000);
})();
// ---- real weather via Open-Meteo (keyless), hourly ----
(function(){
  var deg=document.getElementById('wxDeg'), ico=document.getElementById('wxIco');
  var WMO={0:'SUNNY',1:'SUNNY',2:'PARTLY CLOUDY',3:'CLOUDY',45:'FOGGY',48:'FOGGY',51:'DRIZZLE',53:'DRIZZLE',55:'DRIZZLE',61:'RAIN',63:'RAIN',65:'RAIN',71:'SNOW',73:'SNOW',75:'SNOW',80:'SHOWERS',81:'SHOWERS',82:'SHOWERS',95:'STORMS',96:'STORMS',99:'STORMS'};
  function wordFor(code){ var w=WMO[code]||''; return (code===0||code===1)&&document.body.classList.contains('night')?'CLEAR':w; }   // no 'sunny' after sunset
  window.__wxWord=wordFor; setInterval(function(){ if(window.__wx) ico.textContent=wordFor(window.__wx.code); },5000);
  function wx(){
    try{
      fetch('https://api.open-meteo.com/v1/forecast?latitude=39.685&longitude=-104.980&current=temperature_2m,weather_code&daily=sunset&timezone=America%2FDenver&temperature_unit=fahrenheit')
        .then(r=>r.json()).then(d=>{
          if(d&&d.current){
            deg.textContent=Math.round(d.current.temperature_2m)+'°';
            ico.textContent=wordFor(d.current.weather_code);
            window.__wx={temp:d.current.temperature_2m,code:d.current.weather_code,word:WMO[d.current.weather_code]||''};
            try{ var ss=d.daily&&d.daily.sunset&&d.daily.sunset[0]; if(ss){ var hm=ss.slice(11,16).split(':'); window.__sunset=parseInt(hm[0],10)+parseInt(hm[1],10)/60; } }catch(e){}
            if(window.__autoScene) window.__autoScene();   // let the scene react (snow, heat)
          }
        }).catch(function(){});
    }catch(e){}
  }
  wx(); setInterval(wx,60*60*1000);
})();

/* ---- FEST DAY OVERRIDE: Sept 12 2026, by Denver calendar ---- */
function festOverride(s){
  try{
    const d=new Intl.DateTimeFormat('en-CA',{timeZone:'America/Denver'}).format(new Date());
    if(d==='2026-09-12' || new URLSearchParams(location.search).has('fest')){
      s.context=s.context||{};
      s.context.event={title:'South Pearl Oktoberfest',banner:'South Pearl Oktoberfest today \u00b7 Festbier + steins pouring til 10 \u00b7 real bathrooms, no lines'};
      s.context.eventPhase='run';
    }
  }catch(e){}
  return s;
}
(function(){ const _r=render; render=function(s){ return _r(festOverride(s)); }; })();

/* ---- AUTO SCENES: the clock, the calendar and live weather pick the scene.
   Nothing invented: hours and specials are the real ones, weather is Open-Meteo.
   A preview button still wins while someone is demoing (window.__scene != default). ---- */
(function(){
  const OPEN=10.5; const closeFor=function(dow,date){ var H=(window.__hours||{}); if((H.late||[]).indexOf(date)>=0) return 24; return (dow==='Fri'||dow==='Sat') ? 24 : 22; };   // 10:30 for setup, doors 11; Fri/Sat till midnight, else 10pm
  const PREVIEW=/[?&]preview\b/.test(location.search); window.PREVIEW_MODE=PREVIEW;                  // business day, America/Denver, every day
  const SNOW=[71,73,75,77,85,86], HOT_F=90; // WMO snow codes; "hot" from 90°F
  function denver(){
    // Denver wall clock that survives old browsers: hour12:false is honoured almost
    // everywhere; if a browser still hands back 12-hour parts, the dayPeriod fixes it;
    // if Intl fails outright, the device itself lives in Denver, so use its clock.
    var now=new Date(), dow='', h=NaN, m=NaN;
    try{
      var p=new Intl.DateTimeFormat('en-US',{timeZone:'America/Denver',weekday:'short',hour:'numeric',minute:'2-digit',hour12:false})
        .formatToParts(now).reduce(function(o,x){o[x.type]=x.value;return o;},{});
      dow=p.weekday; h=parseInt(p.hour,10); m=parseInt(p.minute,10);
      if(h===24) h=0;
      if(p.dayPeriod){ var pm=/p/i.test(p.dayPeriod); if(pm&&h<12) h+=12; if(!pm&&h===12) h=0; }
    }catch(e){}
    if(!(h>=0&&h<24)||!(m>=0&&m<60)){ h=now.getHours(); m=now.getMinutes(); }
    if(!dow) dow=['Sun','Mon','Tue','Wed','Thu','Fri','Sat'][now.getDay()];
    var dt=''; try{ var q=new Intl.DateTimeFormat('en-CA',{timeZone:'America/Denver',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(now).reduce(function(o,x){o[x.type]=x.value;return o;},{}); dt=q.year+'-'+q.month+'-'+q.day; }catch(e){ dt=now.toISOString().slice(0,10); }
    return {dow:dow, t:h+m/60, date:dt};
  }
  function auto(){
    const {dow,t,date}=denver(), ctx={}, w=window.__wx; const H=(window.__hours||{});
    if(!PREVIEW){ if((H.closed||[]).indexOf(date)>=0) ctx.curtain='closed'; else if(t<OPEN) ctx.curtain=(t<1.5?'goodnight':'preopen'); else if(t>=closeFor(dow,date)) ctx.curtain='goodnight'; }   // ?preview: crew check, never the curtain
    if(!ctx.curtain){
      if(dow==='Mon'){ ctx.event={title:'Industry night',banner:'Everything, all day, food included \u00b7 clock-out slip, schedule or work shirt gets you in'}; ctx.eventPhase='run'; }
      else if(dow==='Tue'){ const live=(t>=19&&t<21);
        ctx.event={title:'Trivia Tuesday',promo:'Team Trivia tonight \u00b7 7pm',banner:'Team Trivia \u00b7 happening now'}; ctx.eventPhase=live?'run':'promote'; }
      else if(dow==='Wed'){ ctx.event={title:'Wing Wednesday',banner:'A dozen wings for $12 \u00b7 every other day it\u2019s seven',wingCounter:false}; ctx.eventPhase='run'; }
    }
    let scene='default', banner;
    if(w && SNOW.includes(w.code)){ scene='snow'; banner='Snow day. Nitro pours lead the board.'; }
    else if(w && w.temp>=HOT_F){ scene='hot'; banner='Scorcher. Lagers and frozen cocktails up top.'; }
    return {weather:{scene,icon:'',label:w?Math.round(w.temp)+'\u00b0':'',banner},context:ctx};
  }
  const _r=render;
  render=function(s){
    if(window.__scene==='default'){ const a=auto(); s.weather=a.weather; s.context=Object.assign({},s.context,a.context); }
    const out=_r(s);
    window.__hours = s.hours || window.__hours || {};
    if(window.__shade) window.__shade();       // render() rewrites body.className; put the night level back
    document.body.classList.toggle('curtained', document.getElementById('curtain').classList.contains('on'));
    (function(){ var h=document.getElementById('hero'); if(!h) return; var pk=(s.beers||[]).find(function(b){return b.pick;}); var n=(s.beers||[]).length;
      var mk=function(c,t){ var e=document.createElement('div'); e.className=c; e.textContent=t; return e; };
      h.textContent='';
      var title='What\u2019s pouring';                                                  // the wall's title (it pairs with the side panel's "Also pouring"); the pick is a subline, never the headline
      h.appendChild(mk('hk','On tap today \u00b7 '+n+' brewed here')); h.appendChild(mk('hn',title));
      h.appendChild(mk('hs', pk ? 'Brewers\u2019 pick \u00b7 '+pk.name : 'brewed 40 feet from your glass'));   // "house beers" means the promo pours at Platt Park - never use it for the whole list
      h.classList.add('on'); })();
    // the real weather always wins over any scene's placeholder text
    if(window.__wx){ const d=$('wxDeg'), i=$('wxIco');
      if(d) d.textContent=Math.round(window.__wx.temp)+'\u00b0';
      if(i && !/scene-/.test(document.body.className)) i.textContent=(window.__wxWord?window.__wxWord(window.__wx.code):window.__wx.word)||i.textContent; }
    return out;
  };
  let sig='';
  window.__autoScene=function(force){
    if(window.__scene!=='default') return;
    const a=JSON.stringify(auto());
    if(force || a!==sig){ sig=a; try{ render(payload()); }catch(e){} }
  };
  // night dimming: the cream board is a lamp in a dark bar. From sunset (Open-Meteo;
  // 7pm if unknown) step the shade down an hour at a time; lift it again at open.
  // the moon as it is tonight: phase from the mean synodic month (new moon 2000-01-06 18:14 UTC), drawn lit-side-correct
  function moonPhase(){ var p=((Date.now()/864e5-10962.76)/29.530588853)%1; return p<0?p+1:p; }   // 0 new, .5 full, waxing below .5
  function moonSVG(p){ var r=9,c=10,k=Math.cos(2*Math.PI*p),rx=Math.abs(k)*r,wax=p<0.5,gib=Math.abs(p-0.5)<0.25;
    var d='M'+c+','+(c-r)+'A'+r+','+r+' 0 1,'+(wax?1:0)+' '+c+','+(c+r)+'A'+rx.toFixed(2)+','+r+' 0 1,'+((wax?1:0)^(gib?0:1))+' '+c+','+(c-r)+'Z';
    return '<svg viewBox="0 0 20 20"><circle cx="'+c+'" cy="'+c+'" r="'+r+'" fill="#e7eacd" fill-opacity=".22"/><path d="'+d+'" fill="#e7eacd" fill-opacity=".92"/></svg>'; }
  function moonWord(p){ var d=Math.abs(p-0.5)*29.53; return d<0.5?'full moon tonight':(p<0.017||p>0.983)?'new moon tonight \u00b7 darkest sky of the month':''; }
  var _lastSky='';
  function shade(){
    const {t}=denver(); const sunset=window.__sunset||19;
    const night = (t>=sunset+0.5) || (!PREVIEW && (t<OPEN || ((window.__hours||{}).closed||[]).indexOf(denver().date)>=0));      // half an hour after sunset until doors
    const dusk = !night && t>=sunset-0.75 && t<sunset+0.5;                                                                        // golden hour: the paper warms 45 min before sunset
    document.body.classList.toggle('night', night); document.body.classList.toggle('dusk', dusk);
    document.documentElement.style.background = (night || document.body.classList.contains('scene-industry')) ? '#1c2818' : dusk ? '#e9dfb6' : '#e7eacd';
    const p=moonPhase(), lit=(1-Math.cos(2*Math.PI*p))/2;                                                                          // moonlit: the night map brightens with the real moon
    document.documentElement.style.setProperty('--moonlit',(0.42+0.2*lit).toFixed(2));
    const mo=$('moon'); if(mo && night && !mo.dataset.p){ mo.innerHTML=moonSVG(p); mo.dataset.p='1'; }
    const hh=Math.floor(sunset), mm=Math.round((sunset-hh)*60), when=(hh>12?hh-12:hh)+':'+(mm<10?'0':'')+mm;
    let sky=''; if(!night && t>=sunset-1 && t<sunset) sky='sunset at '+when+' tonight'; else if(t>=sunset && t<sunset+2) sky='sun went down at '+when;
    const mw=night?moonWord(p):''; if(mw) sky=sky?sky+' \u00b7 '+mw:mw;
    if(sky!==_lastSky){ _lastSky=sky; window.__skyWire=sky; if(window.__buildWire) window.__buildWire(); }
  }
  window.__shade=shade; shade(); setInterval(shade, 60000);
  if(window.__noData){ document.body.classList.add('curtained'); }
  window.__autoScene(true);                 // apply now (boot render ran before this hook)
  setInterval(function(){ window.__autoScene(); }, 60000);
})();

(function(){ function isFest(){ try{ if(new URLSearchParams(location.search).has('fest')) return true; return new Intl.DateTimeFormat('en-CA',{timeZone:'America/Denver'}).format(new Date())==='2026-09-12'; }catch(e){ return false; } }
  function enforce(){ if(!isFest()) return; var b=$('banner'); if(b && !b.classList.contains('show')){ b.innerHTML='<strong>South Pearl Oktoberfest</strong> Festbier + steins pouring til 10 \u00b7 real bathrooms, no lines'; b.classList.add('show','gold');document.body.classList.add('bn'); } }
  enforce(); setInterval(enforce, 15000); })();

/* ---- SHOWCASE LIFE: motion and rotation, every word true ---- */
(function(){
  if(window.__SHOWLIFE) return; window.__SHOWLIFE=true;
  // spotlight is stationary: the sun lives on the fest beer, full stop
  window.__rotNow=function(){};

  // rail cell cycles true facts
  const DAY=[
    ['Weekend','breakfast at Gates \u00b7 8am'],
    ['Tonight','industry night \u00b7 MNF on the big screen'],
    ['Tonight','trivia 7pm \u00b7 bring a team'],
    ['Tonight','wing wednesday \u00b7 dozen for $12'],
    ['To go','crowlers from $12 \u00b7 filled at the bar'],
    ['To go','crowlers from $12 \u00b7 filled at the bar'],
    ['Weekend','breakfast at Gates \u00b7 sat + sun 8am']
  ];
  const FACTS=[DAY[new Date().getDay()]];
  let fi=0;
  function rotFact(){ if(window.__LIVE) return;
    const k=$('mostK'), v=$('most');
    if(k&&v){ const f=FACTS[fi%FACTS.length]; k.textContent=f[0]; v.textContent=f[1]; fi++; }
  }
  rotFact(); /*boot*/
  window.__factNow=rotFact;
  rotFact(); setInterval(rotFact,18000);
})();

/* ---- THE WIRE: ticker of true things. Showcase = lore + real facts; live = real pours too. ---- */
(function(){
  /* beer medals on the wire come from beers.json (medals with show "wall" or "menu"), so a
     line only runs while that beer is pouring and never names a medal we didn't win.
     "GABF silver our very first year" is the brewery's own line and stays, Gump's or not. */
  const WIRE_COMP={'us open':'US Open','state fair':'Colorado State Fair','gabf':'GABF','world beer cup':'World Beer Cup','brewers cup':'Colorado Brewers Cup'};
  const MEDAL_LINES=(function(){ try{
    const esc=t=>String(t).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
    const rank=l=>({gold:3,silver:2,bronze:1})[l]||0, comp=c=>WIRE_COMP[String(c||'').toLowerCase()]||String(c||'');
    const beers=(typeof SIM!=='undefined'&&SIM.beers)||[], groups=new Map(), perBeer=[];
    beers.forEach(b=>{
      const ms=(typeof medalsOf==='function'?medalsOf(b):[]).filter(m=>(m.show||'wall')!=='site');
      if(!ms.length) return;
      ms.forEach(m=>{ const k=[String(m.comp||'').toLowerCase(),m.level,m.year||''].join('|'); if(!groups.has(k)) groups.set(k,{m,names:[]}); groups.get(k).names.push(b.name); });
      perBeer.push({b,ms});
    });
    const out=[], used=new Set();
    groups.forEach(g=>{ if(g.names.length<2) return;          // one medal, several beers: one shared line
      out.push(esc(g.names.slice(0,-1).join(', ')+' + '+g.names.slice(-1))+' \u00b7 '+esc(comp(g.m.comp))+' <em>'+esc(String(g.m.level).toUpperCase())+'</em>'+(g.m.year?' '+g.m.year:'')+' \u00b7 '+(g.names.length===2?'both':'all')+' pouring now');
      g.names.forEach(n=>used.add(n+'|'+String(g.m.comp||'').toLowerCase())); });
    perBeer.forEach(({b,ms})=>{                              // one beer, its medals by competition: "Nutorious \u00b7 US Open GOLD 2026 \u00b7 bronze 2025"
      const byComp=new Map(); ms.forEach(m=>{ const k=String(m.comp||'').toLowerCase(); if(!byComp.has(k)) byComp.set(k,[]); byComp.get(k).push(m); });
      byComp.forEach((list,k)=>{ if(used.has(b.name+'|'+k)) return;
        list.sort((a,c)=>(c.year||0)-(a.year||0)||rank(c.level)-rank(a.level));
        const top=list[0], rest=list.slice(1).map(m=>esc(m.level)+(m.year?' '+m.year:''));
        out.push(esc(b.name)+' \u00b7 '+esc(comp(top.comp))+' <em>'+esc(String(top.level).toUpperCase())+'</em>'+(top.year?' '+top.year:'')+(rest.length?' \u00b7 '+rest.join(' \u00b7 '):'')); });
    });
    return out;
  }catch(e){ console.warn('wire medals', e); return []; } })();
  const LORE=[

    'every beer pours in a 10oz too \u00b7 just ask', 'this room sold antique cash registers \u2014 then the tanks moved in',
    "GABF <em>silver</em> our very first year \u2014 Gump's Vienna Lager",
    'trivia tuesdays 7pm \u00b7 wing wednesdays \u00b7 dozen for <em>$12</em>',
    'industry night mondays \u00b7 Monday Night Football on the big screen',
    ...MEDAL_LINES,
    '\u201cBest Sandwich Shop in Denver\u201d \u2014 Mom',
    'bagged ice <em>$3</em> \u00b7 fill your cooler <em>$5</em> \u00b7 yes, really',
    '5280 put the Italian Job on its best-sandwiches-in-Denver list',
    'Westword Best of Denver 2020 \u00b7 best walk-up beer + sandwiches',
    'kids eat too \u00b7 dino nuggs or a Vienna dog \u00b7 goldfish, apple slices, capri-sun',

    'K\u0100KOU pours like a stout, drinks like a vacation',
    'pint <em>#1,000,000</em> poured Thanksgiving 2025 \u00b7 now pouring million two',
    'crowlers to go \u00b7 from <em>$12</em> \u00b7 sealed at the bar',
    'Gates Deli out the sidewalk window \u00b7 sandwiches worth the walk'
  ];
  let liveItems=[];
  window.__wirePour=function(name){ liveItems.unshift('<span class="wi pour">just poured \u00b7 '+name+'</span>'); liveItems=liveItems.slice(0,6); buildWire(); };
  function wireItems(){ return [...liveItems, ...(window.__skyWire?['<span class="wi">'+window.__skyWire+'</span>']:[]), ...(window.__mapWire?['<span class="wi">'+window.__mapWire+'</span>']:[]), ...LORE.map(t=>'<span class="wi">'+t+'</span>')]; }
  function buildWire(){
    const el=$('railMsg'); if(!el) return;
    const items=wireItems(); if(!items.length) return;
    const half=items.join('');
    el.innerHTML='<span class="wireStrip">'+half+half+'</span>';
    const strip=el.querySelector('.wireStrip');
    requestAnimationFrame(function(){
      const w=strip.scrollWidth/2;
      strip.style.setProperty('--wd',(w/52).toFixed(1)+'s');
    });
    const k=$('railK'); if(k) k.textContent='The wire';
  }
  buildWire();
  window.__buildWire=buildWire; window.__wireNext=function(){}; /* seasonal map: the field behind the tanks follows the real seasons (solstice/equinox, Denver); beers.json `map` overrides; maps/maps.json carries each map's file + wire line */ (function(){ var MAPS={winter:'abasin',spring:'platte',summer:'lostcreek',fall:'ouray'}; function season(){ var p; try{ p=new Intl.DateTimeFormat('en-US',{timeZone:'America/Denver',month:'numeric',day:'numeric'}).formatToParts(new Date()).reduce(function(o,x){o[x.type]=x.value;return o;},{}); }catch(e){ var n=new Date(); p={month:n.getMonth()+1,day:n.getDate()}; } var m=+p.month, d=+p.day; if((m===12&&d>=21)||m<3||(m===3&&d<20)) return 'winter'; if(m<6||(m===6&&d<21)) return 'spring'; if(m<9||(m===9&&d<22)) return 'summer'; return 'fall'; } var current=''; function apply(){ var key=(window.__mapOverride||'').replace(/[^a-z]/g,'')||MAPS[season()]; if(key===current) return; var x=new XMLHttpRequest(); x.open('GET','maps/maps.json?t='+Date.now(),true); x.onload=function(){ try{ var mp=JSON.parse(x.responseText); var e=mp[key]||mp[MAPS[season()]]; if(!e) return; current=key; document.documentElement.style.setProperty('--map','url("'+e.file+'")'); window.__mapWire=e.wire; buildWire(); }catch(err){} }; x.onerror=function(){}; x.send(); } window.__applyMap=apply; window.__season=season; apply(); setInterval(apply,3600000); })();
})();



/* split-flap pint counter (Solari tiles): #odo stays the only data source - the audited pace and Square pours write it there;
   this just mirrors it. Only a digit that actually changed folds: old top half drops, new bottom half rises, staggered right-to-left.
   If the text ever changes shape (more digits) the tiles are rebuilt. If anything here fails, #odo is un-hidden and shows plain. */
(function(){
  var host=$('odoFlap'), o=$('odo'); if(!host||!o) return;
  var shown='', busy=false;
  function half(cls,d){ var h=document.createElement('div'); h.className='h '+cls; var s=document.createElement('span'); s.textContent=d; h.appendChild(s); return h; }
  function tile(d){ var f=document.createElement('div'); f.className='fl'; f.appendChild(half('t st',d)); f.appendChild(half('b st',d)); f.setAttribute('data-d',d); return f; }
  function build(txt){
    host.innerHTML='';
    for(var i=0;i<txt.length;i++){ var c=txt.charAt(i);
      if(c>='0'&&c<='9') host.appendChild(tile(c));
      else { var s=document.createElement('span'); s.className='sep'; s.textContent=c; host.appendChild(s); } }
    shown=txt; host.classList.add('on'); o.classList.add('hid');
  }
  function settle(f){ var was=f.getAttribute('data-d'); var go=f.querySelectorAll('.go'); for(var i=0;i<go.length;i++) go[i].parentNode.removeChild(go[i]);
    var st=f.querySelectorAll('.st'); if(st.length===2){ st[0].firstChild.textContent=was; st[1].firstChild.textContent=was; } }
  function flip(f,d,delay){
    settle(f);
    var was=f.getAttribute('data-d'); if(was===d) return;
    var st=f.querySelectorAll('.st'); st[0].firstChild.textContent=d;   /* static top already shows the new digit, behind the falling flap */
    var t=half('t go',was), b=half('b go',d);
    t.style.setProperty('--d',delay.toFixed(2)+'s'); b.style.setProperty('--d',delay.toFixed(2)+'s');
    f.appendChild(t); f.appendChild(b); f.setAttribute('data-d',d);
    var done=false; function fin(){ if(done) return; done=true; settle(f); }
    b.addEventListener('animationend',fin); setTimeout(fin, 2600+delay*1000);
  }
  function sync(){
    var txt=o.textContent||''; if(txt===shown||!txt) return;
    if(!shown||txt.length!==shown.length){ build(txt); return; }
    var tiles=host.querySelectorAll('.fl'), digits=[], i;
    for(i=0;i<txt.length;i++){ var c=txt.charAt(i); if(c>='0'&&c<='9') digits.push(c); else if(shown.charAt(i)!==c){ build(txt); return; } }
    if(digits.length!==tiles.length){ build(txt); return; }
    var n=0;
    for(i=digits.length-1;i>=0;i--){ if(tiles[i].getAttribute('data-d')!==digits[i]){ flip(tiles[i],digits[i],n*0.07); n++; } }
    shown=txt;
  }
  try{ build(o.textContent||''); }catch(e){ o.classList.remove('hid'); host.classList.remove('on'); return; }
  setInterval(function(){ try{ sync(); }catch(e){ o.classList.remove('hid'); host.classList.remove('on'); } }, 400);
})();
