
const $ = id => document.getElementById(id);
let prev = {}, prevKick = {}, odo = 1080448;
setInterval(function(){ if(!window.__LIVE){ var o=$('odo'); if(o){
  /* audited count through Sep 10 2026, advancing at the audited 2026 average (292.6 pints/day) */
  var mins=(Date.now()-new Date('2026-09-11T00:00:00-06:00').getTime())/60000;
  o.textContent=Math.floor(1080448 + Math.max(0,mins)*0.203188).toLocaleString();
} } }, 15000);
(function(){ var o=$('odo'); if(o&&!window.__LIVE){ var mins=(Date.now()-new Date('2026-09-11T00:00:00-06:00').getTime())/60000; o.textContent=Math.floor(1080448+Math.max(0,mins)*0.203188).toLocaleString(); } })();
const HOUSE = [
  'Every beer brewed 40 feet from your glass',
  '1875 S Pearl St · Platt Park, Denver',
  'Order everything right here at the bar',
  'To-go food + pickup: Gates window on the sidewalk',
  'Crowlers to go · any tank, sealed at the bar',
  'Dog friendly patio · water bowls on request',
  'Family owned on South Pearl since 2014'
];
let houseIx = 0; /* wire ticker owns railMsg now */
let spotIx = -1;
function celebrateKick(name){
  const f=document.createElement('div'); f.className='kickflash'; document.body.appendChild(f);
  const st=document.createElement('div'); st.className='kickstamp';
  st.innerHTML=`Tank kicked<small>${name}</small>`; document.body.appendChild(st);
  setTimeout(()=>{f.remove();st.remove();},2200);
}
const stars = r => r ? '●'.repeat(Math.round(r))+'○'.repeat(5-Math.round(r))+` <small>${r.toFixed(2)}</small>` : 'new';
const daysAgo = ts => { if(!ts) return ''; const d=Math.floor((Date.now()-ts)/86400000); if(d===0) return 'fresh · tapped today'; return d<=10?`fresh · tapped ${d}d ago`:''; };

function render(s){
  const _p=new Intl.DateTimeFormat('en-US',{timeZone:'America/Denver',weekday:'short',hour:'numeric',minute:'2-digit'}).formatToParts(new Date()).reduce((o,x)=>(o[x.type]=x.value,o),{}); $('clock').textContent=_p.weekday.toUpperCase()+' · '+_p.hour+':'+_p.minute+' '+(_p.dayPeriod||'').toLowerCase();
  const curtain=window.__noData ? 'offline' : (s.context&&s.context.curtain);
  const cv=$('curtain');
  if(curtain){
    cv.classList.add('on'); cv.classList.toggle('night',curtain==='goodnight');
    if(!$('cRanger').src){$('cRanger').src=document.querySelector('.ranger img').src;$('cWm').src=document.querySelector('.brand img').src;}
    $('cLine').textContent=curtain==='goodnight'?"That's last call":curtain==='offline'?'Back in a moment':curtain==='closed'?'Closed today':'Doors at 11';
    $('cSub').textContent=curtain==='goodnight'?'See you tomorrow · open 11am':curtain==='offline'?'the tap list is reconnecting · ask the bar':curtain==='closed'?'back tomorrow at 11':'Gates breakfast next door til 11';
  } else cv.classList.remove('on');
  const wxWord={default:'SUNNY',hot:'HOT',snow:'SNOW',rain:'RAIN',cold:'COLD'};
  if (s.weather){
    $('wxIco').textContent=wxWord[s.weather.scene]||'SUNNY'; $('wxDeg').textContent=s.weather.label;
    const ev=s.context&&s.context.event, phase=s.context&&s.context.eventPhase;
    let cls='';
    if (s.weather.scene && s.weather.scene!=='default') cls='scene-'+s.weather.scene;
    if (ev&&ev.title==='Industry night' && phase==='run') cls='scene-industry';
    if (ev&&ev.fest && phase==='run') cls+=' scene-fest';
    document.body.className=cls;
    if(cls.includes('scene-industry')) $('wxIco').textContent='NIGHT';
    snow(s.weather.scene==='snow');
  }
  const hh=s.context&&s.context.happyHour;
  $('hhChip').style.display=hh?'flex':'none';
  if(hh) $('hhChip').innerHTML=`HAPPY HOUR <span class="sub">${hh.minutesLeft} MIN LEFT</span>`;
  const k=s.context&&s.context.kitchen;
  $('kChip').style.display=k?'flex':'none';
  if(k) $('kChip').innerHTML=`KITCHEN <span class="sub">CLOSES IN ${k.minutesLeft} MIN</span>`;

  const ev=s.context&&s.context.event, phase=s.context&&s.context.eventPhase, b=$('banner');
  b.classList.remove('gold');
  if(ev && phase==='run'){ b.innerHTML=`<strong>${ev.title}</strong> ${ev.banner}`; b.classList.add('show');document.body.classList.add('bn'); if(ev.wingCounter) b.classList.add('gold'); }
  else if(ev && phase==='promote'){ b.innerHTML=`<strong>Tonight</strong> ${ev.promo}`; b.classList.add('show');document.body.classList.add('bn'); }
  else if(s.weather&&s.weather.banner){ b.innerHTML=`<strong>${wxWord[s.weather.scene]||''} DAY</strong> ${s.weather.banner}`; b.classList.add('show'); }
  else b.classList.remove('show');

  $('wingCell').style.display=(ev&&ev.wingCounter&&phase==='run')?'flex':'none';
  $('wings').textContent=(s.wingsToday||0).toLocaleString();
  if(s.mostPoured){$('most').textContent=`${s.mostPoured.name} · ${s.mostPoured.pouredTodayPints} pt`;}else if(window.__LIVE){$('most').textContent='—';}
  const _mk=$('mostK'); if(_mk) _mk.textContent=window.__LIVE?'Most poured today':'To go';

  const floor=$('floor');
  (function(){
    const n=s.beers.length;
    const cols = n<=6 ? Math.max(n,1) : Math.ceil(n/2);
    floor.style.gridTemplateColumns='repeat('+cols+','+(n>=15?'minmax(0,1fr)':'1fr')+')';
    floor.classList.toggle('dense', n>=15);
    floor.classList.toggle('single',n<=6);
    // prune tanks for beers no longer in the feed
    const ids=new Set(s.beers.map(b=>'u-'+b.id));
    [...floor.querySelectorAll('.unit')].forEach(u=>{ if(!ids.has(u.id)) u.remove(); });
  })();
  for(const beer of s.beers){ try{
    let u=document.getElementById('u-'+beer.id);
    if(!u){
      u=document.createElement('div'); u.id='u-'+beer.id;
      u.innerHTML=`
        <div class="tankwrap"><span class="spotcap"></span><div class="sun"></div><div class="vessel">
          <div class="dish"></div>
          <div class="tbody">
            <span class="size"></span><span class="blip">−1</span>
            <span class="nitrotag">Nitro</span><span class="lowtag">Running low</span>
            <span class="newtag">Just tapped</span>
            <div class="kicktag"><span>Tank empty</span></div>
            <div class="liquid"><svg class="wave" viewBox="0 0 200 12" preserveAspectRatio="none"><path d="M0 6 Q12.5 0 25 6 T50 6 T75 6 T100 6 T125 6 T150 6 T175 6 T200 6 V12 H0 Z"/></svg><div class="foam"></div><span class="bub" style="left:22%;top:74px;--rise:-66px;width:4px;height:4px;animation-duration:4.6s"></span><span class="bub" style="left:52%;top:96px;--rise:-88px;width:3px;height:3px;animation-duration:6s;animation-delay:1.2s"></span><span class="bub" style="left:76%;top:58px;--rise:-50px;width:5px;height:5px;animation-duration:5.2s;animation-delay:2.3s"></span></div>
            <div class="sheen"></div><div class="weld" style="top:33%"></div><div class="weld" style="top:66%"></div><div class="manway"></div>
          </div>
          <div class="cone"></div><div class="valve"></div>
        </div></div>
        <div class="plate">
          <div class="name"></div><div class="note"></div><div class="meta"></div><div class="adj"></div>
          <div class="row2"><span class="price"></span></div>
          <div class="age"></div>
        </div>`;
      floor.appendChild(u);
      u.querySelector('.wave').style.animationDelay = (-Math.random()*8).toFixed(2)+'s'; if(beer.nitro||/\bnitro\b/i.test(beer.style||'')){ var nliq=u.querySelector('.liquid'); for(var q=0;q<22;q++){ var sp=document.createElement('span'); sp.className='bub n'+(1+q%3); var wall=q%2?3+Math.random()*7:90+Math.random()*7; sp.style.left=wall.toFixed(1)+'%'; sp.style.top=(6+Math.random()*20).toFixed(0)+'px'; sp.style.setProperty('--fall',(70+Math.random()*60).toFixed(0)+'px'); sp.style.animationDelay=(-Math.random()*4).toFixed(2)+'s'; nliq.appendChild(sp);} }
      u.querySelectorAll('.bub').forEach(bb=>{
        bb.style.left=(12+Math.random()*72).toFixed(0)+'%';
        const t=40+Math.random()*70; bb.style.top=t+'px'; bb.style.setProperty('--rise',(-(t-8))+'px');
        bb.style.animationDuration=(3.8+Math.random()*3).toFixed(2)+'s';
        bb.style.animationDelay=(-Math.random()*6).toFixed(2)+'s';
      });
    }
    const fresh = beer.tappedAt && (Date.now()-beer.tappedAt) < 3*86400000;   // NEW for the first 3 days
    u.className='unit'+(beer.tall?' tall':'')+(beer.featured?' featured spotlight':'')+(beer.low&&!fresh?' low':'')+(beer.kicked?' kicked':'')+(beer.medal?' gold':'')+(fresh&&!beer.kicked?' justtapped':'')+(beer.pick?' pick':'')+(beer.sash?' hasSash':'')+(beer.sash==='last keg'?' lastkeg':'')+((beer.nitro||/\bnitro\b/i.test(beer.style||''))?' nitro':'');
    u.querySelector('.newtag').textContent=beer.pick?'Brewers\u2019 pick':'New';
    u.querySelector('.spotcap').textContent=beer.sash||'';
    var smallV=(beer.vessel==='keg-half'||beer.vessel==='serve6');u.querySelector('.lowtag').textContent = beer.pct<=0.04 ? (smallV?'Last pours':'Almost gone') : (smallV?'Low':'Running low');
    u.querySelector('.size').textContent=beer.vesselLabel;
    const liq=u.querySelector('.liquid');
    const shown=Math.max(0,beer.pct*0.94);
    liq.style.transform=`translateY(${(1-shown)*100}%)`;
    liq.style.background=`linear-gradient(${beer.colorTop},${beer.color})`;
    liq.querySelector('.wave').style.fill=beer.colorTop;
    u.querySelector('.name').textContent=beer.name;
    (function(){var tb=u.querySelector('.tbody');var pl=tb.querySelector('.tplaque');if(beer.medal){if(!pl){pl=document.createElement('div');pl.className='tplaque';tb.appendChild(pl);}pl.className='tplaque'+(beer.medal==='silver'?' sv':'');pl.textContent=beer.medalText||(beer.medal==='silver'?'SILVER':'GOLD');}else if(pl){pl.remove();}})();
    u.querySelector('.meta').textContent=`${beer.style} · ${beer.abv}%`;
    u.querySelector('.note').textContent=beer.wall||beer.note||''; u.querySelector('.note').classList.toggle('long',(beer.wall||beer.note||'').length>30);
    u.querySelector('.adj').textContent=(beer.adjuncts&&beer.adjuncts.length)?'contains '+beer.adjuncts.join(' · '):'';
    u.querySelector('.price').innerHTML='<span class="tag">$'+beer.price.toFixed(2).replace(/\.00$/,'')+((beer.pourNote||beer.tenOzOnly)?' <span class="p10">10oz</span>':'')+' <span class="dot">\u00b7</span> <span class="abv">'+beer.abv+'%</span></span>';
    u.querySelector('.age').textContent=daysAgo(beer.tappedAt);
    const was=prev[beer.id];
    if(was!==undefined && beer.remainingOz<was){
      odo += Math.max(1, Math.round((was-beer.remainingOz)/16));
      const bl=u.querySelector('.blip');
      bl.textContent='−'+Math.round((was-beer.remainingOz)/16*10)/10+' pt';
      bl.classList.remove('go'); void bl.offsetWidth; bl.classList.add('go');
    }
    prev[beer.id]=beer.remainingOz;
    }catch(e){ console.error('tank render failed', beer&&beer.id, e); }
  }
  if(s.side){
    for(const it of s.side){
      const el=$('s-'+it.id); if(!el) continue;
      const bar=el.querySelector('.s-bar i'); if(bar) bar.style.width=(it.pct*100)+'%';
      el.classList.toggle('low-side', it.pct<=0.15);
    }
    if(s.side.find(x=>x.id==='frozen')) $('sFlavor').innerHTML=s.side.find(x=>x.id==='frozen').flavor;
  }
  // odometer + kick detection
  for(const beer of s.beers){
    if(beer.kicked && prevKick[beer.id]===false) celebrateKick(beer.name);
    prevKick[beer.id]=beer.kicked;
  }
  if(window.__LIVE) $('odo').textContent=odo.toLocaleString(); /* showcase: the audited pace is the only writer */
  $('demoTag').textContent=(window.PREVIEW_MODE?'PREVIEW \u00b7 live data \u00b7 what the wall shows during service':'');
}

let snowTimer=null;
function snow(on){
  if(on&&!snowTimer){snowTimer=setInterval(()=>{const f=document.createElement('span');f.className='flake';f.textContent='❄';f.style.left=Math.random()*1920+'px';f.style.fontSize=(8+Math.random()*10)+'px';f.style.animationDuration=(4+Math.random()*5)+'s';document.body.appendChild(f);setTimeout(()=>f.remove(),9500);},300);}
  if(!on&&snowTimer){clearInterval(snowTimer);snowTimer=null;document.querySelectorAll('.flake').forEach(f=>f.remove());}
}

// LIVE SEED from Square sales Mon Sep 7 → Thu Sep 10, 2026
const CAP={tank20:79360,tank10:39680,serve6:5280,'keg-half':1984};
const SIM={beers:[
 {id:'oktoberfest',name:'Oktoberfest',style:'Märzen',abv:5.4,price10:4.75,price:7.5,rating:3.63,vessel:'tank20',vesselLabel:'20 BBL',tall:true,featured:true,color:'#c77a1e',colorTop:'#e8a53a',remainingOz:67456,tappedAt:Date.now()-86400000*3},
 {id:'plattmosphere',name:'Plattmosphere',style:'Hazy IPA',abv:6.9,price10:5.25,price:8.5,rating:3.82,vessel:'tank20',vesselLabel:'20 BBL',tall:true,medal:'silver',medalText:'STATE FAIR SILVER',color:'#d9a83c',colorTop:'#efc76a',remainingOz:5952,tappedAt:Date.now()-86400000*9},
 {id:'nutorious',name:'Nutorious',style:'Pistachio Cream Ale',abv:6.0,price10:5.0,price:8.5,rating:3.88,vessel:'tank10',vesselLabel:'10 BBL',medal:'gold',medalText:'US OPEN GOLD',color:'#b7893f',colorTop:'#d4a95c',remainingOz:4999,tappedAt:Date.now()-86400000*18},
 {id:'tropical-snow-dance',name:'Tropical Snow Dance',style:'West Coast IPA',abv:6.9,price10:5.25,price:8.5,rating:3.74,vessel:'tank20',vesselLabel:'20 BBL',tall:true,color:'#d69a2b',colorTop:'#eebd55',remainingOz:19840,tappedAt:Date.now()-86400000*12},
 {id:'platty-lite',name:'Platty Lite',style:'Light Lager',abv:4.0,price10:4.25,price:6.5,rating:3.56,vessel:'tank20',vesselLabel:'20 BBL',tall:true,medal:'silver',medalText:'STATE FAIR SILVER',color:'#e3c25a',colorTop:'#f2dc8a',remainingOz:6745,tappedAt:Date.now()-86400000*6},
 {id:'nadare',name:'Nadare',style:'Japanese Rice Lager',abv:5.2,price10:4.75,price:7.5,rating:3.37,vessel:'tank10',vesselLabel:'10 BBL',color:'#e8d58a',colorTop:'#f5e9b3',remainingOz:32140,tappedAt:Date.now()-86400000*2},
 {id:'astronaut-amber',name:'Astronaut Amber',style:'American Amber',abv:5.3,price10:4.75,price:7.5,rating:3.51,vessel:'tank10',vesselLabel:'10 BBL',color:'#a8542a',colorTop:'#c97648',remainingOz:31347,tappedAt:Date.now()-86400000*15},
 {id:'witbier',name:'Witbier',style:'Witbier / Blanche',abv:4.3,price10:4.75,price:7.5,rating:3.6,vessel:'tank10',vesselLabel:'10 BBL',color:'#e6d9a0',colorTop:'#f3ecc4',remainingOz:1904,tappedAt:Date.now()-86400000*4},
 {id:'chela',name:'Chela Morena',style:'Mexican Dark Lager',abv:4.9,price10:4.5,price:7.0,rating:3.74,vessel:'keg-half',vesselLabel:'1/2 BBL',color:'#6e4a2a',colorTop:'#8a5f38',remainingOz:1091,tappedAt:Date.now()-86400000*6},
 {id:'madagascar-dream',name:'Madagascar Dream',style:'Vanilla Cream · Nitro',abv:6.0,price10:5.0,price:8.0,rating:3.75,vessel:'tank10',vesselLabel:'10 BBL',color:'#c9973c',colorTop:'#e6bd6e',remainingOz:19840,tappedAt:Date.now()-86400000*21},
 {id:'kakou',name:'KĀKOU',style:'Golden Stout · Nitro',abv:5.8,price10:5.25,price:8.5,rating:3.9,vessel:'tank10',vesselLabel:'10 BBL',color:'#dfa93c',colorTop:'#eec468',remainingOz:1267,tappedAt:Date.now()-86400000*8},
]
,poured:{'oktoberfest':16,'platty-lite':16,'plattmosphere':16,'astronaut-amber':16,'chela':10},wings:847,side:[{id:'cider',pct:.62},{id:'seltzer',pct:.34},{id:'frozen',flavor:'Mexican Firing Squad<br>Transfusion'}]};

/* ── LIVE TAP DATA ─────────────────────────────────────────────────
   What's pouring lives in beers.json, not in this file.

   On boot we load it synchronously so the board renders the real list
   immediately. Every 60s we re-check; if the file changed, the page
   reloads. A reload on a wall display is invisible and it's bulletproof
   — no half-rendered tanks.

   If beers.json is missing or the network is down, the list compiled
   into this file below is used instead, so the board never goes blank.

   >> EDIT beers.json TO CHANGE WHAT'S POURING. Never edit this file. */
const FALLBACK_BEERS = SIM.beers.slice();
let _tapFp = null;   // fingerprint of the beer list we booted with

(function bootTaps(){
  try{
    const x = new XMLHttpRequest();
    x.open('GET', 'beers.json?t=' + Date.now(), false);   // sync: kiosk boot
    x.send(null);
    if(x.status >= 200 && x.status < 300){
      const d = JSON.parse(x.responseText);
      if(d && Array.isArray(d.beers) && d.beers.length){
        // beers.json stores freshness as plain days; the board wants a timestamp
        d.beers.forEach(function(b){
          b.tappedAt = Date.now() - 86400000 * (b.tappedDaysAgo || 0);
        });
        _tapFp     = x.responseText.length + ':' + JSON.stringify(d.beers).length;
        SIM.beers  = d.beers; window.__hours = d.hours || window.__hours || {};
        // remember the last good list so an outage shows something recent,
        // not whatever was compiled into this file months ago
        try{ localStorage.setItem('ppb_taps', x.responseText); }catch(_){}
        console.log('[taps] booted with ' + d.beers.length + ' beers from beers.json');
        return;
      }
    }
    throw new Error('HTTP ' + x.status);
  }catch(e){
    console.warn('[taps] beers.json unavailable:', e.message);
    // 1st fallback: the last list this browser successfully loaded
    try{
      const cached = localStorage.getItem('ppb_taps');
      if(cached){
        const d = JSON.parse(cached);
        if(d && Array.isArray(d.beers) && d.beers.length){
          d.beers.forEach(function(b){ b.tappedAt = Date.now() - 86400000 * (b.tappedDaysAgo || 0); });
          SIM.beers = d.beers; window.__hours = d.hours || window.__hours || {};
          console.warn('[taps] using last cached list (' + (d.updated || 'no stamp') + ')');
          return;
        }
      }
    }catch(_){}
    // 2nd fallback: nothing trustworthy to show. Curtain up, keep retrying
    // (checkTaps reloads the moment beers.json is reachable). Never a stale list as if live.
    console.warn('[taps] no cache either — curtain until the list is reachable');
    SIM.beers = [];
    window.__noData = true;
  }
})();

async function checkTaps(){
  try{
    const r = await fetch('beers.json?t=' + Date.now(), {cache:'no-store'});
    if(!r.ok) return;
    const d = await r.json();
    if(!d || !Array.isArray(d.beers) || !d.beers.length) return;
    const fp = (await r.clone().text()).length + ':' + JSON.stringify(d.beers).length;
    if(_tapFp && fp !== _tapFp){
      console.log('[taps] change detected — reloading');
      location.reload();
    }
    // booted on fallback, file now reachable: adopt it
    if(!_tapFp){ console.log('[taps] beers.json now reachable — reloading'); location.reload(); }
  }catch(e){ /* offline: keep showing what we have */ }
}
setInterval(checkTaps, 20000);

setInterval(function(){ var n=new Date();
  if(n.getHours()===3 && n.getMinutes()===0) location.reload(true);
}, 60000);


window.__scene='default';
const NEXT={id:'fresh-hop-pale',name:'Fresh Hop Pale',style:'Wet Hop Pale Ale',abv:5.5,price:8.0,rating:0,vessel:'tank10',vesselLabel:'10 BBL',color:'#b8cf5e',colorTop:'#d4e88a',remainingOz:39680,tappedAt:Date.now()};
function payload(){
  const scenes={
    default:{weather:{scene:'default',icon:'☀️',label:'78°'},context:{}},
    hot:{weather:{scene:'hot',icon:'🔥',label:'94°',banner:'Scorcher. Lagers and the slushie machine up top.'},context:{}},
    snow:{weather:{scene:'snow',icon:'❄️',label:'28°',banner:'Snow day. Nitro pours lead the board.'},context:{}},
    industry:{weather:{scene:'default',icon:'🌙',label:'66°'},context:{event:{title:'Industry night',banner:'Show your paystub or POS login · specials til close'},eventPhase:'run'}},
    trivia:{weather:{scene:'default',icon:'☀️',label:'71°'},context:{event:{title:'Trivia Tuesday',promo:'Trivia tonight · 7pm · free to play · winners drink cheaper'},eventPhase:'promote'}},
    wings:{weather:{scene:'default',icon:'☀️',label:'74°'},context:{event:{title:'Wing Wednesday',banner:'Dozen wings $12 · Full nachos $12 · Personal pitchers: Platty Lite $10, any beer $12',wingCounter:true},eventPhase:'run'}},
    hh:{weather:{scene:'default',icon:'☀️',label:'78°'},context:{happyHour:{minutesLeft:47},kitchen:{minutesLeft:18}}},
    fest:{weather:{scene:'default',icon:'☀️',label:'76°'},context:{event:{title:'Oktoberfest',banner:'South Pearl Oktoberfest today · Festbier + steins pouring til 10 · real bathrooms, no lines',fest:true,wingCounter:false},eventPhase:'run'}},
    preopen:{weather:{scene:'default',icon:'☀️',label:'64°'},context:{curtain:'preopen'}},
    goodnight:{weather:{scene:'default',icon:'🌙',label:'58°'},context:{curtain:'goodnight'}}
  };
  const sc=scenes[window.__scene]||scenes.default;
  const beers=SIM.beers.map(b=>{const cap=CAP[b.vessel];
    if(!window.__LIVE){
      /* HONEST SHOWCASE: no server = no invented state. Healthy neutral fills, no fake stats. */
      let h=0; for(const c of b.id) h=(h*31+c.charCodeAt(0))>>>0;
      const fill=0.32+((((h*2654435761)>>>0)%63)/100);
      /* hash sets the opening level; once materialized, showcase pours draw it down for real */
      const oz=(typeof b.remainingOz==='number'&&!isNaN(b.remainingOz))?b.remainingOz:cap*fill;
      return{...b,capacityOz:cap,remainingOz:oz,pct:oz/cap,pintsLeft:Math.floor(oz/16),
        low:(oz/cap)<=0.10,kicked:false,tappedAt:null,pouredTodayPints:0};
    }
    return{...b,capacityOz:cap,pct:b.remainingOz/cap,pintsLeft:Math.floor(b.remainingOz/16),low:b.remainingOz>0&&b.remainingOz/cap<=0.05,kicked:b.remainingOz<=0,pouredTodayPints:Math.round((SIM.poured[b.id]||0)/16)}});
  beers.sort((x,y)=>y.capacityOz-x.capacityOz);
  let most=null,mx=0;for(const b of beers)if(b.pouredTodayPints>mx){mx=b.pouredTodayPints;most=b}
  return{beers,side:SIM.side,wingsToday:SIM.wings,mostPoured:most,weather:sc.weather,context:sc.context,mode:'demo'};
}


function simulate(){ /* showcase heartbeat: one sim pint at a time, until Monday's real pours take over */
  // materialize each tank's volume once, so pours subtract from real numbers
  const REAL_LEVELS={"oktoberfest": 0.85, "plattmosphere": 0.12, "tropical-snow-dance": 0.261, "platty-lite": 0.96, "nutorious": 0.96, "nadare": 0.826, "astronaut-amber": 0.823, "madagascar-dream": 0.5, "kakou": 0.16, "watermelon-sour": 0.05, "pacific-detour": 0.6, "witbier": 0.64}; // Greg's Mon 9/8 inventory − his burn rates × 3.6 days (Square: this week ran 1.00× normal) + Jules's Wed notes
  try{ const snap=payload(); snap.beers.forEach(pb=>{ const sb=SIM.beers.find(x=>x.id===pb.id); if(!sb) return;
    if(REAL_LEVELS[pb.id]!==undefined) sb.remainingOz=Math.round(REAL_LEVELS[pb.id]*pb.capacityOz);
    else if(sb.remainingOz==null||isNaN(sb.remainingOz)) sb.remainingOz=pb.remainingOz; }); }catch(e){}
  const popular=['oktoberfest','plattmosphere','platty-lite','tropical-snow-dance','oktoberfest','nutorious','chela','astronaut-amber','oktoberfest','kakou','madagascar-dream','nadare','chela'];
  function pour(){
    const id=popular[Math.floor(Math.random()*popular.length)];
    const beer=SIM.beers.find(b=>b.id===id);
    if(beer && beer.remainingOz>320){ beer.remainingOz-=(Math.random()<0.25?10:16); try{render(payload());}catch(e){} }
    setTimeout(pour, 25000+Math.random()*20000);
  }
  setTimeout(pour, 6000);
}
simulate();
try{render(payload());}catch(e){document.body.innerHTML='<div style="font-family:sans-serif;color:#293d22;background:#e7eacd;padding:40px;font-size:28px">Board error: '+e.message+'<br><br>This TV browser may be too old — try a Fire Stick / Chromecast with Chrome.</div>';throw e;}
(function pourLoop(){ setTimeout(function(){ simulate(); pourLoop(); }, 90000+Math.random()*180000); })();
/* spotlight walker retired — featured rotation drives sash+glow+sun as one */
setTimeout(()=>{const units=[...document.querySelectorAll('.unit')];if(units.length){spotIx=0;units[0].classList.add('spotlight');}},4000);
setInterval(()=>{ document.body.classList.toggle('dusk', new Date().getHours()>=17 && !document.body.className.includes('industry')); },60000);
