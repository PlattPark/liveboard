
(function(){
  function fit(){
    var b=document.body;
    var H=1080;                       // the design is 1920x1080 — never measure, never guess
    b.style.height='1080px';
    var s=Math.min(window.innerWidth/1920, window.innerHeight/H)*0.965; /* TV overscan safe margin */
    var x=(window.innerWidth-1920*s)/2, y=(window.innerHeight-H*s)/2;
    b.style.transform='translate('+x+'px,'+y+'px) scale('+s+')';
  }
  window.addEventListener('resize',fit);
  window.addEventListener('load',fit);
  var _mo=new MutationObserver(function(){clearTimeout(window.__ft);window.__ft=setTimeout(fit,120);});
  _mo.observe(document.getElementById('banner'),{attributes:true,childList:true});
  fit(); setTimeout(fit,300); setTimeout(fit,1500); setInterval(fit,5000);
})();
