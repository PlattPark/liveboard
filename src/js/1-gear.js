
document.getElementById('gearBtn').onclick=()=>{const p=document.getElementById('panel');p.style.display=p.style.display==='none'?'flex':'none'};
   // the scene picker is a demo tool: never on the wall. Add ?demo to the URL to get it back.
   if(!/[?&]demo\b/.test(location.search)){ document.getElementById('gearBtn').parentElement.style.display='none'; }
document.querySelectorAll('.sc[data-s]').forEach(b=>b.onclick=()=>{window.__scene=b.dataset.s;render(payload());});
document.getElementById('kickBtn').onclick=()=>{const w=SIM.beers.find(b=>b.id==='chela');if(w)w.remainingOz=17;};
