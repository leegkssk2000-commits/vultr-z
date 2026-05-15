(function(){
  "use strict";
  var ID = "zel-mission-control-dock-v2";
  function html(){
    return '<section id="'+ID+'" class="zel-mcd-v2" data-step="2" data-version="ZEL_MISSION_CONTROL_DOCK_V2_INSTANT" data-phase="instant">'+
      '<div class="zel-mcd-head">'+
        '<div><div class="zel-mcd-kicker">ZEL Mission Control Dock</div><div class="zel-mcd-title">boot · source/proof pending</div></div>'+
        '<div class="zel-mcd-state">BOOT</div>'+
      '</div>'+
      '<div class="zel-mcd-rail">'+
        '<span class="zel-mcd-chip" data-sev="pending"><i class="zel-mcd-dot"></i>truth: loading</span>'+
        '<span class="zel-mcd-chip" data-sev="hold"><i class="zel-mcd-dot"></i>decision: hold</span>'+
        '<span class="zel-mcd-chip" data-sev="pending"><i class="zel-mcd-dot"></i>proof: pending</span>'+
      '</div>'+
      '<div class="zel-mcd-strip">'+
        '<div class="zel-mcd-row"><b>Decision</b><span>initializing · no execution</span></div>'+
        '<div class="zel-mcd-row"><b>Guard</b><span>waiting for dashboard truth state</span></div>'+
      '</div>'+
      '<div class="zel-mcd-mini">'+
        '<div><label>LIVE</label><strong>read-only</strong></div>'+
        '<div><label>VIRTUAL</label><strong>route pending</strong></div>'+
        '<div><label>TEAM</label><strong>advisor pending</strong></div>'+
      '</div>'+
      '<div class="zel-mcd-foot"><span>Step2 instant shell</span><code>BOOT</code></div>'+
    '</section>';
  }
  function boot(){
    if(document.getElementById(ID)) return;
    var wrap = document.createElement("div");
    wrap.innerHTML = html();
    document.body.appendChild(wrap.firstElementChild);
    window.__ZEL_MISSION_CONTROL_DOCK_V2_PREBOOT__ = {inserted:true, ts:Date.now()};
  }
  if(document.body) boot();
  else document.addEventListener("DOMContentLoaded", boot, {once:true});
})();
