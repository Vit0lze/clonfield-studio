// Anchors a floating panel to its trigger. The panel is moved to <body> while open: `.dock` has backdrop-filter, which
// would make `position: fixed` resolve against the dock instead of the viewport.
// Placement: prefer above the trigger (the dock sits at the bottom), flip below when there is more room there, clamp to
// the viewport on X, cap max-height to the room that really exists, and become a bottom sheet on narrow screens.

const SHEET_MAX = 600;

export function anchorPopover(trigger, panel, { gap = 10, margin = 8, prefer = "top", bottomReserve = 0 } = {}) {
  const home = panel.parentNode;
  document.body.append(panel);
  panel.classList.add("anchored");

  const place = () => {
    if (panel.hidden) return;
    const vw = document.documentElement.clientWidth, vh = window.innerHeight;
    const rect = trigger.getBoundingClientRect();
    panel.style.maxHeight = ""; panel.style.width = "";
    if (vw <= SHEET_MAX) {
      // bottom sheet, above the mobile navigation
      const rail = document.querySelector(".rail")?.getBoundingClientRect();
      const reserve = bottomReserve || (rail && rail.top > vh / 2 ? Math.ceil(vh - rail.top) + margin : margin);
      panel.dataset.placement = "sheet";
      Object.assign(panel.style, { left: `${margin}px`, right: `${margin}px`, width: "auto", top: "auto", bottom: `${reserve}px`, maxHeight: `${Math.max(180, vh - reserve - 56)}px` });
      return;
    }
    const above = rect.top - gap - margin, below = vh - rect.bottom - gap - margin;
    const natural = panel.scrollHeight + 2;
    const top = prefer === "top" ? above >= Math.min(natural, 320) || above >= below : !(below >= Math.min(natural, 320) || below >= above);
    const room = Math.max(160, top ? above : below);
    const width = panel.offsetWidth || 380;
    const left = Math.min(Math.max(rect.left, margin), Math.max(margin, vw - width - margin));
    panel.dataset.placement = top ? "top" : "bottom";
    Object.assign(panel.style, { left: `${left}px`, right: "auto", maxHeight: `${room}px` });
    if (top) Object.assign(panel.style, { top: "auto", bottom: `${vh - rect.top + gap}px` });
    else Object.assign(panel.style, { bottom: "auto", top: `${rect.bottom + gap}px` });
  };

  const onMove = () => place();
  window.addEventListener("resize", onMove);
  window.addEventListener("scroll", onMove, true);
  window.visualViewport?.addEventListener("resize", onMove);
  const observer = typeof ResizeObserver === "function" ? new ResizeObserver(onMove) : null;
  observer?.observe(panel);
  place();

  return {
    place,
    destroy() {
      window.removeEventListener("resize", onMove);
      window.removeEventListener("scroll", onMove, true);
      window.visualViewport?.removeEventListener("resize", onMove);
      observer?.disconnect();
      panel.classList.remove("anchored");
      for (const key of ["left", "right", "top", "bottom", "maxHeight", "width"]) panel.style[key] = "";
      delete panel.dataset.placement;
      if (home) home.append(panel);
    }
  };
}
