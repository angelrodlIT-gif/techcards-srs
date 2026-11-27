/**
 * TechCards · Cabina de Entrenamiento (TechCards SRS)
 * Controller: state, real API orchestration, opt-in Demo/Worst-case mode,
 * theme persistence, Command Palette (Ctrl/Cmd+K), and Focus Mode shortcuts.
 */

import { api, fetchRealHeatmap } from "./api.js";
import {
  createIcon,
  createModalManager,
  createToastManager,
  h,
  hydrateIcons,
} from "./components.js";
import { buildDemoDataset, buildWorstCaseDataset } from "./fixtures.js";
import {
  addDaysToKey,
  computeDeckMastery,
  formatCompactCount,
  getLastNDaysKeys,
  pluralize,
  toCancunDateKey,
} from "./format.js";
import {
  buildApproveErrorModalContent,
  buildApproveSourceModalContent,
  buildCaptureErrorModalContent,
  buildDeckInspectorContent,
  buildDeckModalContent,
  buildEditCardModalContent,
  buildEditErrorModalContent,
  buildEditSourceModalContent,
  renderAnalyticsView,
  renderCreateView,
  renderDashboardView,
  renderErrorsView,
  renderStudyView,
} from "./views.js";

const THEME_STORAGE_KEY = "techcards:ui:theme";
const VIEW_TITLES = {
  dashboard: "Cabina",
  study: "Modo foco",
  create: "Crear",
  errors: "Errores",
  analytics: "Analítica",
};

const isMac = /Mac|iPhone|iPad|iPod/i.test(navigator.platform || navigator.userAgent || "");

const todayKey = toCancunDateKey();
const initialDateKeys = getLastNDaysKeys(84, todayKey);

const state = {
  isMac,
  todayKey,
  view: "dashboard",
  createTab: "generate",
  templateCategory: "all",
  sourceFilter: "all",
  errorsMobileCol: "draft",

  // Data mode: real API by default; demo/worst-case strictly opt-in & read-only to API
  demoMode: false,
  demoVariant: "demo", // "demo" | "worst"
  demoData: null,

  apiStatus: "connecting", // "connecting" | "ok" | "demo" | "error"
  loadingInitial: true,
  loadError: "",

  decks: [],
  deckStats: {}, // { [deckId]: { total, due, mastered, cards } }
  selectedDeckId: "",
  lastGeneratedCards: [],

  templates: [],
  templatesLoading: false,
  templatesError: "",
  addedTemplateIds: new Set(),

  sources: [],
  sourcesLoading: false,
  sourcesError: "",

  errors: [],
  errorsLoading: false,
  errorsError: "",

  heatmap: {
    dateKeys: initialDateKeys,
    counts: Object.fromEntries(initialDateKeys.map((k) => [k, 0])),
    loading: true,
    error: "",
  },
  sessionCompletedToday: 0,

  analytics: {
    preset: "all",
    start: "",
    end: "",
    data: null,
    loading: false,
    error: "",
  },

  study: {
    deckId: "",
    filterKind: "",
    remediationOnly: false,
    initialDueCount: 0,
    card: null,
    reveal: null,
    loading: false,
    revealing: false,
    grading: false,
    error: "",
    sessionHistory: [],
    audioLoading: false,
    audioUrl: "",
    audioError: "",
  },
};

/* ==========================================================================
   DOM References & Core UI Services
   ========================================================================== */

const shellEl = document.getElementById("app-shell");
const mainEl = document.getElementById("main-content");
const mobileTitleEl = document.getElementById("mobile-view-title");
const apiStatusLabelEl = document.getElementById("api-status-label");
const apiStatusDotEl = document.getElementById("api-status-dot");
const mobileStatusDotEl = document.getElementById("mobile-status-dot");
const navBadgeDueEl = document.getElementById("nav-badge-due");
const navBadgeErrorsEl = document.getElementById("nav-badge-errors");
const mobileBadgeDueEl = document.getElementById("mobile-badge-due");
const demoToggleEl = document.getElementById("demo-mode-toggle");
const demoVariantBarEl = document.getElementById("demo-variant-bar");
const demoBannerEl = document.getElementById("demo-banner");
const demoBannerTitleEl = document.getElementById("demo-banner-title");
const demoBannerDescEl = document.getElementById("demo-banner-desc");
const themeToggleBtn = document.getElementById("theme-toggle-btn");
const themeToggleLabel = document.getElementById("theme-toggle-label");
const themeToggleIcon = document.getElementById("theme-toggle-icon");
const mobileThemeIcon = document.getElementById("mobile-theme-icon");
const themeColorMeta = document.getElementById("theme-color-meta");
const cmdShortcutHint = document.getElementById("cmd-shortcut-hint");

const toast = createToastManager(document.getElementById("toast-region"));
const modal = createModalManager({
  backdrop: document.getElementById("modal-backdrop"),
  panel: document.getElementById("modal-panel"),
  titleEl: document.getElementById("modal-title"),
  bodyEl: document.getElementById("modal-body"),
  closeBtn: document.getElementById("modal-close-btn"),
});

/* ==========================================================================
   Theme Management (Dark default, persisted in localStorage)
   ========================================================================== */

function applyTheme(theme) {
  const normalized = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = normalized;
  try {
    localStorage.setItem(THEME_STORAGE_KEY, normalized);
  } catch {
    // Ignore storage restriction
  }
  if (themeColorMeta) {
    themeColorMeta.setAttribute("content", normalized === "light" ? "#f5f6f8" : "#0b0c0f");
  }
  const nextIcon = normalized === "light" ? "moon" : "sun";
  if (themeToggleLabel) {
    themeToggleLabel.textContent = normalized === "light" ? "Tema oscuro" : "Tema claro";
  }
  if (themeToggleIcon) themeToggleIcon.replaceChildren(createIcon(nextIcon, 16));
  if (mobileThemeIcon) mobileThemeIcon.replaceChildren(createIcon(nextIcon, 16));
}

function initTheme() {
  let saved = "dark";
  try {
    saved = localStorage.getItem(THEME_STORAGE_KEY) || "dark";
  } catch {
    saved = "dark";
  }
  applyTheme(saved);
}

function toggleTheme() {
  const current = document.documentElement.dataset.theme === "light" ? "light" : "dark";
  applyTheme(current === "light" ? "dark" : "light");
}

/* ==========================================================================
   Status, Badges & Shell Chrome
   ========================================================================== */

function updateChrome() {
  const isFocus = state.view === "study";
  shellEl.classList.toggle("focus-active", isFocus);
  document.body.classList.toggle("focus-mode-body", isFocus);

  if (mobileTitleEl) {
    mobileTitleEl.textContent = VIEW_TITLES[state.view] || "Cabina";
  }

  document.querySelectorAll("[data-view]").forEach((btn) => {
    const active = btn.dataset.view === state.view;
    if (active) btn.setAttribute("aria-current", "page");
    else btn.removeAttribute("aria-current");
  });

  // Status indicator
  const statusMap = {
    connecting: { dot: "", label: "Conectando…" },
    ok: { dot: "ok", label: "API local activa" },
    demo: {
      dot: "demo",
      label: state.demoVariant === "worst" ? "Peor caso (solo vista)" : "Datos demo (solo vista)",
    },
    error: { dot: "error", label: "API sin conexión" },
  };
  const st = statusMap[state.apiStatus] || statusMap.connecting;
  if (apiStatusLabelEl) apiStatusLabelEl.textContent = st.label;
  if (apiStatusDotEl) apiStatusDotEl.dataset.status = st.dot;
  if (mobileStatusDotEl) mobileStatusDotEl.dataset.status = st.dot;

  // Demo controls & banner
  if (demoToggleEl) demoToggleEl.checked = state.demoMode;
  if (demoVariantBarEl) demoVariantBarEl.hidden = !state.demoMode;
  if (demoBannerEl) demoBannerEl.hidden = !state.demoMode;
  if (state.demoMode) {
    demoBannerTitleEl.textContent =
      state.demoVariant === "worst" ? "Modo Peor caso (break-ui)" : "Modo Datos demo";
    demoBannerDescEl.textContent =
      state.demoVariant === "worst"
        ? "Datos extremos en memoria (IDs > 2^53, nombres largos, 0/1/10,000 tarjetas) — nunca escribe en la API."
        : "Vista de demostración en memoria — ninguna acción escribe en la API.";
  }
  document.querySelectorAll("[data-demo-variant]").forEach((btn) => {
    btn.setAttribute("aria-pressed", String(btn.dataset.demoVariant === state.demoVariant));
  });

  // Navigation badges
  const totalDue = state.decks.reduce((acc, d) => acc + (state.deckStats[d.id]?.due ?? 0), 0);
  if (navBadgeDueEl) {
    navBadgeDueEl.hidden = totalDue <= 0;
    navBadgeDueEl.textContent = formatCompactCount(totalDue);
  }
  if (mobileBadgeDueEl) {
    mobileBadgeDueEl.hidden = totalDue <= 0;
  }

  const draftErrors = state.errors.filter((e) => e.status === "draft").length;
  if (navBadgeErrorsEl) {
    navBadgeErrorsEl.hidden = draftErrors <= 0;
    navBadgeErrorsEl.textContent = formatCompactCount(draftErrors);
  }
}

function render() {
  updateChrome();
  const ctx = { state, actions };
  let content;
  switch (state.view) {
    case "study":
      content = renderStudyView(ctx);
      break;
    case "create":
      content = renderCreateView(ctx);
      break;
    case "errors":
      content = renderErrorsView(ctx);
      break;
    case "analytics":
      content = renderAnalyticsView(ctx);
      break;
    default:
      content = renderDashboardView(ctx);
      break;
  }
  mainEl.replaceChildren(content);
}

/* ==========================================================================
   Demo / Worst-Case In-Memory Helpers (NEVER write to API)
   ========================================================================== */

let demoSeq = 9000;
function nextDemoId() {
  demoSeq += 1;
  return state.demoVariant === "worst"
    ? `900719925474100${demoSeq}`
    : String(demoSeq);
}

function computeDemoDeckStats(data) {
  const stats = {};
  for (const deck of data.decks) {
    const cards = data.cards.filter((c) => c.deck_id === deck.id);
    if (deck._syntheticTotalCards !== undefined) {
      stats[deck.id] = {
        total: deck._syntheticTotalCards,
        due: deck._syntheticDueCards,
        mastered: deck._syntheticMasteredCards,
        cards,
      };
    } else {
      const due = cards.filter((c) => c.due_date <= state.todayKey).length;
      const mastery = computeDeckMastery(cards);
      stats[deck.id] = {
        total: cards.length,
        due,
        mastered: mastery.mastered,
        cards,
      };
    }
  }
  return stats;
}

function loadDemoDataset(variant = "demo") {
  state.demoMode = true;
  state.demoVariant = variant;
  state.apiStatus = "demo";
  state.loadingInitial = false;
  state.loadError = "";
  state.demoData = variant === "worst" ? buildWorstCaseDataset() : buildDemoDataset();

  state.decks = state.demoData.decks;
  state.deckStats = computeDemoDeckStats(state.demoData);
  state.selectedDeckId = state.decks[0]?.id || "";
  state.templates = state.demoData.templates;
  state.templatesLoading = false;
  state.templatesError = "";
  state.sources = state.demoData.sources;
  state.sourcesLoading = false;
  state.sourcesError = "";
  state.errors = state.demoData.errors;
  state.errorsLoading = false;
  state.errorsError = "";
  state.heatmap = {
    dateKeys: initialDateKeys,
    counts: { ...state.demoData.heatmapCounts },
    loading: false,
    error: "",
  };
  state.analytics = {
    ...state.analytics,
    data: state.demoData.analytics,
    loading: false,
    error: "",
  };

  syncUrlDemoParam(variant);
  if (state.view === "study" && state.decks[0]) {
    actions.startStudy(state.decks[0].id);
  } else {
    render();
  }
}

function syncUrlDemoParam(mode) {
  try {
    const url = new URL(window.location.href);
    if (!mode) url.searchParams.delete("data");
    else url.searchParams.set("data", mode);
    window.history.replaceState({}, "", url.toString());
  } catch {
    // Ignore history API restrictions
  }
}

/* ==========================================================================
   Real API Loaders
   ========================================================================== */

let heatmapSeq = 0;

async function refreshDeckStats(decks) {
  const stats = {};
  await Promise.all(
    decks.map(async (deck) => {
      const [dueRes, cardsRes] = await Promise.all([
        api.listDueCards(deck.id),
        api.listCards(deck.id),
      ]);
      const cards = cardsRes.ok ? cardsRes.data : [];
      const due = dueRes.ok ? dueRes.data.length : 0;
      const mastery = computeDeckMastery(cards);
      stats[deck.id] = {
        total: cards.length,
        due,
        mastered: mastery.mastered,
        cards,
      };
    })
  );
  state.deckStats = stats;
}

async function refreshHeatmap() {
  if (state.demoMode) return;
  const seq = ++heatmapSeq;
  state.heatmap.loading = true;
  state.heatmap.error = "";
  render();

  const res = await fetchRealHeatmap(state.heatmap.dateKeys);
  if (seq !== heatmapSeq || state.demoMode) return;
  state.heatmap.loading = false;
  if (res.ok) {
    state.heatmap.counts = res.counts;
    state.heatmap.error = "";
  } else {
    state.heatmap.error = res.error;
  }
  render();
}

async function loadTemplates() {
  if (state.demoMode) return;
  state.templatesLoading = true;
  state.templatesError = "";
  render();
  const res = await api.listTemplates();
  if (state.demoMode) return;
  state.templatesLoading = false;
  if (res.ok) {
    state.templates = Array.isArray(res.data) ? res.data : [];
  } else {
    state.templatesError = res.error;
  }
  render();
}

async function loadSources() {
  if (state.demoMode) return;
  state.sourcesLoading = true;
  state.sourcesError = "";
  render();
  const res = await api.listSources();
  if (state.demoMode) return;
  state.sourcesLoading = false;
  if (res.ok) {
    state.sources = res.data;
  } else {
    state.sourcesError = res.error;
  }
  render();
}

async function loadErrors() {
  if (state.demoMode) return;
  state.errorsLoading = true;
  state.errorsError = "";
  render();
  const res = await api.listErrors();
  if (state.demoMode) return;
  state.errorsLoading = false;
  if (res.ok) {
    state.errors = res.data;
  } else {
    state.errorsError = res.error;
  }
  render();
}

async function loadAnalytics() {
  if (state.demoMode) {
    render();
    return;
  }
  state.analytics.loading = true;
  state.analytics.error = "";
  render();
  const res = await api.learningSummary({
    start: state.analytics.start,
    end: state.analytics.end,
  });
  if (state.demoMode) return;
  state.analytics.loading = false;
  if (res.ok) {
    state.analytics.data = res.data;
  } else {
    state.analytics.error = res.error;
  }
  render();
}

async function refreshAll() {
  if (state.demoMode) {
    loadDemoDataset(state.demoVariant);
    return;
  }

  state.loadError = "";
  const [healthRes, decksRes, errorsRes, templatesRes, sourcesRes] = await Promise.all([
    api.health(),
    api.listDecks(),
    api.listErrors(),
    api.listTemplates(),
    api.listSources(),
  ]);

  if (state.demoMode) return;
  state.loadingInitial = false;

  if (!healthRes.ok && !decksRes.ok) {
    state.apiStatus = "error";
    state.loadError = decksRes.error || healthRes.error;
    state.heatmap.loading = false;
    render();
    return;
  }

  state.apiStatus = healthRes.ok ? "ok" : "error";
  if (decksRes.ok) {
    state.decks = decksRes.data;
    if (!state.selectedDeckId || !state.decks.some((d) => d.id === state.selectedDeckId)) {
      state.selectedDeckId = state.decks[0]?.id || "";
    }
    await refreshDeckStats(state.decks);
  } else {
    state.loadError = decksRes.error;
  }

  if (errorsRes.ok) state.errors = errorsRes.data;
  if (templatesRes.ok) state.templates = Array.isArray(templatesRes.data) ? templatesRes.data : [];
  if (sourcesRes.ok) state.sources = sourcesRes.data;

  render();
  refreshHeatmap();
  if (state.view === "analytics") loadAnalytics();
}

/* ==========================================================================
   Study Flow (Recall-First)
   ========================================================================== */

function clearStudyAudio() {
  if (state.study.audioUrl) {
    URL.revokeObjectURL(state.study.audioUrl);
    state.study.audioUrl = "";
  }
  state.study.audioError = "";
  state.study.audioLoading = false;
}

async function loadNextStudyCard() {
  clearStudyAudio();
  const study = state.study;
  study.reveal = null;
  study.error = "";

  if (!study.deckId) {
    study.card = null;
    study.loading = false;
    render();
    return;
  }

  if (state.demoMode) {
    const dueCards = state.demoData.cards.filter((c) => {
      if (c.deck_id !== study.deckId) return false;
      if (c.due_date > state.todayKey) return false;
      if (study.filterKind && c.kind !== study.filterKind) return false;
      if (study.remediationOnly && !c.error_id) return false;
      return true;
    });
    const next = dueCards[0] || null;
    study.card = next
      ? {
          card_id: next.id,
          deck_id: next.deck_id,
          front: next.front,
          kind: next.kind,
          source_label: next.source_label,
          error_id: next.error_id,
          due_date: next.due_date,
          repetitions: next.repetitions,
          interval_days: next.interval_days,
          ease_factor: next.ease_factor,
        }
      : null;
    study.loading = false;
    render();
    return;
  }

  study.loading = true;
  render();
  const res = await api.studyNext(study.deckId, {
    kind: study.filterKind,
    remediationOnly: study.remediationOnly,
  });
  study.loading = false;
  if (res.status === 204) {
    study.card = null;
  } else if (res.ok) {
    study.card = res.data;
  } else {
    study.card = null;
    study.error = res.error;
  }
  render();
}

/* ==========================================================================
   Command Palette (Instant — 0ms, Keyboard-First)
   ========================================================================== */

const cmdBackdrop = document.getElementById("command-palette-backdrop");
const cmdInput = document.getElementById("cmd-input");
const cmdResults = document.getElementById("cmd-results");

let cmdItems = [];
let cmdActiveIdx = 0;
let cmdPrevFocus = null;

function buildCommandList() {
  const list = [
    { group: "Vistas", icon: "cockpit", label: "Ir a Cabina (Inicio)", meta: "Vista", run: () => actions.navigate("dashboard") },
    { group: "Vistas", icon: "focus", label: "Abrir Modo foco", meta: "Estudiar", run: () => actions.startStudy(state.selectedDeckId || state.decks[0]?.id || "") },
    { group: "Vistas", icon: "sparkles", label: "Generar tarjetas desde texto", meta: "Crear", run: () => actions.navigate("create", { tab: "generate" }) },
    { group: "Vistas", icon: "create", label: "Crear tarjeta manual", meta: "Crear", run: () => actions.navigate("create", { tab: "manual" }) },
    { group: "Vistas", icon: "layers", label: "Galería de plantillas STAR / Networking", meta: "Plantillas", run: () => actions.navigate("create", { tab: "templates" }) },
    { group: "Vistas", icon: "external", label: "Gestionar fuentes de estudio", meta: "Fuentes", run: () => actions.navigate("create", { tab: "sources" }) },
    { group: "Vistas", icon: "errors", label: "Tablero de errores (3 columnas)", meta: "Errores", run: () => actions.navigate("errors") },
    { group: "Vistas", icon: "analytics", label: "Ver Analítica de aprendizaje", meta: "Analítica", run: () => actions.navigate("analytics") },
  ];

  state.decks.forEach((deck) => {
    const due = state.deckStats[deck.id]?.due ?? 0;
    list.push({
      group: "Mazos",
      icon: "focus",
      label: `Estudiar: ${deck.name}`,
      meta: due > 0 ? `${formatCompactCount(due)} hoy` : "Al día",
      run: () => actions.startStudy(deck.id),
    });
  });

  list.push(
    { group: "Acciones rápidas", icon: "create", label: "Nuevo mazo", meta: "Crear", run: () => actions.openNewDeckModal() },
    { group: "Acciones rápidas", icon: "sparkles", label: "Registrar o sugerir error de entrevista", meta: "Errores", run: () => actions.openCaptureErrorModal() },
    { group: "Acciones rápidas", icon: "sun", label: "Cambiar tema oscuro / claro", meta: "Apariencia", run: toggleTheme },
    {
      group: "Acciones rápidas",
      icon: "flask",
      label: state.demoMode ? "Salir de Datos demo (volver a API real)" : "Activar Datos demo (solo lectura)",
      meta: "Datos",
      run: () => actions.setDemoMode(!state.demoMode),
    }
  );

  return list;
}

function renderCommandResults() {
  const q = cmdInput.value.trim().toLowerCase();
  const all = buildCommandList();
  cmdItems = q
    ? all.filter((item) => `${item.label} ${item.group} ${item.meta}`.toLowerCase().includes(q))
    : all;
  cmdActiveIdx = Math.min(cmdActiveIdx, Math.max(0, cmdItems.length - 1));

  cmdResults.replaceChildren();
  if (cmdItems.length === 0) {
    cmdResults.append(h("div", { className: "cmd-empty", textContent: "Sin resultados para esa búsqueda." }));
    return;
  }

  let currentGroup = "";
  cmdItems.forEach((item, idx) => {
    if (item.group !== currentGroup) {
      currentGroup = item.group;
      cmdResults.append(h("div", { className: "cmd-group-label", textContent: currentGroup }));
    }
    const row = h(
      "button",
      {
        type: "button",
        role: "option",
        className: "cmd-item",
        "aria-selected": String(idx === cmdActiveIdx),
        onMouseenter: () => {
          cmdActiveIdx = idx;
          updateCmdSelection();
        },
        onClick: () => executeCommand(idx),
      },
      h("span", { className: "cmd-item-main" }, createIcon(item.icon, 15), h("span", { className: "cmd-item-label", textContent: item.label })),
      h("span", { className: "cmd-item-meta tabular", textContent: item.meta })
    );
    cmdResults.append(row);
  });
}

function updateCmdSelection() {
  const buttons = cmdResults.querySelectorAll(".cmd-item");
  buttons.forEach((btn, idx) => {
    const selected = idx === cmdActiveIdx;
    btn.setAttribute("aria-selected", String(selected));
    if (selected) btn.scrollIntoView({ block: "nearest" });
  });
}

function openCommandPalette() {
  if (!cmdBackdrop.hidden) return;
  cmdPrevFocus = document.activeElement;
  cmdBackdrop.hidden = false;
  cmdInput.value = "";
  cmdActiveIdx = 0;
  renderCommandResults();
  cmdInput.focus();
}

function closeCommandPalette() {
  if (cmdBackdrop.hidden) return;
  cmdBackdrop.hidden = true;
  if (cmdPrevFocus && typeof cmdPrevFocus.focus === "function") {
    cmdPrevFocus.focus();
  }
  cmdPrevFocus = null;
}

function executeCommand(idx) {
  const item = cmdItems[idx];
  closeCommandPalette();
  if (item) item.run();
}

cmdInput.addEventListener("input", () => {
  cmdActiveIdx = 0;
  renderCommandResults();
});

cmdInput.addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown") {
    e.preventDefault();
    if (cmdItems.length) {
      cmdActiveIdx = (cmdActiveIdx + 1) % cmdItems.length;
      updateCmdSelection();
    }
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    if (cmdItems.length) {
      cmdActiveIdx = (cmdActiveIdx - 1 + cmdItems.length) % cmdItems.length;
      updateCmdSelection();
    }
  } else if (e.key === "Enter") {
    e.preventDefault();
    executeCommand(cmdActiveIdx);
  } else if (e.key === "Escape") {
    e.preventDefault();
    closeCommandPalette();
  }
});

cmdBackdrop.addEventListener("click", (e) => {
  if (e.target === cmdBackdrop) closeCommandPalette();
});

/* ==========================================================================
   Application Actions
   ========================================================================== */

const actions = {
  refreshAll,
  refreshHeatmap,
  loadTemplates,
  loadSources,
  loadErrors,
  loadAnalytics,
  loadNextStudyCard,
  openCommandPalette,

  navigate(view, opts = {}) {
    if (state.view === "study" && view !== "study") {
      clearStudyAudio();
    }
    state.view = view;
    if (opts.tab) state.createTab = opts.tab;
    render();
    if (view === "analytics" && !state.analytics.data && !state.demoMode) {
      loadAnalytics();
    } else if (view === "create" && state.createTab === "templates" && state.templates.length === 0) {
      loadTemplates();
    } else if (view === "create" && state.createTab === "sources" && state.sources.length === 0) {
      loadSources();
    } else if (view === "errors" && state.errors.length === 0 && !state.demoMode) {
      loadErrors();
    }
  },

  setCreateTab(tab) {
    state.createTab = tab;
    render();
    if (tab === "templates" && state.templates.length === 0 && !state.demoMode) loadTemplates();
    if (tab === "sources" && state.sources.length === 0 && !state.demoMode) loadSources();
  },

  setTemplateCategory(cat) {
    state.templateCategory = cat;
    render();
  },

  setSelectedDeckId(deckId) {
    state.selectedDeckId = deckId;
    render();
  },

  setSourceFilter(filter) {
    state.sourceFilter = filter;
    render();
  },

  setErrorsMobileCol(col) {
    state.errorsMobileCol = col;
    render();
  },

  setDemoMode(enabled, variant = state.demoVariant) {
    if (enabled) {
      loadDemoDataset(variant);
      toast.show(
        variant === "worst"
          ? "Modo Peor caso activo (solo lectura, no escribe en API)."
          : "Modo Datos demo activo (solo lectura, no escribe en API)."
      );
    } else {
      state.demoMode = false;
      state.demoData = null;
      state.loadingInitial = true;
      state.apiStatus = "connecting";
      syncUrlDemoParam("");
      render();
      refreshAll();
    }
  },

  setDemoVariant(variant) {
    state.demoVariant = variant;
    if (state.demoMode) {
      loadDemoDataset(variant);
    }
  },

  async startStudy(deckId, { keepFilters = false } = {}) {
    const resolvedDeckId = deckId || state.decks[0]?.id || "";
    state.view = "study";
    state.selectedDeckId = resolvedDeckId;
    state.study = {
      deckId: resolvedDeckId,
      filterKind: keepFilters ? state.study.filterKind : "",
      remediationOnly: keepFilters ? state.study.remediationOnly : false,
      initialDueCount: state.deckStats[resolvedDeckId]?.due ?? 0,
      card: null,
      reveal: null,
      loading: true,
      revealing: false,
      grading: false,
      error: "",
      sessionHistory: [],
      audioLoading: false,
      audioUrl: "",
      audioError: "",
    };
    render();
    await loadNextStudyCard();
  },

  async setStudyFilter({ kind, remediationOnly }) {
    if (kind !== undefined) state.study.filterKind = kind;
    if (remediationOnly !== undefined) state.study.remediationOnly = remediationOnly;
    await loadNextStudyCard();
  },

  async revealStudyCard() {
    const study = state.study;
    if (!study.card || study.reveal || study.revealing) return;

    if (state.demoMode) {
      const full = state.demoData.cards.find((c) => c.id === study.card.card_id);
      if (full) {
        study.reveal = {
          card_id: full.id,
          deck_id: full.deck_id,
          back: full.back,
          accepted_answers: full.accepted_answers || [],
          explanation: full.explanation || null,
        };
      }
      render();
      return;
    }

    study.revealing = true;
    render();
    const res = await api.studyReveal(study.card.card_id);
    study.revealing = false;
    if (res.ok) {
      study.reveal = res.data;
    } else {
      toast.show(res.error, { tone: "error" });
    }
    render();
  },

  async loadListeningAudio() {
    const study = state.study;
    if (!study.card || study.audioLoading) return;
    if (state.demoMode) {
      study.audioError = "Audio Polly deshabilitado en Datos demo. Revela la tarjeta para ver la transcripción.";
      render();
      return;
    }
    study.audioLoading = true;
    study.audioError = "";
    render();
    const res = await api.studyAudio(study.card.card_id);
    study.audioLoading = false;
    if (res.ok && res.blob) {
      if (study.audioUrl) URL.revokeObjectURL(study.audioUrl);
      study.audioUrl = URL.createObjectURL(res.blob);
    } else if (res.status === 503) {
      study.audioError =
        "Audio Polly no disponible (deshabilitado por defecto en este servidor). Revela la tarjeta para estudiar con la transcripción.";
    } else {
      study.audioError = res.error;
    }
    render();
  },

  async gradeStudyCard(quality) {
    const study = state.study;
    if (!study.card || !study.reveal || study.grading) return;
    const cardSnapshot = study.card;

    if (state.demoMode) {
      const full = state.demoData.cards.find((c) => c.id === cardSnapshot.card_id);
      const nextDays = quality < 3 ? 1 : quality === 3 ? 2 : quality === 4 ? 6 : 10;
      if (full) {
        full.repetitions = quality < 3 ? 0 : (full.repetitions || 0) + 1;
        full.interval_days = nextDays;
        full.due_date = addDaysToKey(state.todayKey, nextDays);
      }
      study.sessionHistory.push({
        cardId: cardSnapshot.card_id,
        front: cardSnapshot.front,
        quality,
        intervalDays: nextDays,
      });
      state.sessionCompletedToday += 1;
      state.heatmap.counts[state.todayKey] = (state.heatmap.counts[state.todayKey] || 0) + 1;
      state.deckStats = computeDemoDeckStats(state.demoData);
      toast.show(`Calificada ${quality}/5 · próxima en ${pluralize(nextDays, "día", "días")} (demo local)`, {
        tone: quality >= 3 ? "success" : "neutral",
      });
      await loadNextStudyCard();
      return;
    }

    study.grading = true;
    render();
    const res = await api.studyGrade(cardSnapshot.card_id, quality);
    study.grading = false;
    if (!res.ok) {
      toast.show(res.error, { tone: "error" });
      render();
      return;
    }

    const review = res.data;
    study.sessionHistory.push({
      cardId: cardSnapshot.card_id,
      front: cardSnapshot.front,
      quality,
      intervalDays: review.interval_days,
    });
    state.sessionCompletedToday += 1;
    state.heatmap.counts[state.todayKey] = (state.heatmap.counts[state.todayKey] || 0) + 1;
    if (state.deckStats[study.deckId] && state.deckStats[study.deckId].due > 0) {
      state.deckStats[study.deckId].due -= 1;
    }

    toast.show(
      `Guardado (${quality}/5) · próximo repaso en ${pluralize(review.interval_days, "día", "días")}`,
      { tone: quality >= 3 ? "success" : "neutral", duration: 2400 }
    );

    await loadNextStudyCard();
    refreshDeckStats(state.decks).then(updateChrome);
  },

  // Deck modals & CRUD
  openNewDeckModal() {
    modal.open({
      title: "Nuevo mazo",
      content: buildDeckModalContent({
        onCancel: modal.close,
        onSubmit: async (payload) => {
          if (state.demoMode) {
            const created = { id: nextDemoId(), ...payload };
            state.demoData.decks.push(created);
            state.decks = state.demoData.decks;
            state.deckStats = computeDemoDeckStats(state.demoData);
            state.selectedDeckId = created.id;
            modal.close();
            toast.show("Mazo creado en memoria (Datos demo).", { tone: "success" });
            render();
            return;
          }
          const res = await api.createDeck(payload);
          if (!res.ok) {
            toast.show(res.error, { tone: "error" });
            return;
          }
          state.selectedDeckId = res.data.id;
          modal.close();
          toast.show(`Mazo "${res.data.name}" creado.`, { tone: "success" });
          await refreshAll();
        },
      }),
    });
  },

  openEditDeckModal(deck) {
    modal.open({
      title: "Editar mazo",
      content: buildDeckModalContent({
        deck,
        onCancel: modal.close,
        onSubmit: async (payload) => {
          if (state.demoMode) {
            deck.name = payload.name;
            deck.description = payload.description;
            modal.close();
            toast.show("Mazo actualizado en memoria (Datos demo).", { tone: "success" });
            render();
            return;
          }
          const res = await api.updateDeck(deck.id, payload);
          if (!res.ok) {
            toast.show(res.error, { tone: "error" });
            return;
          }
          modal.close();
          toast.show("Mazo actualizado.", { tone: "success" });
          await refreshAll();
        },
      }),
    });
  },

  openDeckInspector(deckId) {
    const deck = state.decks.find((d) => d.id === deckId);
    if (!deck) return;
    const stats = state.deckStats[deckId] || { total: 0, due: 0, mastered: 0, cards: [] };

    modal.open({
      title: deck.name,
      wide: true,
      content: buildDeckInspectorContent({
        deck,
        cards: stats.cards || [],
        stats,
        onStudy: actions.startStudy,
        onClose: modal.close,
        onEditDeck: (d) => {
          modal.close();
          window.setTimeout(() => actions.openEditDeckModal(d), 180);
        },
        onDeleteDeck: (d) => {
          modal.open({
            title: "Eliminar mazo",
            content: h(
              "div",
              { className: "form-grid" },
              h("p", {
                style: "margin:0;color:var(--fg-secondary);",
                textContent: `¿Eliminar "${d.name}" y todas sus tarjetas asociadas? Esta acción no se puede deshacer.`,
              }),
              h(
                "div",
                { className: "form-actions" },
                h("button", { type: "button", className: "btn btn-ghost", onClick: modal.close }, "Cancelar"),
                h(
                  "button",
                  {
                    type: "button",
                    className: "btn btn-danger",
                    onClick: async () => {
                      if (state.demoMode) {
                        state.demoData.decks = state.demoData.decks.filter((x) => x.id !== d.id);
                        state.demoData.cards = state.demoData.cards.filter((c) => c.deck_id !== d.id);
                        state.decks = state.demoData.decks;
                        state.deckStats = computeDemoDeckStats(state.demoData);
                        modal.close();
                        toast.show("Mazo eliminado en memoria (Datos demo).");
                        render();
                        return;
                      }
                      const res = await api.deleteDeck(d.id);
                      if (!res.ok) {
                        toast.show(res.error, { tone: "error" });
                        return;
                      }
                      modal.close();
                      toast.show("Mazo eliminado.", { tone: "success" });
                      await refreshAll();
                    },
                  },
                  "Eliminar definitivamente"
                )
              )
            ),
          });
        },
        onEditCard: (card) => {
          actions.openEditCardModal(deckId, card);
        },
        onDeleteCard: async (cardId) => {
          if (state.demoMode) {
            state.demoData.cards = state.demoData.cards.filter((c) => c.id !== cardId);
            state.deckStats = computeDemoDeckStats(state.demoData);
            toast.show("Tarjeta eliminada en memoria (Datos demo).");
            actions.openDeckInspector(deckId);
            render();
            return;
          }
          const res = await api.deleteCard(cardId);
          if (!res.ok) {
            toast.show(res.error, { tone: "error" });
            return;
          }
          toast.show("Tarjeta eliminada.", { tone: "success" });
          await refreshDeckStats(state.decks);
          actions.openDeckInspector(deckId);
          render();
        },
      }),
    });
  },

  openEditCardModal(returnDeckId, card) {
    modal.open({
      title: `Editar tarjeta #${card.id}`,
      content: buildEditCardModalContent({
        card,
        decks: state.decks,
        onCancel: () => actions.openDeckInspector(returnDeckId),
        onSubmit: async (payload) => {
          if (state.demoMode) {
            const target = state.demoData.cards.find((c) => c.id === card.id);
            if (target) Object.assign(target, payload);
            state.deckStats = computeDemoDeckStats(state.demoData);
            toast.show("Tarjeta actualizada en memoria (Datos demo).", { tone: "success" });
            actions.openDeckInspector(payload.deck_id || returnDeckId);
            render();
            return;
          }
          const res = await api.updateCard(card.id, payload);
          if (!res.ok) {
            toast.show(res.error, { tone: "error" });
            return;
          }
          toast.show("Tarjeta actualizada.", { tone: "success" });
          await refreshDeckStats(state.decks);
          actions.openDeckInspector(res.data.deck_id || returnDeckId);
          render();
        },
      }),
    });
  },

  // Create cards & templates
  async generateCards(payload) {
    if (state.demoMode) {
      const created = [
        {
          id: nextDemoId(),
          deck_id: payload.deck_id,
          front: "Explain how you would debug this scenario in technical English.",
          back: `Demo generated card from: ${payload.text.slice(0, 120)}`,
          kind: "interview_phrase",
          source_label: "demo-generator",
          accepted_answers: [],
          explanation: "Generado solo en memoria (Datos demo).",
          error_id: null,
          repetitions: 0,
          interval_days: 0,
          ease_factor: 2.5,
          due_date: state.todayKey,
        },
      ];
      state.demoData.cards.unshift(...created);
      state.deckStats = computeDemoDeckStats(state.demoData);
      state.lastGeneratedCards = created;
      toast.show("1 tarjeta generada en memoria (Datos demo).", { tone: "success" });
      render();
      return true;
    }

    const res = await api.generateCards(payload);
    if (!res.ok) {
      toast.show(res.error, { tone: "error" });
      return false;
    }
    const created = Array.isArray(res.data) ? res.data : [];
    state.lastGeneratedCards = created;
    toast.show(`${pluralize(created.length, "tarjeta generada", "tarjetas generadas")} y listas hoy.`, {
      tone: "success",
    });
    await refreshDeckStats(state.decks);
    render();
    return true;
  },

  async createCard(payload) {
    if (state.demoMode) {
      const created = {
        id: nextDemoId(),
        ...payload,
        error_id: null,
        repetitions: 0,
        interval_days: 0,
        ease_factor: 2.5,
        due_date: state.todayKey,
      };
      state.demoData.cards.unshift(created);
      state.deckStats = computeDemoDeckStats(state.demoData);
      toast.show("Tarjeta guardada en memoria (Datos demo).", { tone: "success" });
      render();
      return true;
    }

    const res = await api.createCard(payload);
    if (!res.ok) {
      toast.show(res.error, { tone: "error" });
      return false;
    }
    toast.show("Tarjeta creada y programada para hoy.", { tone: "success" });
    await refreshDeckStats(state.decks);
    render();
    return true;
  },

  async addTemplateToDeck(templateId, deckId) {
    if (!deckId) {
      toast.show("Selecciona o crea un mazo primero.", { tone: "error" });
      return;
    }
    if (state.demoMode) {
      const tpl = state.templates.find((t) => t.id === templateId);
      if (tpl) {
        state.demoData.cards.unshift({
          id: nextDemoId(),
          deck_id: deckId,
          front: tpl.front,
          back: tpl.back,
          kind: tpl.kind,
          source_label: `template:${tpl.id}`,
          accepted_answers: [],
          explanation: tpl.explanation,
          error_id: null,
          repetitions: 0,
          interval_days: 0,
          ease_factor: 2.5,
          due_date: state.todayKey,
        });
        state.deckStats = computeDemoDeckStats(state.demoData);
        state.addedTemplateIds.add(templateId);
        toast.show("Plantilla añadida en memoria (Datos demo).", { tone: "success" });
        render();
      }
      return;
    }

    const res = await api.createCardFromTemplate(templateId, deckId);
    if (!res.ok) {
      toast.show(res.error, { tone: "error" });
      return;
    }
    state.addedTemplateIds.add(templateId);
    toast.show("Plantilla añadida al mazo.", { tone: "success" });
    await refreshDeckStats(state.decks);
    render();
  },

  // Sources
  async createSource(payload) {
    if (state.demoMode) {
      state.demoData.sources.unshift({
        id: nextDemoId(),
        label: payload.label,
        url: payload.url,
        normalized_url: payload.url,
        excerpt: payload.excerpt,
        status: "draft",
      });
      state.sources = state.demoData.sources;
      toast.show("Fuente guardada en memoria (Datos demo).", { tone: "success" });
      render();
      return true;
    }

    const res = await api.createSource(payload);
    if (!res.ok) {
      toast.show(res.error, { tone: "error" });
      return false;
    }
    toast.show("Fuente guardada como borrador.", { tone: "success" });
    await loadSources();
    return true;
  },

  openApproveSourceModal(source) {
    modal.open({
      title: "Aprobar fuente a tarjeta",
      content: buildApproveSourceModalContent({
        source,
        decks: state.decks,
        selectedDeckId: state.selectedDeckId,
        onCancel: modal.close,
        onApprove: async (payload) => {
          if (state.demoMode) {
            source.status = "approved";
            state.demoData.cards.unshift({
              id: nextDemoId(),
              ...payload,
              source_label: source.label,
              accepted_answers: [],
              error_id: null,
              repetitions: 0,
              interval_days: 0,
              ease_factor: 2.5,
              due_date: state.todayKey,
            });
            state.deckStats = computeDemoDeckStats(state.demoData);
            modal.close();
            toast.show("Fuente aprobada en memoria (Datos demo).", { tone: "success" });
            render();
            return;
          }
          const res = await api.approveSource(source.id, payload);
          if (!res.ok) {
            toast.show(res.error, { tone: "error" });
            if (res.status === 409) await loadSources();
            return;
          }
          modal.close();
          toast.show("Fuente aprobada y tarjeta creada.", { tone: "success" });
          await Promise.all([loadSources(), refreshDeckStats(state.decks)]);
          render();
        },
      }),
    });
  },

  openEditSourceModal(source) {
    modal.open({
      title: `Editar fuente #${source.id}`,
      content: buildEditSourceModalContent({
        source,
        onCancel: modal.close,
        onSubmit: async (payload) => {
          if (state.demoMode) {
            source.label = payload.label;
            source.url = payload.url;
            source.normalized_url = payload.url;
            source.excerpt = payload.excerpt;
            modal.close();
            toast.show("Fuente actualizada en memoria (Datos demo).", { tone: "success" });
            render();
            return;
          }
          const res = await api.updateSource(source.id, payload);
          if (!res.ok) {
            toast.show(res.error, { tone: "error" });
            if (res.status === 409) await loadSources();
            return;
          }
          modal.close();
          toast.show("Fuente actualizada.", { tone: "success" });
          await loadSources();
        },
      }),
    });
  },

  async discardSource(sourceId) {
    if (state.demoMode) {
      const s = state.demoData.sources.find((x) => x.id === sourceId);
      if (s) s.status = "discarded";
      toast.show("Fuente descartada en memoria (Datos demo).");
      render();
      return;
    }
    const res = await api.discardSource(sourceId);
    if (!res.ok) {
      toast.show(res.error, { tone: "error" });
      if (res.status === 409) await loadSources();
      return;
    }
    toast.show("Fuente descartada.");
    await loadSources();
  },

  async deleteSource(sourceId) {
    if (state.demoMode) {
      state.demoData.sources = state.demoData.sources.filter((x) => x.id !== sourceId);
      state.sources = state.demoData.sources;
      toast.show("Fuente eliminada en memoria (Datos demo).");
      render();
      return;
    }
    const res = await api.deleteSource(sourceId);
    if (!res.ok) {
      toast.show(res.error, { tone: "error" });
      return;
    }
    toast.show("Fuente eliminada.");
    await loadSources();
  },

  // Errors Kanban
  openCaptureErrorModal(prefill = {}) {
    modal.open({
      title: "Registrar error de entrevista",
      content: buildCaptureErrorModalContent({
        prefill,
        onCancel: modal.close,
        onSuggest: async (payload) => {
          if (state.demoMode) {
            state.demoData.errors.unshift({
              id: nextDemoId(),
              attempted: payload.prompt ? `Prompt: ${payload.prompt}\nAnswer: ${payload.answer}` : payload.answer,
              corrected: payload.corrected || `Refined: ${payload.answer}`,
              rationale:
                payload.category === "star"
                  ? "[STAR remediation] Borrador local en Datos demo."
                  : "[Technical remediation] Borrador local en Datos demo.",
              status: "draft",
              card_id: null,
            });
            state.errors = state.demoData.errors;
            modal.close();
            toast.show("Borrador de error creado en memoria (Datos demo).", { tone: "success" });
            render();
            return;
          }
          const res = await api.suggestError(payload);
          if (!res.ok) {
            toast.show(res.error, { tone: "error" });
            return;
          }
          modal.close();
          toast.show("Sugerencia creada en la columna Pendiente.", { tone: "success" });
          await loadErrors();
        },
        onManual: async (payload) => {
          if (state.demoMode) {
            state.demoData.errors.unshift({
              id: nextDemoId(),
              ...payload,
              status: "draft",
              card_id: null,
            });
            state.errors = state.demoData.errors;
            modal.close();
            toast.show("Error guardado en memoria (Datos demo).", { tone: "success" });
            render();
            return;
          }
          const res = await api.createError(payload);
          if (!res.ok) {
            toast.show(res.error, { tone: "error" });
            return;
          }
          modal.close();
          toast.show("Error añadido a Pendiente.", { tone: "success" });
          await loadErrors();
        },
      }),
    });
  },

  openApproveErrorModal(errorItem) {
    modal.open({
      title: `Aprobar ERR-${errorItem.id}`,
      content: buildApproveErrorModalContent({
        errorItem,
        decks: state.decks,
        selectedDeckId: state.selectedDeckId,
        onCancel: modal.close,
        onApprove: async (payload) => {
          if (state.demoMode) {
            const newCardId = nextDemoId();
            errorItem.status = "approved";
            errorItem.card_id = newCardId;
            state.demoData.cards.unshift({
              id: newCardId,
              ...payload,
              source_label: `error:${errorItem.id}`,
              accepted_answers: [],
              error_id: errorItem.id,
              repetitions: 0,
              interval_days: 0,
              ease_factor: 2.5,
              due_date: state.todayKey,
            });
            state.deckStats = computeDemoDeckStats(state.demoData);
            modal.close();
            toast.show("Error aprobado y tarjeta creada en memoria (Datos demo).", { tone: "success" });
            render();
            return;
          }
          const res = await api.approveError(errorItem.id, payload);
          if (!res.ok) {
            toast.show(res.error, { tone: "error" });
            if (res.status === 409) await loadErrors();
            return;
          }
          modal.close();
          toast.show(`Error aprobado → Tarjeta #${res.data.card.id} creada.`, { tone: "success" });
          await Promise.all([loadErrors(), refreshDeckStats(state.decks)]);
          render();
        },
      }),
    });
  },

  openEditErrorModal(errorItem) {
    modal.open({
      title: `Editar ERR-${errorItem.id}`,
      content: buildEditErrorModalContent({
        errorItem,
        onCancel: modal.close,
        onSubmit: async (payload) => {
          if (state.demoMode) {
            errorItem.attempted = payload.attempted;
            errorItem.corrected = payload.corrected;
            errorItem.rationale = payload.rationale;
            modal.close();
            toast.show("Error actualizado en memoria (Datos demo).", { tone: "success" });
            render();
            return;
          }
          const res = await api.updateError(errorItem.id, payload);
          if (!res.ok) {
            toast.show(res.error, { tone: "error" });
            if (res.status === 409) await loadErrors();
            return;
          }
          modal.close();
          toast.show("Error actualizado.", { tone: "success" });
          await loadErrors();
        },
      }),
    });
  },

  async discardError(errorId) {
    if (state.demoMode) {
      const err = state.demoData.errors.find((e) => e.id === errorId);
      if (err) err.status = "discarded";
      toast.show("Error movido a Descartado (Datos demo).");
      render();
      return;
    }
    const res = await api.discardError(errorId);
    if (!res.ok) {
      toast.show(res.error, { tone: "error" });
      if (res.status === 409) await loadErrors();
      return;
    }
    toast.show("Error descartado.");
    await loadErrors();
  },

  openDeleteErrorModal(err) {
    const deleteCardCheckbox = h("input", { type: "checkbox" });
    modal.open({
      title: `Eliminar ERR-${err.id}`,
      content: h(
        "div",
        { className: "form-grid" },
        h("p", {
          style: "margin:0;color:var(--fg-secondary);",
          textContent: "¿Quieres eliminar este registro de error de forma permanente?",
        }),
        err.card_id
          ? h(
              "label",
              { className: "checkbox-row" },
              deleteCardCheckbox,
              h("span", { textContent: `También eliminar la tarjeta asociada (#${err.card_id})` })
            )
          : null,
        h(
          "div",
          { className: "form-actions" },
          h("button", { type: "button", className: "btn btn-ghost", onClick: modal.close }, "Cancelar"),
          h(
            "button",
            {
              type: "button",
              className: "btn btn-danger",
              onClick: async () => {
                const delCard = Boolean(deleteCardCheckbox.checked);
                if (state.demoMode) {
                  state.demoData.errors = state.demoData.errors.filter((e) => e.id !== err.id);
                  if (delCard && err.card_id) {
                    state.demoData.cards = state.demoData.cards.filter((c) => c.id !== err.card_id);
                  }
                  state.errors = state.demoData.errors;
                  state.deckStats = computeDemoDeckStats(state.demoData);
                  modal.close();
                  toast.show("Error eliminado en memoria (Datos demo).");
                  render();
                  return;
                }
                const res = await api.deleteError(err.id, delCard);
                if (!res.ok) {
                  toast.show(res.error, { tone: "error" });
                  return;
                }
                modal.close();
                toast.show("Error eliminado.", { tone: "success" });
                await Promise.all([loadErrors(), refreshDeckStats(state.decks)]);
                render();
              },
            },
            "Eliminar"
          )
        )
      ),
    });
  },

  async exportErrors() {
    if (state.demoMode) {
      const payload = {
        exported_at: new Date().toISOString(),
        demo_mode: true,
        count: state.errors.length,
        items: state.errors,
      };
      downloadJson(payload, `techcards-errors-demo-${state.todayKey}.json`);
      toast.show("Exportación demo descargada.");
      return;
    }
    const res = await api.exportErrors();
    if (!res.ok) {
      toast.show(res.error, { tone: "error" });
      return;
    }
    downloadJson(res.data, `techcards-errors-${state.todayKey}.json`);
    toast.show(`Exportados ${pluralize(res.data.count, "error", "errores")} en JSON.`, {
      tone: "success",
    });
  },

  // Analytics filters
  applyAnalyticsPreset(preset) {
    state.analytics.preset = preset;
    if (preset === "all") {
      state.analytics.start = "";
      state.analytics.end = "";
    } else if (preset === "7d") {
      state.analytics.start = addDaysToKey(state.todayKey, -6);
      state.analytics.end = state.todayKey;
    } else if (preset === "30d") {
      state.analytics.start = addDaysToKey(state.todayKey, -29);
      state.analytics.end = state.todayKey;
    } else if (preset === "84d") {
      state.analytics.start = addDaysToKey(state.todayKey, -83);
      state.analytics.end = state.todayKey;
    }
    loadAnalytics();
  },

  applyAnalyticsRange(start, end) {
    state.analytics.preset = "custom";
    state.analytics.start = start;
    state.analytics.end = end;
    loadAnalytics();
  },
};

function downloadJson(data, filename) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/* ==========================================================================
   Global Event Listeners & Keyboard Shortcuts
   ========================================================================== */

document.querySelectorAll("[data-view]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const view = btn.dataset.view;
    if (view === "study") {
      actions.startStudy(state.selectedDeckId || state.decks[0]?.id || "");
    } else {
      actions.navigate(view);
    }
  });
});

document.getElementById("sidebar-cmd-btn")?.addEventListener("click", openCommandPalette);
document.getElementById("mobile-cmd-btn")?.addEventListener("click", openCommandPalette);
themeToggleBtn?.addEventListener("click", toggleTheme);
document.getElementById("mobile-theme-btn")?.addEventListener("click", toggleTheme);
document.getElementById("mobile-demo-btn")?.addEventListener("click", () => {
  actions.setDemoMode(!state.demoMode);
});
document.getElementById("exit-demo-btn")?.addEventListener("click", () => {
  actions.setDemoMode(false);
});
demoToggleEl?.addEventListener("change", (e) => {
  actions.setDemoMode(e.target.checked);
});
document.querySelectorAll("[data-demo-variant]").forEach((btn) => {
  btn.addEventListener("click", () => actions.setDemoVariant(btn.dataset.demoVariant));
});

document.addEventListener("keydown", (e) => {
  // Ctrl/Cmd + K opens Command Palette everywhere
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
    e.preventDefault();
    if (cmdBackdrop.hidden) openCommandPalette();
    else closeCommandPalette();
    return;
  }

  // Ignore shortcuts when palette or modal is open, or user is typing in a field
  if (!cmdBackdrop.hidden || modal.isOpen()) return;
  const tag = document.activeElement?.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || document.activeElement?.isContentEditable) {
    return;
  }

  if (state.view === "study") {
    if (e.key === "Escape") {
      e.preventDefault();
      actions.navigate("dashboard");
      return;
    }
    if (e.code === "Space" && state.study.card && !state.study.reveal) {
      e.preventDefault();
      actions.revealStudyCard();
      return;
    }
    if (/^[0-5]$/.test(e.key) && state.study.card && state.study.reveal && !state.study.grading) {
      e.preventDefault();
      actions.gradeStudyCard(Number(e.key));
    }
  }
});

/* ==========================================================================
   Bootstrap
   ========================================================================== */

function init() {
  hydrateIcons();
  if (cmdShortcutHint) {
    cmdShortcutHint.textContent = isMac ? "⌘K" : "Ctrl K";
  }
  initTheme();

  const params = new URLSearchParams(window.location.search);
  const dataParam = params.get("data");
  if (dataParam === "demo" || dataParam === "worst") {
    loadDemoDataset(dataParam);
    return;
  }

  render();
  refreshAll();
}

init();
