import { api, getDataMode, setDataMode } from "./api.js";
import { formatCompact, showToast } from "./ui.js";
import { mountAnalytics } from "./views/analytics.js";
import { mountCreate } from "./views/create.js";
import { mountDashboard } from "./views/dashboard.js";
import { mountErrors } from "./views/errors.js";
import { mountStudy } from "./views/study.js";

const ROUTES = {
  inicio: mountDashboard,
  estudiar: mountStudy,
  crear: mountCreate,
  errores: mountErrors,
  analitica: mountAnalytics,
};

const THEME_STORAGE_KEY = "techcards_p1_theme";
const MODE_LABELS = {
  demo: {
    title: "Modo Datos demo",
    desc: "Vista previa sintética de solo lectura. No se envía ninguna escritura a la API.",
  },
  worst: {
    title: "Modo Caso extremo (break-ui)",
    desc: "Datos de estrés (IDs de 19 dígitos, nombres largos, emoji, RTL, 10 000 tarjetas). Solo lectura.",
  },
  empty: {
    title: "Modo Estado vacío (break-ui)",
    desc: "Simula una instancia sin mazos, sin errores y sin repasos. Solo lectura.",
  },
};

let currentUnmount = null;
let currentRoute = "inicio";

function parseHashRoute() {
  const raw = (window.location.hash || "#inicio").replace(/^#/, "");
  const [routePart, queryPart] = raw.split("?");
  const route = ROUTES[routePart] ? routePart : "inicio";
  const params = {};
  if (queryPart) {
    for (const [k, v] of new URLSearchParams(queryPart)) {
      params[k] = v;
    }
  }
  return { route, params };
}

function syncUrlDataModeParam(mode) {
  const url = new URL(window.location.href);
  if (mode === "live") url.searchParams.delete("data");
  else url.searchParams.set("data", mode);
  window.history.replaceState(null, "", url.toString());
}

function initDataModeFromUrl() {
  const url = new URL(window.location.href);
  const param = url.searchParams.get("data");
  if (param && ["demo", "worst", "empty"].includes(param)) {
    setDataMode(param);
  } else {
    setDataMode("live");
  }
}

function applyTheme(theme) {
  const root = document.documentElement;
  if (theme === "light" || theme === "dark") {
    root.dataset.theme = theme;
    try {
      localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch (_) {}
  } else {
    delete root.dataset.theme;
    try {
      localStorage.removeItem(THEME_STORAGE_KEY);
    } catch (_) {}
  }

  const label = theme === "light" ? "Tema: Claro" : theme === "dark" ? "Tema: Oscuro" : "Tema: Auto";
  document.querySelectorAll("[data-theme-label]").forEach((node) => {
    node.textContent = label;
  });

  // Sync browser status bar theme-color meta tags
  const lightMeta = document.getElementById("meta-theme-light");
  const darkMeta = document.getElementById("meta-theme-dark");
  if (lightMeta && darkMeta) {
    if (theme === "dark") {
      lightMeta.setAttribute("content", "#141311");
      darkMeta.setAttribute("content", "#141311");
    } else if (theme === "light") {
      lightMeta.setAttribute("content", "#F6F4EF");
      darkMeta.setAttribute("content", "#F6F4EF");
    } else {
      lightMeta.setAttribute("content", "#F6F4EF");
      darkMeta.setAttribute("content", "#141311");
    }
  }
}

function cycleTheme() {
  const cur = document.documentElement.dataset.theme || "auto";
  const next = cur === "auto" ? "light" : cur === "light" ? "dark" : "auto";
  applyTheme(next);
}

function updateDataModeChrome() {
  const mode = getDataMode();
  const banner = document.getElementById("mode-banner");
  const titleNode = document.getElementById("mode-banner-title");
  const descNode = document.getElementById("mode-banner-desc");
  const mobileToggle = document.getElementById("mobile-demo-toggle");

  if (mode === "live") {
    banner.hidden = true;
  } else {
    const info = MODE_LABELS[mode] || MODE_LABELS.demo;
    titleNode.textContent = info.title;
    descNode.textContent = info.desc;
    banner.hidden = false;
  }

  document.querySelectorAll("[data-data-mode]").forEach((btn) => {
    const btnMode = btn.dataset.dataMode;
    if (btn.classList.contains("seg-btn")) {
      btn.setAttribute("aria-pressed", String(btnMode === mode));
    }
  });

  if (mobileToggle) {
    mobileToggle.setAttribute("aria-pressed", String(mode !== "live"));
    mobileToggle.textContent = mode === "live" ? "Datos demo" : mode === "worst" ? "Caso extremo" : mode === "empty" ? "Vacío" : "Demo activo";
  }
}

function updateNavActive(route) {
  document.querySelectorAll("[data-nav]").forEach((link) => {
    if (link.classList.contains("brand")) return;
    if (link.dataset.nav === route) {
      link.setAttribute("aria-current", "page");
    } else {
      link.removeAttribute("aria-current");
    }
  });
}

function updateBadges({ due, draftErrors }) {
  const dueBadge = document.querySelector('[data-badge="due"]');
  const dueDot = document.querySelector('[data-dot="due"]');
  if (typeof due === "number") {
    if (dueBadge) {
      dueBadge.textContent = formatCompact(due);
      dueBadge.hidden = due <= 0;
    }
    if (dueDot) dueDot.hidden = due <= 0;
  }

  const errBadge = document.querySelector('[data-badge="draftErrors"]');
  const errDot = document.querySelector('[data-dot="draftErrors"]');
  if (typeof draftErrors === "number") {
    if (errBadge) {
      errBadge.textContent = formatCompact(draftErrors);
      errBadge.hidden = draftErrors <= 0;
    }
    if (errDot) errDot.hidden = draftErrors <= 0;
  }
}

async function refreshGlobalBadges() {
  const [decksRes, draftErrRes] = await Promise.all([api.listDecks(), api.listErrors("draft")]);
  let totalDue = 0;
  if (decksRes.ok) {
    const counts = await Promise.all(
      (decksRes.data || []).map(async (d) => {
        const res = await api.listDueCards(d.id);
        if (typeof res.syntheticCount === "number") return res.syntheticCount;
        return res.ok ? (res.data || []).length : 0;
      })
    );
    totalDue = counts.reduce((a, b) => a + b, 0);
  }
  const draftErrors = draftErrRes.ok ? (draftErrRes.data || []).length : 0;
  updateBadges({ due: totalDue, draftErrors });
}

function navigate(route, params = {}) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  }
  const nextHash = `#${route}${qs.toString() ? `?${qs.toString()}` : ""}`;
  if (window.location.hash === nextHash) {
    renderCurrentRoute();
  } else {
    window.location.hash = nextHash;
  }
}

function switchDataMode(mode) {
  setDataMode(mode);
  syncUrlDataModeParam(mode);
  updateDataModeChrome();
  if (mode === "live") {
    showToast("Conectado a la API real.", { tone: "info" });
  } else {
    showToast(`${MODE_LABELS[mode]?.title || "Datos demo"} activado (solo lectura).`, { tone: "warning" });
  }
  refreshGlobalBadges();
  renderCurrentRoute();
}

function renderCurrentRoute() {
  const { route, params } = parseHashRoute();
  currentRoute = route;
  updateNavActive(route);

  if (currentUnmount) {
    currentUnmount();
    currentUnmount = null;
  }

  const root = document.getElementById("view-root");
  const mount = ROUTES[route] || mountDashboard;
  currentUnmount = mount(root, {
    params,
    navigate,
    updateBadges,
    refreshGlobalBadges,
    setDataMode: switchDataMode,
  });

  window.scrollTo({ top: 0, behavior: "instant" });
}

function wireGlobalControls() {
  document.addEventListener("click", (e) => {
    const modeBtn = e.target.closest("[data-data-mode]");
    if (modeBtn) {
      e.preventDefault();
      switchDataMode(modeBtn.dataset.dataMode);
      return;
    }

    const actionEl = e.target.closest("[data-action]");
    if (actionEl) {
      const action = actionEl.dataset.action;
      if (action === "cycle-theme") {
        cycleTheme();
      } else if (action === "toggle-demo") {
        switchDataMode(getDataMode() === "live" ? "demo" : "live");
      }
    }
  });

  // Global keyboard shortcut: 's' jumps to Study when not typing
  window.addEventListener("keydown", (e) => {
    const dialog = document.getElementById("app-dialog");
    if (dialog && dialog.open) return;
    const tag = e.target?.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || e.target?.isContentEditable) {
      return;
    }
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if ((e.key === "s" || e.key === "S") && currentRoute !== "estudiar") {
      e.preventDefault();
      navigate("estudiar");
    }
  });

  window.addEventListener("hashchange", renderCurrentRoute);
}

// Bootstrap
initDataModeFromUrl();
applyTheme(document.documentElement.dataset.theme || "auto");
updateDataModeChrome();
wireGlobalControls();
renderCurrentRoute();
if (currentRoute !== "inicio") {
  refreshGlobalBadges();
}
