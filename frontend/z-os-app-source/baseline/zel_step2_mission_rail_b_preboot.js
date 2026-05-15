(function(){
  "use strict";
  var ID = "zel-step2-mission-rail-b";
  function html(){
    return ''+
    '<section id="'+ID+'" data-version="ZEL_STEP2_MISSION_RAIL_B_FIX1" data-expanded="0" data-owner="body-portal">'+
      '<div class="z2b-shell">'+
        '<div class="z2b-top">'+
          '<div class="z2b-main"><div class="z2b-kicker">ZEL Mission Rail</div><div class="z2b-title" data-z2b-title>boot · hold · proof pending</div></div>'+
          '<div class="z2b-right"><div class="z2b-state" data-z2b-state>BOOT</div><button class="z2b-btn" type="button" data-z2b-toggle>open</button></div>'+
        '</div>'+
        '<div class="z2b-body">'+
          '<div class="z2b-rail">'+
            '<span class="z2b-chip" data-sev="pending" data-z2b-chip="truth"><i class="z2b-dot"></i><span>truth: loading</span></span>'+
            '<span class="z2b-chip" data-sev="hold" data-z2b-chip="decision"><i class="z2b-dot"></i><span>decision: hold</span></span>'+
            '<span class="z2b-chip" data-sev="pending" data-z2b-chip="proof"><i class="z2b-dot"></i><span>proof: pending</span></span>'+
          '</div>'+
          '<div class="z2b-grid">'+
            '<div class="z2b-row"><b>Decision</b><span data-z2b-decision>initializing · no execution</span></div>'+
            '<div class="z2b-row"><b>Guard</b><span data-z2b-guard>compact rail · no app relocation</span></div>'+
            '<div class="z2b-row"><b>Missing</b><span data-z2b-missing>unbound</span></div>'+
          '</div>'+
          '<div class="z2b-foot"><span>Step2 Mission Rail B fix1</span><code data-z2b-time>BOOT</code></div>'+
        '</div>'+
      '</div>'+
    '</section>';
  }
  function boot(){
    if(!document.body) return;
    var el = document.getElementById(ID);
    if(!el){
      var div = document.createElement("div");
      div.innerHTML = html();
      el = div.firstElementChild;
      document.body.appendChild(el);
    } else if(el.parentElement !== document.body) {
      document.body.appendChild(el);
    }
    window.__ZEL_STEP2_MISSION_RAIL_B_PREBOOT__ = {inserted:true,parent:el.parentElement && el.parentElement.tagName,ts:Date.now()};
  }
  if(document.body) boot();
  else document.addEventListener("DOMContentLoaded", boot, {once:true});
})();
