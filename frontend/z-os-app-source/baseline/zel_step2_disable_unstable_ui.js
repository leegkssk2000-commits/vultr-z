(() => {
  "use strict";

  const VERSION = "ZEL_STEP2_DISABLE_UNSTABLE_UI";
  const IDS = [
    "zel-mission-control-dock-v1",
    "zel-mission-control-dock-v2",
    "zel-mission-control-dock-v3",
    "zel-step2-mission-control-rebuild-a",
    "zel-step2-mission-rail-b",
    "zel-step2-mission-rail-c",
    "zel-step2-current-strip-d"
  ];

  const PREFIX_SELECTORS = [
    '[id^="zel-mission-control-dock-"]',
    '[id^="zel-step2-mission-control-"]',
    '[id^="zel-step2-mission-rail-"]',
    '[id^="zel-step2-current-strip-"]'
  ];

  function kill() {
    let removed = 0;

    for (const id of IDS) {
      document.querySelectorAll("#" + CSS.escape(id)).forEach(el => {
        el.remove();
        removed += 1;
      });
    }

    for (const sel of PREFIX_SELECTORS) {
      document.querySelectorAll(sel).forEach(el => {
        el.remove();
        removed += 1;
      });
    }

    try {
      document.body.classList.remove(
        "zel-step2-dock-pad",
        "zel-mcd-v3-pad",
        "zel-mission-rail-pad",
        "zel-step2-rail-pad"
      );
      document.documentElement.style.removeProperty("--zel-step2-dock-h");
      document.documentElement.style.removeProperty("--zel-mcd-v3-h");
      document.documentElement.style.removeProperty("--zel-step2-rail-h");
    } catch (_) {}

    window.__ZEL_STEP2_DISABLED__ = {
      version: VERSION,
      disabled: true,
      removed,
      ui: "none",
      reason: "unstable mission rail/current strip removed",
      ts: Date.now()
    };
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", kill, { once: true });
  } else {
    kill();
  }

  setInterval(kill, 1000);
})();
