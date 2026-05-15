(function(){
  "use strict";
  var ID = "zel-step2-mission-rail-c";
  function html(){
    return ''+
    '<section id="'+ID+'" data-version="ZEL_STEP2_MISSION_RAIL_C_APPBOUND" data-expanded="0" data-owner="body-portal">'+
      '<div class="z2c-shell">'+
        '<div class="z2c-head">'+
          '<div><span class="z2c-kicker">ZEL Mission Rail</span><strong class="z2c-title" data-z2c-title>boot · source/proof pending</strong></div>'+
          '<span class="z2c-state" data-z2c-state>BOOT</span>'+
          '<button class="z2c-btn" type="button" data-z2c-toggle>open</button>'+
        '</div>'+
        '<div class="z2c-body">'+
          '<div class="z2c-rail">'+
            '<span class="z2c-chip" data-sev="pending" data-z2c-chip="truth">truth: loading</span>'+
            '<span class="z2c-chip" data-sev="hold" data-z2c-chip="decision">decision: hold</span>'+
            '<span class="z2c-chip" data-sev="pending" data-z2c-chip="proof">proof: pending</span>'+
          '</div>'+
          '<div class="z2c-grid">'+
            '<div class="z2c-row"><b>Decision</b><span data-z2c-decision>initializing · no execution</span></div>'+
            '<div class="z2c-row"><b>Guard</b><span data-z2c-guard>app-bound body portal · no full width</span></div>'+
            '<div class="z2c-row"><b>Missing</b><span data-z2c-missing>unbound</span></div>'+
          '</div>'+
          '<div class="z2c-foot"><span data-z2c-foot>Step2 Rail C · app-bound</span><code data-z2c-time>BOOT</code></div>'+
        '</div>'+
      '</div>'+
    '</section>';
  }
  function boot(){
    if(!document.body) return;
    if(!document.getElementById(ID)){
      var div = document.createElement('div');
      div.innerHTML = html();
      document.body.appendChild(div.firstElementChild);
    }
    window.__ZEL_STEP2_MISSION_RAIL_C_PREBOOT__ = {inserted:true, ts:Date.now()};
  }
  if(document.body) boot();
  else document.addEventListener('DOMContentLoaded', boot, {once:true});
})();
