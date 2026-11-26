/**
 * Safe DOM helpers, Spanish locale formatters (Intl), SM-2 deterministic preview,
 * inline SVG empty-state illustrations, native modal dialog, and interruptible toasts.
 *
 * Security rule: NEVER interpolate user data into innerHTML. Always use textContent via `el()`.
 */

const numFmt = new Intl.NumberFormat("es-MX");
const compactNumFmt = new Intl.NumberFormat("es-MX", { notation: "compact", maximumFractionDigits: 1 });
const pctFmt = new Intl.NumberFormat("es-MX", { maximumFractionDigits: 1 });
const pluralRules = new Intl.PluralRules("es");
const dateFmt = new Intl.DateTimeFormat("es-MX", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });

export function formatInt(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return numFmt.format(Number(value));
}

export function formatCompact(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  const n = Number(value);
  return Math.abs(n) >= 10000 ? compactNumFmt.format(n) : numFmt.format(n);
}

export function plural(count, one, other) {
  const n = Number(count) || 0;
  return `${formatInt(n)} ${pluralRules.select(n) === "one" ? one : other}`;
}

export function formatPercent(numerator, denominator) {
  if (!denominator || denominator <= 0) return null;
  const clamped = Math.max(0, Math.min(100, (numerator / denominator) * 100));
  return `${pctFmt.format(clamped)} %`;
}

export function formatIsoDate(isoDate) {
  if (!isoDate || typeof isoDate !== "string") return "—";
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(isoDate);
  if (!match) return isoDate;
  const d = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  return Number.isNaN(d.getTime()) ? isoDate : dateFmt.format(d);
}

export function formatDurationSeconds(seconds) {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return null;
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${formatInt(total)} s`;
  const mins = Math.floor(total / 60);
  if (mins < 60) return `${formatInt(mins)} min`;
  const hours = Math.floor(mins / 60);
  const remMins = mins % 60;
  if (hours < 24) return remMins ? `${formatInt(hours)} h ${remMins} min` : `${formatInt(hours)} h`;
  const days = Math.floor(hours / 24);
  const remHours = hours % 24;
  return remHours ? `${formatInt(days)} d ${remHours} h` : `${formatInt(days)} d`;
}

/**
 * Safe DOM element builder — sets text via textContent only.
 */
export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "className") {
      node.className = v;
    } else if (k === "dataset" && typeof v === "object") {
      for (const [dk, dv] of Object.entries(v)) {
        if (dv !== undefined && dv !== null) node.dataset[dk] = String(dv);
      }
    } else if (k.startsWith("on") && typeof v === "function") {
      node.addEventListener(k.slice(2).toLowerCase(), v);
    } else if (k === "checked" || k === "disabled" || k === "selected" || k === "required" || k === "readOnly") {
      node[k] = Boolean(v);
    } else if (k === "value") {
      node.value = String(v);
    } else {
      node.setAttribute(k, v === true ? "" : String(v));
    }
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

/**
 * Pure mirror of app/sm2.py schedule_review() interval calculation for honest grade button hints.
 */
export function previewSm2IntervalDays(card, quality) {
  if (quality < 3) return 1;
  const reps = Number(card?.repetitions || 0);
  const interval = Number(card?.interval_days || 0);
  const ease = Number(card?.ease_factor || 2.5);
  if (reps === 0) return 1;
  if (reps === 1) return 6;
  return Math.max(1, Math.ceil(interval * ease));
}

export const KIND_META = {
  vocabulary: { label: "Vocabulario", tone: "info" },
  interview_phrase: { label: "Frase entrevista", tone: "accent" },
  behavioral: { label: "STAR / Conductual", tone: "warning" },
  sentence: { label: "Oración", tone: "info" },
  cloze: { label: "Cloze (hueco)", tone: "accent" },
  es_en: { label: "ES → EN", tone: "success" },
  listening: { label: "Audio / Listening", tone: "info" },
};

export const STATUS_META = {
  draft: { label: "Borrador", tone: "warning" },
  approved: { label: "Aprobado", tone: "success" },
  discarded: { label: "Descartado", tone: "neutral" },
};

export const GRADE_OPTIONS = [
  { q: 0, label: "Olvido", tone: "fail" },
  { q: 1, label: "Casi nada", tone: "fail" },
  { q: 2, label: "Difícil", tone: "fail" },
  { q: 3, label: "Con esfuerzo", tone: "hard" },
  { q: 4, label: "Fluido", tone: "good" },
  { q: 5, label: "Perfecto", tone: "good" },
];

export function renderKindBadge(kind) {
  const meta = KIND_META[kind] || { label: String(kind || "Tarjeta"), tone: "neutral" };
  return el("span", { className: `badge ${meta.tone !== "neutral" ? `badge--${meta.tone}` : ""}` }, meta.label);
}

export function renderStatusBadge(status) {
  const meta = STATUS_META[status] || { label: String(status || ""), tone: "neutral" };
  return el("span", { className: `badge ${meta.tone !== "neutral" ? `badge--${meta.tone}` : ""}` }, meta.label);
}

/**
 * Render cloze text safely, highlighting the exact `____` blank without innerHTML.
 */
export function renderPromptText(text, kind) {
  const p = el("p", { className: "card-prompt-text", dir: "auto" });
  if (kind === "cloze" && typeof text === "string" && text.includes("____")) {
    const parts = text.split("____");
    parts.forEach((part, idx) => {
      if (part) p.append(document.createTextNode(part));
      if (idx < parts.length - 1) {
        p.append(el("span", { className: "cloze-blank", "aria-label": "espacio en blanco" }, "____"));
      }
    });
    return p;
  }
  p.textContent = text || "";
  return p;
}

/**
 * Clean editorial SVG illustrations for empty states (zero external assets).
 */
export function emptyIllustration(variant = "cards") {
  const svgNS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNS, "svg");
  svg.setAttribute("viewBox", "0 0 88 64");
  svg.setAttribute("width", "88");
  svg.setAttribute("height", "64");
  svg.setAttribute("fill", "none");
  svg.setAttribute("aria-hidden", "true");
  svg.classList.add("empty-illustration");

  const add = (tag, attrs) => {
    const node = document.createElementNS(svgNS, tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
    svg.append(node);
  };

  if (variant === "done") {
    add("circle", { cx: 44, cy: 32, r: 22, stroke: "currentColor", "stroke-width": 1.6, "stroke-dasharray": "4 4" });
    add("path", { d: "M34 32.5 41 39.5 55 25.5", stroke: "var(--success)", "stroke-width": 2.4, "stroke-linecap": "round", "stroke-linejoin": "round" });
  } else if (variant === "analytics") {
    add("path", { d: "M16 50h56", stroke: "currentColor", "stroke-width": 1.6, "stroke-linecap": "round" });
    add("rect", { x: 24, y: 34, width: 10, height: 16, rx: 2, stroke: "currentColor", "stroke-width": 1.6 });
    add("rect", { x: 39, y: 24, width: 10, height: 26, rx: 2, stroke: "currentColor", "stroke-width": 1.6 });
    add("rect", { x: 54, y: 16, width: 10, height: 34, rx: 2, stroke: "var(--accent)", "stroke-width": 1.8 });
  } else {
    add("rect", { x: 18, y: 12, width: 42, height: 34, rx: 5, stroke: "currentColor", "stroke-width": 1.6, "stroke-dasharray": "4 3" });
    add("rect", { x: 28, y: 18, width: 42, height: 34, rx: 5, fill: "var(--surface)", stroke: "currentColor", "stroke-width": 1.8 });
    add("path", { d: "M36 29h26M36 36h18", stroke: "currentColor", "stroke-width": 1.6, "stroke-linecap": "round" });
  }
  return svg;
}

export function renderEmptyState({ variant = "cards", title, description, action = null }) {
  return el(
    "section",
    { className: "empty-state" },
    emptyIllustration(variant),
    el("h3", { className: "empty-title" }, title),
    el("p", { className: "empty-desc" }, description),
    action
  );
}

export function renderErrorBanner(message, onRetry = null) {
  return el(
    "div",
    { className: "alert-banner", role: "alert" },
    el("div", { className: "alert-copy" }, message),
    onRetry ? el("button", { type: "button", className: "btn btn--secondary btn--sm", onClick: onRetry }, "Reintentar") : null
  );
}

export function renderSkeleton(variant = "dashboard") {
  if (variant === "study") {
    return el(
      "div",
      { className: "skeleton-stack", "aria-label": "Cargando sesión de estudio" },
      el("div", { className: "skeleton skeleton--title" }),
      el("div", { className: "skeleton", style: "height: 300px;" })
    );
  }
  return el(
    "div",
    { className: "skeleton-stack", "aria-label": "Cargando contenido" },
    el("div", { className: "skeleton skeleton--title" }),
    el("div", { className: "skeleton skeleton--hero" }),
    el(
      "div",
      { className: "skeleton-grid" },
      el("div", { className: "skeleton skeleton--card" }),
      el("div", { className: "skeleton skeleton--card" })
    )
  );
}

/**
 * Native <dialog> modal controller with accessible focus management.
 */
let activeDialogCleanup = null;

export function openModal({ title, content, onClose = null }) {
  const dialog = document.getElementById("app-dialog");
  const titleNode = document.getElementById("dialog-title");
  const bodyNode = document.getElementById("dialog-body");
  const closeBtn = document.getElementById("dialog-close-btn");
  if (!dialog || !titleNode || !bodyNode) return;

  if (activeDialogCleanup) {
    activeDialogCleanup();
    activeDialogCleanup = null;
  }

  titleNode.textContent = title;
  clear(bodyNode);
  if (content instanceof Node) bodyNode.append(content);
  else bodyNode.textContent = String(content || "");

  const handleBackdrop = (e) => {
    if (e.target === dialog) closeModal();
  };
  const handleCloseBtn = () => closeModal();
  const handleNativeClose = () => {
    if (onClose) onClose();
  };

  dialog.addEventListener("click", handleBackdrop);
  closeBtn.addEventListener("click", handleCloseBtn);
  dialog.addEventListener("close", handleNativeClose, { once: true });

  activeDialogCleanup = () => {
    dialog.removeEventListener("click", handleBackdrop);
    closeBtn.removeEventListener("click", handleCloseBtn);
  };

  if (!dialog.open) dialog.showModal();
}

export function closeModal() {
  const dialog = document.getElementById("app-dialog");
  if (dialog && dialog.open) dialog.close();
}

/**
 * Sonner-inspired interruptible toast stack (pauses auto-dismiss when tab is hidden).
 */
const activeToasts = new Set();

export function showToast(message, { tone = "info", durationMs = 3800 } = {}) {
  const region = document.getElementById("toast-region");
  if (!region) return;

  const toastEl = el(
    "div",
    { className: `toast toast--${tone}`, role: tone === "error" ? "alert" : "status" },
    el("div", { className: "toast-msg" }, message),
    el(
      "button",
      {
        type: "button",
        className: "toast-close",
        "aria-label": "Cerrar aviso",
        onClick: () => dismiss(),
      },
      "×"
    )
  );

  let remaining = durationMs;
  let startedAt = Date.now();
  let timer = null;
  let dismissed = false;

  const dismiss = () => {
    if (dismissed) return;
    dismissed = true;
    clearTimeout(timer);
    activeToasts.delete(ctrl);
    toastEl.dataset.leaving = "true";
    setTimeout(() => toastEl.remove(), 260);
  };

  const pause = () => {
    if (dismissed || !timer) return;
    clearTimeout(timer);
    timer = null;
    remaining = Math.max(400, remaining - (Date.now() - startedAt));
  };

  const resume = () => {
    if (dismissed || timer || document.hidden) return;
    startedAt = Date.now();
    timer = setTimeout(dismiss, remaining);
  };

  const ctrl = { pause, resume, dismiss };
  activeToasts.add(ctrl);

  toastEl.addEventListener("pointerenter", pause);
  toastEl.addEventListener("pointerleave", resume);

  // Cap visible toasts to 3 for cleanliness
  while (region.children.length >= 3) {
    region.firstElementChild.remove();
  }
  region.append(toastEl);
  resume();
}

document.addEventListener("visibilitychange", () => {
  for (const t of activeToasts) {
    if (document.hidden) t.pause();
    else t.resume();
  }
});

/**
 * Hold-to-confirm button for destructive actions (Emil Kowalski asymmetric clip-path pattern).
 * Supports both pointer hold (1.2s) and accessible keyboard double-confirm (Space/Enter).
 */
export function createHoldDeleteButton({ label = "Mantener para eliminar", onConfirm, disabled = false, small = true }) {
  let holdTimer = null;
  let armedByKeyboard = false;
  let keyboardResetTimer = null;

  const fill = el("span", { className: "btn-hold-fill", "aria-hidden": "true" });
  const textSpan = el("span", {}, label);
  const btn = el(
    "button",
    {
      type: "button",
      className: `btn btn--danger btn--hold ${small ? "btn--sm" : ""}`,
      disabled,
      title: "Mantén presionado 1.2 s (o pulsa dos veces con teclado) para confirmar",
    },
    fill,
    textSpan
  );

  const cancelHold = () => {
    if (holdTimer) {
      clearTimeout(holdTimer);
      holdTimer = null;
    }
    btn.classList.remove("is-holding");
  };

  btn.addEventListener("pointerdown", (e) => {
    if (btn.disabled || e.button !== 0) return;
    btn.setPointerCapture?.(e.pointerId);
    btn.classList.add("is-holding");
    holdTimer = setTimeout(() => {
      cancelHold();
      onConfirm();
    }, 1200);
  });

  btn.addEventListener("pointerup", cancelHold);
  btn.addEventListener("pointercancel", cancelHold);
  btn.addEventListener("pointerleave", cancelHold);

  // Accessible keyboard path (no trap for keyboard-only users)
  btn.addEventListener("keydown", (e) => {
    if (btn.disabled) return;
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      if (armedByKeyboard) {
        armedByKeyboard = false;
        clearTimeout(keyboardResetTimer);
        textSpan.textContent = label;
        onConfirm();
      } else {
        armedByKeyboard = true;
        textSpan.textContent = "Pulsa de nuevo para confirmar";
        keyboardResetTimer = setTimeout(() => {
          armedByKeyboard = false;
          textSpan.textContent = label;
        }, 3000);
      }
    }
  });

  return btn;
}
