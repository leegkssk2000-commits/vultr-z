(function(){
  "use strict";
  var ID = "zel-mission-control-dock-v3";

  function html(){
    return ''+
    '<section id="'+ID+'" data-version="ZEL_MISSION_CONTROL_DOCK_V3_STABLE" data-collapsed="0">'+
      '<div class="zel-mcd-v3-head">'+
        '<div><div class="zel-mcd-v3-kicker">ZEL Mission Control Dock</div><div class="zel-mcd-v3-title">boot · source/proof pending</div></div>'+
        '<div class="zel-mcd-v3-actions"><div class="zel-mcd-v3-state">BOOT</div><button class="zel-mcd-v3-toggle" type="button" data-zmc-toggle="1">fold</button></div>'+
      '</div>'+
      '<div class="zel-mcd-v3-body">'+
        '<div class="zel-mcd-v3-rail">'+
          '<span class="zel-mcd-v3-chip" data-sev="pending"><i class="zel-mcd-v3-dot"></i>truth: loading</span>'+
          '<span class="zel-mcd-v3-chip" data-sev="hold"><i class="zel-mcd-v3-dot"></i>decision: hold</span>'+
          '<span class="zel-mcd-v3-chip" data-sev="pending"><i class="zel-mcd-v3-dot"></i>proof: pending</span>'+
        '</div>'+
        '<div class="zel-mcd-v3-strip">'+
          '<div class="zel-mcd-v3-row"><b>Decision</b><span>initializing · no execution</span></div>'+
          '<div class="zel-mcd-v3-row"><b>Guard</b><span>body-portal stable · no dashboard relocation</span></div>'+
        '</div>'+
        '<div class="zel-mcd-v3-mini">'+
          '<div><label>LIVE</label><strong>read-only</strong></div>'+
          '<div><label>VIRTUAL</label><strong>route pending</strong></div>'+
          '<div><label>TEAM</label><strong>advisor pending</strong></div>'+
        '</div>'+
        '<div class="zel-mcd-v3-foot"><span>Step2 v3 stable portal</span><code>BOOT</code></div>'+
      '</div>'+
    '</section>';
  }

  function measure(){
    try{
      var el = document.getElementById(ID);
      if(!el || !document.documentElement) return;
      var h = Math.ceil(el.getBoundingClientRect().height || 0);
      document.documentElement.style.setProperty("--zel-mcd-v3-h", h + "px");
      if(document.body) document.body.classList.add("zel-mcd-v3-pad");
    }catch(e){}
  }

  function boot(){
    if(!document.body) return;
    if(!document.getElementById(ID)){
      var wrap = document.createElement("div");
      wrap.innerHTML = html();
      document.body.appendChild(wrap.firstElementChild);
    }
    measure();
    setTimeout(measure, 50);
    setTimeout(measure, 250);
    window.__ZEL_MISSION_CONTROL_DOCK_V3_PREBOOT__ = {inserted:true, ts:Date.now()};
  }

  if(document.body) boot();
  else document.addEventListener("DOMContentLoaded", boot, {once:true});
})();
