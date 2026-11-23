/* THE RANGER'S SEAT (Nov 23 2026): he stands on the rail, over the QR code, whatever the Also Pouring card says.
   He sits in the page flow under that card and was put on the rail by a fixed nudge (css/3-fit.css). So every line
   the crew added to the card or took off it moved him: 46px down into the rail on Oct 20, 16px up off it on Nov 20
   when two lines got shorter - and the wall failed its own check for three days.
   Now the nudge is measured: boots on the rail's top edge, centred over the QR cell, at any screen size, with or
   without the band. If the card ever grows down into his space he gets smaller instead of standing in it.
   The fixed nudge in 3-fit.css stays as the starting point. */
(function(){
  var FEET=3;              // design px his boots sink into the rail's top edge (the tagline under them stays behind the rail)
  var AIR=8, LIGHTS=56;    // design px kept clear under the Also Pouring card; more while the holiday lights hang there
  var MIN=0.6;             // never smaller than this share of his full size
  function px(n){ return (Math.round(n*10)/10)+'px'; }
  function seat(){
    try{
      var r=document.querySelector('.ranger'); if(!r) return;
      var img=r.querySelector('img'), rail=document.querySelector('.rail'), q=document.querySelector('.rail .qrcell'), side=document.getElementById('side');
      if(!img || !rail || !q || !img.naturalWidth || !r.offsetWidth) return;
      if(document.body.classList.contains('curtained')) return;          // behind the curtain: nothing to seat
      if(!r.__w0) r.__w0=r.offsetWidth;                                  // his full width, before anything here touches it
      var kb=document.body.getBoundingClientRect().width/(document.body.offsetWidth||1920);   // screen px per design px
      var k=r.getBoundingClientRect().width/r.offsetWidth;               // screen px per px of his own (the stage is scaled too)
      if(!(k>0) || !(kb>0)) return;
      var L=rail.getBoundingClientRect(), Q=q.getBoundingClientRect(), qx=(Q.left+Q.right)/2;
      var boots=L.top+FEET*kb;
      var f=1;
      if(side){
        var S=side.getBoundingClientRect(), half=r.__w0*k/2;
        if(qx+half>S.left && qx-half<S.right){                           // he stands under the card: fit the room it leaves
          var lights=document.documentElement.classList.contains('hollights');
          var room=boots-(S.bottom+(lights?LIGHTS:AIR)*kb), full=r.__w0*k*img.naturalHeight/img.naturalWidth;
          f=Math.max(MIN, Math.min(1, room/full));
        }
      }
      var w=Math.round(r.__w0*f*10)/10;
      if(Math.abs(r.offsetWidth-w)>0.5) r.style.width=px(w);
      var R=img.getBoundingClientRect();                                 // measured after any resize
      var m=/matrix\(([^)]+)\)/.exec(getComputedStyle(r).transform||''), p=m?m[1].split(',').map(parseFloat):[1,0,0,1,0,0];
      var tx=p[4]+(qx-(R.left+R.right)/2)/k, ty=p[5]+(boots-R.bottom)/k;
      if(Math.abs(tx-p[4])>0.25 || Math.abs(ty-p[5])>0.25) r.style.transform='translate('+px(tx)+','+px(ty)+')';
    }catch(e){}
  }
  window.__seatRanger=seat;
  var t=0; function soon(){ clearTimeout(t); t=setTimeout(seat,60); }
  var _r=render;
  render=function(s){ var out=_r(s); seat(); return out; };
  window.addEventListener('resize',soon);
  window.addEventListener('load',seat);
  try{ var im=document.querySelector('.ranger img'); if(im) im.addEventListener('load',seat); }catch(e){}
  try{ if(document.fonts && document.fonts.ready) document.fonts.ready.then(seat); }catch(e){}
  try{ new MutationObserver(soon).observe(document.getElementById('side'),{childList:true,subtree:true,characterData:true}); }catch(e){}
  try{ new MutationObserver(soon).observe(document.body,{attributes:true,attributeFilter:['class']});
       new MutationObserver(soon).observe(document.documentElement,{attributes:true,attributeFilter:['class']}); }catch(e){}
  seat(); setTimeout(seat,300); setTimeout(seat,1500); setInterval(seat,5000);
})();
