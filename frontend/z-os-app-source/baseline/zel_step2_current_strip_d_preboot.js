(function(){
  "use strict";

  var OLD_IDS = [
    "zel-mission-control-dock-v1",
    "zel-mission-control-dock-v2",
    "zel-mission-control-dock-v3",
    "zel-step2-mission-control-rebuild-a",
    "zel-step2-mission-rail-b",
    "zel-step2-mission-rail-c"
  ];

  function killOld(){
    try {
      OLD_IDS.forEach(function(id){
        document.querySelectorAll("#" + id).forEach(function(el){ el.remove(); });
      });
      document.querySelectorAll(".zel-step2-mission-rail-b,.zel-step2-mission-rail-c,[class*='zel-step2-mission-rail'],[id^='zel-step2-mission-rail'],[id^='zel-mission-control-dock'],[id*='mission-control-rebuild']").forEach(function(el){ el.remove(); });
      if (document.body) {
        document.body.classList.remove("zel-step2-dock-pad");
        document.body.classList.remove("zel-mission-rail-pad");
      }
      if (document.documentElement) {
        document.documentElement.style.removeProperty("--zel-step2-dock-h");
        document.documentElement.style.removeProperty("--zel-step2-rail-h");
      }
      window.__ZEL_STEP2_CURRENT_STRIP_D_PREBOOT__ = {oldFloatingRemoved: true, ts: Date.now()};
    } catch(e) {
      window.__ZEL_STEP2_CURRENT_STRIP_D_PREBOOT__ = {oldFloatingRemoved: false, error: String(e), ts: Date.now()};
    }
  }

  if (document.body) killOld();
  else document.addEventListener("DOMContentLoaded", killOld, {once:true});
})();
