/**
 * Pure DOM builders, crisp inline SVG icon registry, progress ring, 12-week heatmap,
 * toast manager, and accessible modal/sheet helper.
 *
 * Security: user strings are ALWAYS rendered via textContent (never innerHTML).
 */

import {
  clampPercent,
  computeStreak,
  formatCompactCount,
  formatInt,
  formatIsoDate,
  pluralize,
} from "./format.js";

const SVG_NS = "http://www.w3.org/2000/svg";

export function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "className") {
      node.className = value;
    } else if (key === "textContent") {
      node.textContent = String(value);
    } else if (key === "dataset" && typeof value === "object") {
      for (const [dk, dv] of Object.entries(value)) {
        if (dv !== undefined && dv !== null) node.dataset[dk] = String(dv);
      }
    } else if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key === "checked" || key === "disabled" || key === "selected" || key === "hidden" || key === "required" || key === "readOnly") {
      node[key] = Boolean(value);
    } else if (key === "value") {
      node.value = String(value);
    } else {
      node.setAttribute(key, value === true ? "" : String(value));
    }
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function svgEl(tag, attrs = {}, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    el.setAttribute(k, String(v));
  }
  for (const c of children) {
    if (c) el.append(c);
  }
  return el;
}

const ICON_PATHS = {
  cockpit: [
    ["rect", { x: 3, y: 3, width: 7, height: 9, rx: 1.5 }],
    ["rect", { x: 14, y: 3, width: 7, height: 5, rx: 1.5 }],
    ["rect", { x: 14, y: 12, width: 7, height: 9, rx: 1.5 }],
    ["rect", { x: 3, y: 16, width: 7, height: 5, rx: 1.5 }],
  ],
  focus: [
    ["polygon", { points: "6 4 20 12 6 20 6 4" }],
  ],
  create: [
    ["path", { d: "M12 5v14" }],
    ["path", { d: "M5 12h14" }],
  ],
  errors: [
    ["rect", { x: 3, y: 4, width: 5, height: 16, rx: 1 }],
    ["rect", { x: 10, y: 4, width: 5, height: 11, rx: 1 }],
    ["rect", { x: 17, y: 4, width: 4, height: 14, rx: 1 }],
  ],
  analytics: [
    ["path", { d: "M3 3v18h18" }],
    ["path", { d: "M7 15l4-4 3 3 5-6" }],
  ],
  search: [
    ["circle", { cx: 11, cy: 11, r: 7 }],
    ["path", { d: "M21 21l-4.35-4.35" }],
  ],
  sun: [
    ["circle", { cx: 12, cy: 12, r: 4 }],
    ["path", { d: "M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" }],
  ],
  moon: [
    ["path", { d: "M21 12.79A9 9 0 1 1 11.21 3a7 7 0 0 0 9.79 9.79z" }],
  ],
  "arrow-left": [
    ["path", { d: "M19 12H5" }],
    ["path", { d: "M12 19l-7-7 7-7" }],
  ],
  x: [
    ["path", { d: "M18 6L6 18" }],
    ["path", { d: "M6 6l12 12" }],
  ],
  check: [
    ["path", { d: "M20 6L9 17l-5-5" }],
  ],
  trash: [
    ["path", { d: "M3 6h18" }],
    ["path", { d: "M8 6V4h8v2" }],
    ["path", { d: "M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" }],
  ],
  edit: [
    ["path", { d: "M12 20h9" }],
    ["path", { d: "M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z" }],
  ],
  sparkles: [
    ["path", { d: "M12 3l1.9 5.8L20 11l-6.1 2.2L12 19l-1.9-5.8L4 11l6.1-2.2L12 3z" }],
  ],
  volume: [
    ["polygon", { points: "11 5 6 9 2 9 2 15 6 15 11 19 11 5" }],
    ["path", { d: "M15.54 8.46a5 5 0 0 1 0 7.07" }],
    ["path", { d: "M19.07 4.93a10 10 0 0 1 0 14.14" }],
  ],
  refresh: [
    ["path", { d: "M21 12a9 9 0 1 1-2.64-6.36" }],
    ["path", { d: "M21 3v6h-6" }],
  ],
  download: [
    ["path", { d: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" }],
    ["path", { d: "M7 10l5 5 5-5" }],
    ["path", { d: "M12 15V3" }],
  ],
  flask: [
    ["path", { d: "M10 2v7.31l-5.2 8.69A2 2 0 0 0 6.5 21h11a2 2 0 0 0 1.7-3L14 9.31V2" }],
    ["path", { d: "M8.5 2h7" }],
    ["path", { d: "M7 16h10" }],
  ],
  alert: [
    ["circle", { cx: 12, cy: 12, r: 9 }],
    ["path", { d: "M12 8v4" }],
    ["path", { d: "M12 16h.01" }],
  ],
  flame: [
    ["path", { d: "M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z" }],
  ],
  layers: [
    ["path", { d: "M12 2L2 7l10 5 10-5-10-5z" }],
    ["path", { d: "M2 17l10 5 10-5" }],
    ["path", { d: "M2 12l10 5 10-5" }],
  ],
  external: [
    ["path", { d: "M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" }],
    ["path", { d: "M15 3h6v6" }],
    ["path", { d: "M10 14L21 3" }],
  ],
};

export function createIcon(name, size = 16) {
  const shapes = ICON_PATHS[name] || ICON_PATHS.alert;
  return svgEl(
    "svg",
    {
      width: size,
      height: size,
      viewBox: "0 0 24 24",
      fill: "none",
      stroke: "currentColor",
      "stroke-width": 1.85,
      "stroke-linecap": "round",
      "stroke-linejoin": "round",
      "aria-hidden": "true",
    },
    ...shapes.map(([tag, attrs]) => svgEl(tag, attrs))
  );
}

export function hydrateIcons(root = document) {
  root.querySelectorAll("[data-icon]").forEach((slot) => {
    const iconName = slot.getAttribute("data-icon");
    const size = Number(slot.getAttribute("data-icon-size") || 16);
    slot.replaceChildren(createIcon(iconName, size));
  });
}

/**
 * Renders cloze prompt safely without innerHTML, highlighting the `____` blank.
 */
export function renderPromptText(text, kind) {
  const container = h("span", { dir: "auto" });
  if (kind !== "cloze" || !text.includes("____")) {
    container.textContent = text;
    return container;
  }
  const parts = text.split(/(_{4,})/);
  for (const part of parts) {
    if (/^_{4,}$/.test(part)) {
      container.append(h("span", { className: "cloze-blank", textContent: "espacio" }));
    } else if (part) {
      container.append(document.createTextNode(part));
    }
  }
  return container;
}

/**
 * Session Progress Ring (SVG) with tabular percentage and honest empty handling.
 */
export function createProgressRing({ completed = 0, remaining = 0, size = 112 }) {
  const total = completed + remaining;
  const pct = total > 0 ? Math.round(clampPercent(completed, total)) : 0;
  const strokeWidth = 8;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = total > 0 ? circumference * (1 - pct / 100) : circumference;

  const svg = svgEl(
    "svg",
    {
      width: size,
      height: size,
      viewBox: `0 0 ${size} ${size}`,
      class: "progress-ring-svg",
      "aria-hidden": "true",
    },
    svgEl("circle", {
      class: "progress-ring-track",
      cx: size / 2,
      cy: size / 2,
      r: radius,
      "stroke-width": strokeWidth,
      fill: "none",
    }),
    svgEl("circle", {
      class: "progress-ring-fill",
      cx: size / 2,
      cy: size / 2,
      r: radius,
      "stroke-width": strokeWidth,
      fill: "none",
      "stroke-dasharray": circumference.toFixed(2),
      "stroke-dashoffset": offset.toFixed(2),
      "stroke-linecap": "round",
      transform: `rotate(-90 ${size / 2} ${size / 2})`,
    })
  );

  const label = total > 0 ? `${pct}%` : "—";
  const sub = total > 0 ? `${formatInt(completed)}/${formatInt(total)}` : "Sin meta";

  return h(
    "div",
    {
      className: "progress-ring",
      role: "progressbar",
      "aria-label": "Progreso de la sesión de hoy",
      "aria-valuemin": "0",
      "aria-valuemax": "100",
      "aria-valuenow": String(pct),
    },
    svg,
    h(
      "div",
      { className: "progress-ring-center" },
      h("span", { className: "progress-ring-value tabular", textContent: label }),
      h("span", { className: "progress-ring-sub tabular", textContent: sub })
    )
  );
}

function heatLevel(count) {
  if (!count || count <= 0) return 0;
  if (count <= 2) return 1;
  if (count <= 5) return 2;
  if (count <= 10) return 3;
  return 4;
}

/**
 * 12-Week Activity Heatmap (84 days) derived from real /analytics/learning data.
 * Never fabricates data: when total === 0, renders an explicitly labeled empty grid.
 */
export function createHeatmapCard({
  dateKeys,
  counts,
  loading = false,
  error = "",
  isDemo = false,
  onRetry,
}) {
  const totalReviews = dateKeys.reduce((acc, k) => acc + (counts[k] || 0), 0);
  const { current: streak, activeDays } = computeStreak(dateKeys, counts);

  const latestKey = dateKeys[dateKeys.length - 1];
  const latestCount = latestKey ? counts[latestKey] || 0 : 0;
  const readout = h("span", {
    className: "heatmap-readout tabular",
    textContent:
      latestKey && latestCount > 0
        ? `Hoy (${formatIsoDate(latestKey)}): ${pluralize(latestCount, "repaso", "repasos")}`
        : "Toca o pasa sobre un día para ver su detalle",
  });

  const header = h(
    "div",
    { className: "panel-header" },
    h(
      "div",
      { className: "panel-title-group" },
      h("h2", { className: "panel-title", textContent: "Actividad de 12 semanas" }),
      h("p", {
        className: "panel-subtitle",
        textContent: isDemo
          ? "Datos de demostración (America/Cancun)"
          : "Calculado desde /analytics/learning (America/Cancun)",
      })
    ),
    h(
      "div",
      { className: "streak-badges" },
      h(
        "span",
        { className: `stat-pill ${streak > 0 ? "stat-pill-accent" : ""}` },
        createIcon("flame", 14),
        h("span", {
          className: "tabular",
          textContent: streak > 0 ? `Racha: ${pluralize(streak, "día", "días")}` : "Racha: 0 días",
        })
      ),
      h(
        "span",
        { className: "stat-pill tabular" },
        `${pluralize(activeDays, "día activo", "días activos")}`
      )
    )
  );

  if (loading) {
    return h(
      "section",
      { className: "panel heatmap-panel", "aria-busy": "true" },
      header,
      h("div", { className: "skeleton-heatmap", "aria-label": "Cargando actividad de 12 semanas" })
    );
  }

  if (error) {
    return h(
      "section",
      { className: "panel heatmap-panel" },
      header,
      h(
        "div",
        { className: "inline-error-box", role: "alert" },
        h("span", { textContent: error }),
        onRetry
          ? h("button", { className: "btn btn-secondary btn-sm", type: "button", onClick: onRetry }, "Reintentar")
          : null
      )
    );
  }

  // Group into 12 columns of 7 days with concise weekday hints
  const weeks = [];
  for (let i = 0; i < dateKeys.length; i += 7) {
    weeks.push(dateKeys.slice(i, i + 7));
  }

  const weekdayLabels = ["", "1", "", "3", "", "5", ""];
  if (weeks[0]?.length === 7) {
    const dayFmt = new Intl.DateTimeFormat("es-MX", { weekday: "narrow", timeZone: "UTC" });
    for (let r = 0; r < 7; r += 1) {
      const [y, m, d] = weeks[0][r].split("-").map(Number);
      const letter = dayFmt.format(new Date(Date.UTC(y, m - 1, d))).toUpperCase();
      weekdayLabels[r] = r % 2 === 1 ? letter : "";
    }
  }

  const weekdayCol = h(
    "div",
    { className: "heatmap-weekdays", "aria-hidden": "true" },
    ...weekdayLabels.map((lbl) => h("span", { textContent: lbl }))
  );

  const grid = h("div", {
    className: "heatmap-grid",
    role: "grid",
    "aria-label": "Mapa de repasos de las últimas 12 semanas",
  });

  weeks.forEach((week) => {
    const col = h("div", { className: "heatmap-col", role: "row" });
    week.forEach((dateKey) => {
      const count = counts[dateKey] || 0;
      const lvl = heatLevel(count);
      const label = `${formatIsoDate(dateKey)}: ${pluralize(count, "repaso", "repasos")}`;
      const cell = h("button", {
        type: "button",
        className: `heat-cell heat-l${lvl}`,
        "aria-label": label,
        title: label,
        onMouseenter: () => {
          readout.textContent = label;
        },
        onFocus: () => {
          readout.textContent = label;
        },
        onClick: () => {
          readout.textContent = label;
        },
      });
      col.append(cell);
    });
    grid.append(col);
  });

  const legend = h(
    "div",
    { className: "heatmap-legend", "aria-hidden": "true" },
    h("span", { textContent: "Menos" }),
    h("span", { className: "heat-swatch heat-l0" }),
    h("span", { className: "heat-swatch heat-l1" }),
    h("span", { className: "heat-swatch heat-l2" }),
    h("span", { className: "heat-swatch heat-l3" }),
    h("span", { className: "heat-swatch heat-l4" }),
    h("span", { textContent: "Más" })
  );

  const emptyNote =
    totalReviews === 0
      ? h(
          "div",
          { className: "heatmap-empty-note" },
          createIcon("alert", 15),
          h("span", {
            textContent:
              "Sin repasos registrados en las últimas 12 semanas. Completa tu primera sesión para activar el mapa y tu racha.",
          })
        )
      : null;

  const aside = h(
    "div",
    { className: "heatmap-aside" },
    h(
      "div",
      { className: "heatmap-aside-kpi" },
      h("span", { className: "heatmap-aside-num tabular", textContent: formatInt(totalReviews) }),
      h("span", {
        className: "heatmap-aside-label",
        textContent: totalReviews === 1 ? "repaso en 12 semanas" : "repasos en 12 semanas",
      })
    ),
    readout,
    legend
  );

  return h(
    "section",
    { className: "panel heatmap-panel" },
    header,
    h(
      "div",
      { className: "heatmap-body" },
      h("div", { className: "heatmap-scroll" }, h("div", { className: "heatmap-matrix" }, weekdayCol, grid)),
      aside
    ),
    emptyNote
  );
}

/**
 * Deck Tile with pending count pill, honest mastery bar, and clear actions.
 */
export function createDeckTile({ deck, dueCount, totalCount, masteredCount, onStudy, onInspect }) {
  const masteryPct = totalCount > 0 ? Math.round(clampPercent(masteredCount, totalCount)) : 0;
  const hasDue = dueCount > 0;
  const hasCards = totalCount > 0;

  return h(
    "article",
    { className: `deck-tile ${hasDue ? "deck-tile-due" : ""}` },
    h(
      "div",
      { className: "deck-tile-top" },
      h(
        "div",
        { className: "deck-tile-heading" },
        h("h3", {
          className: "deck-tile-name",
          dir: "auto",
          title: deck.name,
          textContent: deck.name,
        }),
        deck.description
          ? h("p", {
              className: "deck-tile-desc",
              dir: "auto",
              title: deck.description,
              textContent: deck.description,
            })
          : null
      ),
      h(
        "span",
        {
          className: `due-pill tabular ${hasDue ? "due-pill-active" : "due-pill-calm"}`,
          title: pluralize(dueCount, "tarjeta pendiente hoy", "tarjetas pendientes hoy"),
        },
        hasDue ? `${formatCompactCount(dueCount)} hoy` : "Al día"
      )
    ),
    h(
      "div",
      { className: "deck-mastery" },
      h(
        "div",
        { className: "deck-mastery-meta" },
        h("span", {
          className: "tabular",
          textContent: hasCards
            ? `${formatInt(masteredCount)} / ${formatInt(totalCount)} dominadas`
            : "Sin tarjetas todavía",
        }),
        h("span", {
          className: "tabular muted",
          textContent: hasCards ? `${masteryPct}%` : "0%",
        })
      ),
      h(
        "div",
        {
          className: "meter-track",
          role: "progressbar",
          "aria-label": `Dominio de ${deck.name}`,
          "aria-valuemin": "0",
          "aria-valuemax": "100",
          "aria-valuenow": String(masteryPct),
        },
        h("div", {
          className: "meter-fill",
          style: `transform: scaleX(${(masteryPct / 100).toFixed(4)})`,
        })
      )
    ),
    h(
      "div",
      { className: "deck-tile-actions" },
      h(
        "button",
        {
          type: "button",
          className: hasDue ? "btn btn-primary btn-sm" : "btn btn-secondary btn-sm",
          onClick: () => onStudy(deck.id),
        },
        createIcon("focus", 14),
        hasDue ? "Estudiar" : "Practicar"
      ),
      h(
        "button",
        {
          type: "button",
          className: "btn btn-ghost btn-sm",
          onClick: () => onInspect(deck.id),
        },
        "Tarjetas"
      )
    )
  );
}

/**
 * Interruptible toast manager (Sonner principles: CSS transitions, pause when
 * hidden or hovered, exits along the same bottom edge it entered).
 */
export function createToastManager(container) {
  const active = new Set();

  function dismiss(item) {
    if (!active.has(item)) return;
    active.delete(item);
    clearTimeout(item.timer);
    item.el.dataset.state = "closing";
    window.setTimeout(() => item.el.remove(), 220);
  }

  document.addEventListener("visibilitychange", () => {
    for (const item of active) {
      if (document.hidden) {
        clearTimeout(item.timer);
      } else {
        item.timer = window.setTimeout(() => dismiss(item), 2500);
      }
    }
  });

  function show(message, { tone = "neutral", duration = 3800 } = {}) {
    // Cap stack to 3 visible toasts
    while (active.size >= 3) {
      const oldest = active.values().next().value;
      dismiss(oldest);
    }

    const iconName = tone === "success" ? "check" : tone === "error" ? "alert" : "sparkles";
    const closeBtn = h(
      "button",
      {
        type: "button",
        className: "toast-close",
        "aria-label": "Cerrar notificación",
      },
      createIcon("x", 14)
    );

    const toastEl = h(
      "div",
      {
        className: `toast toast-${tone}`,
        role: tone === "error" ? "alert" : "status",
        dataset: { state: "open" },
      },
      h("span", { className: "toast-icon" }, createIcon(iconName, 15)),
      h("span", { className: "toast-msg", textContent: message }),
      closeBtn
    );

    const item = { el: toastEl, timer: null };
    closeBtn.addEventListener("click", () => dismiss(item));
    toastEl.addEventListener("mouseenter", () => clearTimeout(item.timer));
    toastEl.addEventListener("mouseleave", () => {
      if (active.has(item)) item.timer = window.setTimeout(() => dismiss(item), 2000);
    });

    active.add(item);
    container.append(toastEl);
    item.timer = window.setTimeout(() => dismiss(item), duration);
  }

  return { show };
}

/**
 * Accessible modal/sheet manager with focus trap & focus restoration.
 */
export function createModalManager({ backdrop, panel, titleEl, bodyEl, closeBtn }) {
  let lastFocused = null;
  let onCloseCallback = null;
  let closeTimer = null;

  function close({ immediate = false } = {}) {
    if (closeTimer !== null) {
      window.clearTimeout(closeTimer);
      closeTimer = null;
    }
    if (backdrop.hidden) return;
    const finish = () => {
      closeTimer = null;
      backdrop.hidden = true;
      backdrop.dataset.state = "";
      bodyEl.replaceChildren();
      if (lastFocused && typeof lastFocused.focus === "function") {
        lastFocused.focus();
      }
      lastFocused = null;
      if (onCloseCallback) {
        const cb = onCloseCallback;
        onCloseCallback = null;
        cb();
      }
    };
    if (immediate || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      finish();
    } else {
      backdrop.dataset.state = "closing";
      closeTimer = window.setTimeout(finish, 170);
    }
  }

  function open({ title, content, onClose = null, wide = false }) {
    if (closeTimer !== null) {
      window.clearTimeout(closeTimer);
      closeTimer = null;
    }
    lastFocused = document.activeElement;
    onCloseCallback = onClose;
    titleEl.textContent = title;
    panel.classList.toggle("modal-panel-wide", Boolean(wide));
    bodyEl.replaceChildren(content);
    backdrop.hidden = false;
    backdrop.dataset.state = "open";
    const focusable = panel.querySelector(
      "input:not([disabled]), textarea:not([disabled]), select:not([disabled]), button:not([disabled])"
    );
    if (focusable) focusable.focus();
  }

  closeBtn.addEventListener("click", close);
  backdrop.addEventListener("click", (e) => {
    if (e.target === backdrop) close();
  });
  document.addEventListener("keydown", (e) => {
    if (backdrop.hidden) return;
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      close();
    } else if (e.key === "Tab") {
      const nodes = Array.from(
        panel.querySelectorAll(
          'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        )
      ).filter((el) => el.offsetParent !== null);
      if (nodes.length === 0) return;
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  });

  return { open, close, isOpen: () => !backdrop.hidden };
}

export function createEmptyState({ icon = "layers", title, description, actions = [] }) {
  return h(
    "div",
    { className: "empty-state" },
    h("div", { className: "empty-state-icon" }, createIcon(icon, 22)),
    h("h3", { className: "empty-state-title", textContent: title }),
    description ? h("p", { className: "empty-state-desc", textContent: description }) : null,
    actions.length ? h("div", { className: "empty-state-actions" }, ...actions) : null
  );
}
