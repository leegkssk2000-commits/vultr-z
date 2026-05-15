(function(){
  "use strict";
  var ID = "zel-step2-mission-control-rebuild-a";

  function shell(){
    return ''+
    '<section id="'+ID+'" data-version="ZEL_STEP2_MISSION_CONTROL_REBUILD_A" data-collapsed="0" data-owner="body-portal">'+
      '<div class="z2-shell">'+
        '<div class="z2-head">'+
          '<div><div class="z2-kicker">ZEL Mission Control Dock</div><div class="z2-title" data-z2-title>boot · source/proof pending</div></div>'+
          '<div class="z2-actions"><div class="z2-state" data-z2-state>BOOT</div><button class="z2-btn" type="button" data-z2-toggle>fold</button></div>'+
        '</div>'+
        '<div class="z2-body">'+
          '<div class="z2-rail">'+
            '<span class="z2-chip" data-sev="pending" data-z2-chip="truth"><i class="z2-dot"></i><span>truth: loading</span></span>'+
            '<span class="z2-chip" data-sev="hold" data-z2-chip="decision"><i class="z2-dot"></i><span>decision: hold</span></span>'+
            '<span class="z2-chip" data-sev="pending" data-z2-chip="proof"><i class="z2-dot"></i><span>proof: pending</span></span>'+
          '</div>'+
          '<div class="z2-grid">'+
            '<div class="z2-row"><b>Decision</b><span data-z2-decision>initializing · no execution</span></div>'+
            '<div class="z2-row"><b>Guard</b><span data-z2-guard>stable body portal · no app relocation</span></div>'+
            '<div class="z2-row"><b>Missing</b><span data-z2-missing>unbound</span></div>'+
          '</div>'+
          '<div class="z2-mini">'+
            '<div><label>LIVE</label><strong data-z2-live>read-only / no execution</strong></div>'+
            '<div><label>VIRTUAL</label><strong data-z2-virtual>route pending</strong></div>'+
            '<div><label>TEAM</label><strong data-z2-team>advisor pending</strong></div>'+
          '</div>'+
          '<div class="z2-foot"><span data-z2-foot>Step2 rebuild A · stable</span><code data-z2-time>BOOT</code></div>'+
        '</div>'+
      '</div>'+
    '</section>';
  }

  function measure(){
    try{
      var el = document.getElementById(ID);
      var h = el ? Math.ceil(el.getBoundingClientRect().height || 0) : 0;
      document.documentElement.style.setProperty("--zel-step2-dock-h", h + "px");
      document.body.classList.add("zel-step2-dock-pad");
    }catch(e){}
  }

  function boot(){
    if(!document.body) return;
    var el = document.getElementById(ID);
    if(!el){
      var div = document.createElement("div");
      div.innerHTML = shell();
      el = div.firstElementChild;
      document.body.appendChild(el);
    } else if(el.parentElement !== document.body) {
      document.body.appendChild(el);
    }
    measure();
    setTimeout(measure, 30);
    setTimeout(measure, 200);
    window.__ZEL_STEP2_REBUILD_A_PREBOOT__ = {inserted: true, parent: el.parentElement && el.parentElement.tagName, ts: Date.now()};
  }

  if(document.body) boot();
  else document.addEventListener("DOMContentLoaded", boot, {once:true});
})();
