/* WINTER DRESSING: turns the snow on for the season and off again by itself (Denver dates).
   Snow and icicles run FROM..TO; the lights under the Also Pouring card run FROM..LIGHTS_TO, then the card gets icicles.
   ?holiday on the URL previews it any day (?holiday=snow for the after-New-Year's look); ?noholiday hides it.
   Art and rules live in css/4-holiday.css. */
(function(){
  var FROM=1127, LIGHTS_TO=101, TO=229;   // month*100+day, inclusive: Nov 27 -> Jan 1 with lights, then snow only through the end of February
  function today(){
    try{ var p=new Intl.DateTimeFormat('en-US',{timeZone:'America/Denver',month:'numeric',day:'numeric'}).formatToParts(new Date()).reduce(function(o,x){o[x.type]=x.value;return o;},{}); return (+p.month)*100+(+p.day); }
    catch(e){ var n=new Date(); return (n.getMonth()+1)*100+n.getDate(); }
  }
  function mode(){   // '' = off, 'lights' = snow + lights, 'snow' = snow only
    var q=location.search||'';
    if(/[?&]noholiday\b/.test(q)) return '';
    var m=/[?&]holiday(?:=([a-z]*))?(?:&|$)/.exec(q);
    if(m) return m[1]==='snow' ? 'snow' : 'lights';
    var d=today();
    if(d>=FROM || d<=LIGHTS_TO) return 'lights';
    return d<=TO ? 'snow' : '';
  }
  function frame(){
    // the icicles are drawn for the board's 16:9 frame; keep them lined up with it on any screen.
    // The curtains (doors at 11, last call, closed) wear it too: an edge on the ice when the curtain is cream, and the snow on the ranger's hat.
    try{
      var root=document.documentElement; if(!root.classList.contains('holiday')) return;
      var r=document.body.getBoundingClientRect(), w=r.width/0.965;
      if(w>0){ root.style.setProperty('--holw', w.toFixed(1)+'px'); root.style.setProperty('--holx', (r.left-(w-r.width)/2).toFixed(1)+'px'); }
      var cur=document.getElementById('curtain'), up=!!cur && document.body.classList.contains('curtained');
      if(up && !cur.classList.contains('night')) root.classList.add('holcurtday'); else root.classList.remove('holcurtday');
      var img=document.getElementById('cRanger'), hat=document.getElementById('holhat');
      if(up && img && img.offsetHeight>0){
        if(!hat){ hat=document.createElement('i'); hat.id='holhat'; hat.setAttribute('aria-hidden','true'); cur.appendChild(hat); }
        hat.style.left=img.offsetLeft+'px'; hat.style.top=img.offsetTop+'px'; hat.style.width=img.offsetWidth+'px'; hat.style.height=img.offsetHeight+'px';
      } else if(hat){ hat.parentNode.removeChild(hat); }
    }catch(e){}
  }
  function apply(){
    try{
      var md=mode(), root=document.documentElement, el=document.getElementById('holdrift');
      if(md){
        root.classList.add('holiday');
        if(md==='lights') root.classList.add('hollights'); else root.classList.remove('hollights');
        if(!el){ el=document.createElement('div'); el.id='holdrift'; el.setAttribute('aria-hidden','true'); document.body.insertBefore(el, document.body.firstChild); }
        frame();
      } else {
        root.classList.remove('holiday'); root.classList.remove('hollights'); root.classList.remove('holcurtday');
        if(el) el.parentNode.removeChild(el);
        var hat=document.getElementById('holhat'); if(hat) hat.parentNode.removeChild(hat);
      }
    }catch(e){}
  }
  window.addEventListener('resize', frame);
  try{ new MutationObserver(frame).observe(document.body,{attributes:true,attributeFilter:['class','style']}); }catch(e){}
  apply(); setInterval(apply, 600000);
})();
