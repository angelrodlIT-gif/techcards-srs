/**
 * View renderers and modals for TechCards ("Cabina de entrenamiento").
 * Every user-supplied string is rendered via textContent (never innerHTML).
 */

import {
  createDeckTile,
  createEmptyState,
  createHeatmapCard,
  createIcon,
  createProgressRing,
  h,
  renderPromptText,
} from "./components.js";
import {
  clampPercent,
  formatCompactCount,
  formatDurationSeconds,
  formatEase,
  formatInt,
  formatIsoDate,
  formatPercent,
  formatTimestamp,
  getGreeting,
  GRADE_META,
  KIND_META,
  kindLabel,
  pluralize,
  truncateMiddle,
} from "./format.js";

const KIND_OPTIONS = Object.entries(KIND_META).map(([value, meta]) => ({
  value,
  label: meta.label,
}));

function buildDeckOptions(decks, selectedId = "") {
  return decks.map((deck) =>
    h("option", {
      value: deck.id,
      selected: deck.id === selectedId,
      textContent: deck.name,
    })
  );
}

/* ==========================================================================
   View 1 · Cabina (Inicio / Dashboard)
   ========================================================================== */

export function renderDashboardView(ctx) {
  const { state, actions } = ctx;

  if (state.loadingInitial) {
    return h(
      "div",
      { className: "dashboard-stack", "aria-busy": "true" },
      h("div", { className: "skeleton-block", style: "height: 184px" }),
      h("div", { className: "skeleton-heatmap" }),
      h(
        "div",
        { className: "deck-grid" },
        h("div", { className: "skeleton-card" }),
        h("div", { className: "skeleton-card" }),
        h("div", { className: "skeleton-card" })
      )
    );
  }

  if (state.loadError && state.decks.length === 0) {
    return h(
      "div",
      { className: "dashboard-stack" },
      h(
        "div",
        { className: "inline-error-box", role: "alert" },
        h("span", { textContent: state.loadError }),
        h(
          "button",
          { type: "button", className: "btn btn-secondary btn-sm", onClick: actions.refreshAll },
          createIcon("refresh", 14),
          "Reintentar"
        )
      ),
      createEmptyState({
        icon: "alert",
        title: "No pudimos cargar tus mazos",
        description:
          "Comprueba que el servidor FastAPI esté escuchando o activa 'Datos demo' para explorar la interfaz en modo de solo lectura.",
        actions: [
          h(
            "button",
            { type: "button", className: "btn btn-primary", onClick: actions.refreshAll },
            "Reintentar conexión"
          ),
          h(
            "button",
            { type: "button", className: "btn btn-secondary", onClick: () => actions.setDemoMode(true) },
            "Activar Datos demo"
          ),
        ],
      })
    );
  }

  const totalDue = state.decks.reduce((acc, d) => acc + (state.deckStats[d.id]?.due ?? 0), 0);
  const firstDueDeck = state.decks.find((d) => (state.deckStats[d.id]?.due ?? 0) > 0) || state.decks[0];
  const todayReviewed = state.heatmap.counts[state.todayKey] || 0;
  const sessionCompleted = Math.max(todayReviewed, state.sessionCompletedToday);

  const hero = h(
    "section",
    { className: "cockpit-hero", "aria-label": "Resumen diario de entrenamiento" },
    h(
      "div",
      { className: "hero-copy" },
      h("p", {
        className: "hero-greeting",
        textContent: `${getGreeting()} · Cabina de entrevistas remotas IT`,
      }),
      h(
        "div",
        { className: "hero-due-row" },
        h("span", {
          className: "hero-due-number tabular",
          textContent: formatCompactCount(totalDue),
          title: pluralize(totalDue, "tarjeta pendiente hoy", "tarjetas pendientes hoy"),
        }),
        h("span", {
          className: "hero-due-label",
          textContent: totalDue === 1 ? "tarjeta toca hoy" : "tarjetas tocan hoy",
        })
      ),
      h(
        "div",
        { className: "hero-cta-row" },
        firstDueDeck
          ? h(
              "button",
              {
                type: "button",
                className: "btn btn-primary btn-lg",
                onClick: () => actions.startStudy(firstDueDeck.id),
              },
              createIcon("focus", 16),
              totalDue > 0 ? "Iniciar sesión de hoy" : "Practicar mazo"
            )
          : h(
              "button",
              {
                type: "button",
                className: "btn btn-primary btn-lg",
                onClick: actions.openNewDeckModal,
              },
              createIcon("create", 16),
              "Crear primer mazo"
            ),
        h(
          "button",
          {
            type: "button",
            className: "btn btn-secondary btn-lg",
            onClick: () => actions.navigate("create", { tab: "generate" }),
          },
          createIcon("sparkles", 15),
          "Generar tarjetas"
        ),
        h(
          "button",
          {
            type: "button",
            className: "btn btn-ghost btn-lg hero-cmd-btn",
            onClick: actions.openCommandPalette,
          },
          "Comandos ",
          h("kbd", { className: "kbd", textContent: state.isMac ? "⌘K" : "Ctrl K" })
        )
      )
    ),
    h(
      "div",
      { className: "hero-ring-card" },
      createProgressRing({ completed: sessionCompleted, remaining: totalDue }),
      h(
        "div",
        { className: "hero-ring-caption" },
        totalDue === 0 && sessionCompleted > 0
          ? "Sesión de hoy completa"
          : `Hoy: ${pluralize(sessionCompleted, "repaso", "repasos")}`
      )
    )
  );

  const heatmap = createHeatmapCard({
    dateKeys: state.heatmap.dateKeys,
    counts: state.heatmap.counts,
    loading: state.heatmap.loading,
    error: state.heatmap.error,
    isDemo: state.demoMode,
    onRetry: actions.refreshHeatmap,
  });

  const deckHeader = h(
    "div",
    { className: "section-bar" },
    h("h2", {
      className: "section-heading",
      textContent: `Mazos (${formatInt(state.decks.length)})`,
    }),
    h(
      "div",
      { className: "view-actions" },
      h(
        "button",
        { type: "button", className: "btn btn-ghost btn-sm", onClick: actions.refreshAll },
        createIcon("refresh", 14),
        "Actualizar"
      ),
      h(
        "button",
        { type: "button", className: "btn btn-primary btn-sm", onClick: actions.openNewDeckModal },
        createIcon("create", 14),
        "Nuevo mazo"
      )
    )
  );

  let deckSection;
  if (state.decks.length === 0) {
    deckSection = createEmptyState({
      icon: "layers",
      title: "Tu cabina aún no tiene mazos",
      description:
        "Crea un mazo para tu próxima entrevista (por ejemplo, 'Cloud interviews') o añade preguntas desde la galería de plantillas STAR y Networking.",
      actions: [
        h(
          "button",
          { type: "button", className: "btn btn-primary", onClick: actions.openNewDeckModal },
          createIcon("create", 15),
          "Crear mazo"
        ),
        h(
          "button",
          {
            type: "button",
            className: "btn btn-secondary",
            onClick: () => actions.navigate("create", { tab: "templates" }),
          },
          "Explorar plantillas"
        ),
      ],
    });
  } else {
    const tiles = state.decks.map((deck) => {
      const stats = state.deckStats[deck.id] || { due: 0, total: 0, mastered: 0 };
      return createDeckTile({
        deck,
        dueCount: stats.due,
        totalCount: stats.total,
        masteredCount: stats.mastered,
        onStudy: actions.startStudy,
        onInspect: actions.openDeckInspector,
      });
    });
    deckSection = h("div", { className: "deck-grid" }, ...tiles);
  }

  return h(
    "div",
    { className: "dashboard-stack" },
    state.loadError
      ? h("div", { className: "inline-error-box", role: "alert" }, state.loadError)
      : null,
    hero,
    heatmap,
    deckHeader,
    deckSection
  );
}

/* ==========================================================================
   View 2 · Modo Foco (Full-Screen Recall-First Study Session)
   ========================================================================== */

export function renderStudyView(ctx) {
  const { state, actions } = ctx;
  const study = state.study;
  const activeDeck = state.decks.find((d) => d.id === study.deckId);

  const completed = study.sessionHistory.length;
  const totalInSession = Math.max(study.initialDueCount, completed + (study.card ? 1 : 0));
  const progressRatio = totalInSession > 0 ? Math.min(1, completed / totalInSession) : 0;

  const topbar = h(
    "header",
    { className: "focus-topbar" },
    h(
      "div",
      { className: "focus-topbar-left" },
      h(
        "button",
        {
          type: "button",
          className: "btn btn-ghost btn-sm",
          onClick: () => actions.navigate("dashboard"),
          "aria-label": "Salir del modo foco (Escape)",
        },
        createIcon("arrow-left", 15),
        "Salir"
      ),
      state.decks.length > 0
        ? h(
            "select",
            {
              className: "focus-deck-select",
              "aria-label": "Seleccionar mazo para estudiar",
              onChange: (e) => actions.startStudy(e.target.value, { keepFilters: true }),
            },
            ...buildDeckOptions(state.decks, study.deckId)
          )
        : null
    ),
    h(
      "div",
      { className: "focus-topbar-right" },
      h(
        "select",
        {
          className: "focus-filter-select",
          "aria-label": "Filtrar por tipo de tarjeta",
          onChange: (e) => actions.setStudyFilter({ kind: e.target.value }),
        },
        h("option", { value: "", selected: !study.filterKind, textContent: "Todos los tipos" }),
        ...KIND_OPTIONS.map((opt) =>
          h("option", {
            value: opt.value,
            selected: study.filterKind === opt.value,
            textContent: opt.label,
          })
        )
      ),
      h(
        "button",
        {
          type: "button",
          className: `btn btn-sm ${study.remediationOnly ? "btn-primary" : "btn-ghost"}`,
          "aria-pressed": String(study.remediationOnly),
          onClick: () => actions.setStudyFilter({ remediationOnly: !study.remediationOnly }),
        },
        "Solo errores"
      ),
      h("span", {
        className: "stat-pill tabular",
        textContent:
          totalInSession > 0
            ? `${formatInt(completed)} / ${formatInt(totalInSession)}`
            : `${formatInt(completed)} repasadas`,
      })
    )
  );

  let stageContent;

  if (state.decks.length === 0) {
    stageContent = createEmptyState({
      icon: "layers",
      title: "Necesitas al menos un mazo para estudiar",
      description: "Crea un mazo primero o activa Datos demo para probar el modo foco.",
      actions: [
        h(
          "button",
          { type: "button", className: "btn btn-primary", onClick: actions.openNewDeckModal },
          "Crear mazo"
        ),
        h(
          "button",
          { type: "button", className: "btn btn-secondary", onClick: () => actions.navigate("dashboard") },
          "Volver a la cabina"
        ),
      ],
    });
  } else if (study.loading) {
    stageContent = h(
      "div",
      { className: "study-card", "aria-busy": "true" },
      h("div", { className: "skeleton-block", style: "height: 24px; width: 180px" }),
      h("div", { className: "skeleton-block", style: "height: 110px" }),
      h("div", { className: "skeleton-block", style: "height: 46px; width: 220px" })
    );
  } else if (study.error) {
    stageContent = h(
      "div",
      { className: "study-card" },
      h(
        "div",
        { className: "inline-error-box", role: "alert" },
        h("span", { textContent: study.error }),
        h(
          "button",
          { type: "button", className: "btn btn-secondary btn-sm", onClick: actions.loadNextStudyCard },
          "Reintentar"
        )
      )
    );
  } else if (!study.card && study.sessionHistory.length > 0) {
    // Session Summary Screen (Rare / Delight tier)
    const passed = study.sessionHistory.filter((r) => r.quality >= 3).length;
    const recallPct = formatPercent(passed, study.sessionHistory.length);
    const avgQuality = (
      study.sessionHistory.reduce((acc, r) => acc + r.quality, 0) / study.sessionHistory.length
    ).toFixed(1);

    const distCounts = [0, 0, 0, 0, 0, 0];
    study.sessionHistory.forEach((r) => {
      distCounts[r.quality] = (distCounts[r.quality] || 0) + 1;
    });

    stageContent = h(
      "section",
      { className: "summary-card", "aria-label": "Resumen de la sesión" },
      h(
        "div",
        { className: "summary-lead" },
        h("div", { className: "summary-badge" }, createIcon("check", 24)),
        h(
          "div",
          null,
          h("span", { className: "view-eyebrow", textContent: "Sesión completada" }),
          h("h1", {
            className: "view-title",
            textContent: activeDeck ? activeDeck.name : "Entrenamiento completado",
          })
        )
      ),
      h(
        "div",
        { className: "summary-stats" },
        h(
          "div",
          { className: "summary-stat-box" },
          h("span", { className: "summary-stat-value tabular", textContent: formatInt(completed) }),
          h("span", { className: "summary-stat-label", textContent: completed === 1 ? "Tarjeta repasada" : "Tarjetas repasadas" })
        ),
        h(
          "div",
          { className: "summary-stat-box" },
          h("span", { className: "summary-stat-value tabular", textContent: recallPct }),
          h("span", { className: "summary-stat-label", textContent: "Recuerdo (≥ 3)" })
        ),
        h(
          "div",
          { className: "summary-stat-box" },
          h("span", { className: "summary-stat-value tabular", textContent: `${avgQuality} / 5` }),
          h("span", { className: "summary-stat-label", textContent: "Calificación media" })
        )
      ),
      h(
        "div",
        { className: "summary-dist" },
        ...GRADE_META.map((g) => {
          const c = distCounts[g.quality];
          const pct = clampPercent(c, study.sessionHistory.length);
          return h(
            "div",
            { className: "summary-dist-row" },
            h("span", { className: "tabular muted", textContent: `${g.quality} · ${g.label}` }),
            h(
              "div",
              { className: "meter-track" },
              h("div", {
                className: "meter-fill",
                style: `transform: scaleX(${(pct / 100).toFixed(4)})`,
              })
            ),
            h("span", { className: "tabular", style: "text-align:right", textContent: formatInt(c) })
          );
        })
      ),
      h(
        "div",
        { className: "summary-actions" },
        h(
          "button",
          {
            type: "button",
            className: "btn btn-primary btn-lg",
            onClick: () => actions.navigate("dashboard"),
          },
          "Volver a la cabina"
        ),
        h(
          "button",
          {
            type: "button",
            className: "btn btn-secondary btn-lg",
            onClick: () => actions.navigate("analytics"),
          },
          "Ver analítica"
        ),
        h(
          "button",
          {
            type: "button",
            className: "btn btn-ghost btn-lg",
            onClick: () => actions.navigate("create", { tab: "generate" }),
          },
          "Añadir tarjetas"
        )
      )
    );
  } else if (!study.card) {
    const filterMsg =
      study.filterKind || study.remediationOnly
        ? "No hay tarjetas pendientes con los filtros actuales."
        : "No quedan tarjetas programadas para hoy en este mazo.";
    stageContent = createEmptyState({
      icon: "check",
      title: "Mazo al día",
      description: filterMsg,
      actions: [
        study.filterKind || study.remediationOnly
          ? h(
              "button",
              {
                type: "button",
                className: "btn btn-primary",
                onClick: () => actions.setStudyFilter({ kind: "", remediationOnly: false }),
              },
              "Quitar filtros"
            )
          : null,
        h(
          "button",
          {
            type: "button",
            className: "btn btn-primary",
            onClick: () => actions.navigate("create", { tab: "generate" }),
          },
          createIcon("sparkles", 15),
          "Generar nuevas tarjetas"
        ),
        h(
          "button",
          {
            type: "button",
            className: "btn btn-secondary",
            onClick: () => actions.navigate("dashboard"),
          },
          "Volver a la cabina"
        ),
      ].filter(Boolean),
    });
  } else {
    const card = study.card;
    const isRevealed = Boolean(study.reveal && card && study.reveal.card_id === card.card_id);

    const cardEl = h(
      "article",
      { className: "study-card", "aria-label": "Tarjeta de estudio actual" },
      h(
        "div",
        { className: "study-card-meta" },
        h(
          "div",
          { className: "study-card-badges" },
          h("span", { className: "kind-chip kind-chip-accent", textContent: kindLabel(card.kind) }),
          card.source_label
            ? h("span", {
                className: "kind-chip",
                title: card.source_label,
                textContent: truncateMiddle(card.source_label, 34),
              })
            : null,
          card.error_id
            ? h("span", { className: "kind-chip kind-chip-warn", textContent: "Remediación" })
            : null
        ),
        h("span", {
          className: "study-srs-meta tabular",
          textContent: `Rep ${formatInt(card.repetitions)} · Int ${pluralize(card.interval_days, "día", "días")} · EF ${formatEase(card.ease_factor)}`,
        })
      ),
      h("h1", { className: "study-prompt" }, renderPromptText(card.front, card.kind)),
      card.kind === "listening"
        ? h(
            "div",
            { className: "study-audio-row" },
            h(
              "button",
              {
                type: "button",
                className: "btn btn-secondary btn-sm",
                disabled: study.audioLoading,
                onClick: actions.loadListeningAudio,
              },
              createIcon("volume", 15),
              study.audioLoading ? "Sintetizando audio…" : "Escuchar audio (opt-in)"
            ),
            study.audioUrl
              ? h("audio", {
                  className: "study-audio-player",
                  controls: true,
                  src: study.audioUrl,
                })
              : null,
            study.audioError
              ? h("span", { className: "field-error", role: "alert", textContent: study.audioError })
              : null
          )
        : null,
      !isRevealed
        ? h(
            "div",
            { className: "study-reveal-prompt" },
            h("span", {
              className: "study-recall-hint",
              textContent: "Formula tu respuesta en voz alta antes de revelar.",
            }),
            h(
              "button",
              {
                type: "button",
                id: "reveal-btn",
                className: "btn btn-primary btn-lg",
                disabled: study.revealing,
                onClick: actions.revealStudyCard,
              },
              study.revealing ? "Revelando…" : "Revelar respuesta",
              h("kbd", { className: "kbd", textContent: "Espacio" })
            )
          )
        : h(
            "div",
            { className: "study-answer-panel", "aria-live": "polite" },
            h("span", { className: "study-answer-eyebrow", textContent: "Respuesta de referencia" }),
            h("p", { className: "study-answer-text", dir: "auto", textContent: study.reveal.back }),
            study.reveal.accepted_answers?.length
              ? h(
                  "div",
                  { className: "field" },
                  h("span", { className: "field-hint", textContent: "Variantes aceptadas" }),
                  h(
                    "div",
                    { className: "accepted-list" },
                    ...study.reveal.accepted_answers.map((ans) =>
                      h("span", { className: "accepted-chip", dir: "auto", textContent: ans })
                    )
                  )
                )
              : null,
            study.reveal.explanation
              ? h("p", {
                  className: "study-explanation",
                  dir: "auto",
                  textContent: study.reveal.explanation,
                })
              : null,
            h(
              "div",
              { className: "study-answer-footer" },
              h(
                "button",
                {
                  type: "button",
                  className: "btn btn-ghost btn-sm",
                  onClick: () =>
                    actions.openCaptureErrorModal({
                      prompt: card.front,
                      corrected: study.reveal.back,
                    }),
                },
                "Registrar error de esta pregunta"
              )
            )
          )
    );

    const gradeDock = isRevealed
      ? h(
          "div",
          { className: "grade-dock", role: "group", "aria-label": "Calificar recuerdo del 0 al 5" },
          ...GRADE_META.map((g) =>
            h(
              "button",
              {
                type: "button",
                className: "grade-btn",
                dataset: { tone: g.tone, quality: g.quality },
                disabled: study.grading,
                onClick: () => actions.gradeStudyCard(g.quality),
              },
              h("span", { className: "grade-key tabular", textContent: String(g.quality) }),
              h("span", { className: "grade-label", textContent: g.label }),
              h("span", { className: "grade-hint", textContent: g.hint })
            )
          )
        )
      : null;

    stageContent = h("div", { style: "width:100%;display:flex;flex-direction:column;align-items:center;" }, cardEl, gradeDock);
  }

  const shortcutBar = h(
    "footer",
    { className: "focus-shortcut-bar", "aria-label": "Atajos de teclado" },
    h("span", { className: "shortcut-item" }, h("kbd", { className: "kbd", textContent: "Espacio" }), "Revelar"),
    h("span", { className: "shortcut-item" }, h("kbd", { className: "kbd", textContent: "0–5" }), "Calificar"),
    h("span", { className: "shortcut-item" }, h("kbd", { className: "kbd", textContent: state.isMac ? "⌘K" : "Ctrl K" }), "Comandos"),
    h("span", { className: "shortcut-item" }, h("kbd", { className: "kbd", textContent: "Esc" }), "Salir")
  );

  return h(
    "div",
    { className: "focus-shell" },
    h(
      "div",
      { className: "focus-progress-rail", "aria-hidden": "true" },
      h("div", {
        className: "focus-progress-bar",
        style: `transform: scaleX(${progressRatio.toFixed(4)})`,
      })
    ),
    topbar,
    h("div", { className: "focus-stage" }, stageContent),
    shortcutBar
  );
}

/* ==========================================================================
   View 3 · Crear Contenido (Generate, Manual/Decks, Templates, Sources)
   ========================================================================== */

export function renderCreateView(ctx) {
  const { state, actions } = ctx;
  const tab = state.createTab || "generate";

  const tabs = [
    { id: "generate", label: "Generar desde texto" },
    { id: "manual", label: "Tarjeta manual" },
    { id: "templates", label: `Plantillas (${formatInt(state.templates.length)})` },
    { id: "sources", label: `Fuentes (${formatInt(state.sources.length)})` },
  ];

  const header = h(
    "div",
    { className: "view-header" },
    h(
      "div",
      null,
      h("span", { className: "view-eyebrow", textContent: "Estudio de contenido" }),
      h("h1", { className: "view-title", textContent: "Crear y curar material" }),
      h("p", {
        className: "view-desc",
        textContent:
          "Genera tarjetas desde notas técnicas, añade plantillas STAR/Networking o aprueba fuentes reales hacia tus mazos.",
      })
    ),
    h(
      "div",
      { className: "view-actions" },
      h(
        "button",
        { type: "button", className: "btn btn-secondary", onClick: actions.openNewDeckModal },
        createIcon("create", 15),
        "Nuevo mazo"
      )
    )
  );

  const tabBar = h(
    "div",
    { className: "segmented", role: "tablist", "aria-label": "Secciones de creación" },
    ...tabs.map((t) =>
      h(
        "button",
        {
          type: "button",
          role: "tab",
          className: "segment-btn",
          "aria-selected": String(tab === t.id),
          onClick: () => actions.setCreateTab(t.id),
        },
        t.label
      )
    )
  );

  let body;
  if (tab === "generate") body = renderGenerateTab(ctx);
  else if (tab === "manual") body = renderManualCardTab(ctx);
  else if (tab === "templates") body = renderTemplatesTab(ctx);
  else body = renderSourcesTab(ctx);

  return h("div", { className: "studio-stack" }, header, tabBar, body);
}

function renderGenerateTab(ctx) {
  const { state, actions } = ctx;
  const selectedDeckId = state.selectedDeckId || state.decks[0]?.id || "";
  const charCounter = h("span", { className: "field-hint tabular", textContent: "0 / 20,000" });
  const errorBox = h("p", { className: "field-error", hidden: true });

  const deckSelect = h(
    "select",
    { className: "select", name: "deck_id", required: true, disabled: state.decks.length === 0 },
    ...buildDeckOptions(state.decks, selectedDeckId)
  );
  const maxInput = h("input", {
    className: "input tabular",
    type: "number",
    name: "max_cards",
    inputmode: "numeric",
    min: "1",
    max: "20",
    value: "6",
    required: true,
  });
  const textArea = h("textarea", {
    className: "textarea",
    name: "text",
    rows: "7",
    required: true,
    minlength: "10",
    maxlength: "20000",
    placeholder:
      "Pega aquí una descripción de puesto, notas de AWS, PostgreSQL, Docker, Linux o un incidente real (mínimo 10 caracteres)…",
    onInput: (e) => {
      const len = e.target.value.trim().length;
      charCounter.textContent = `${formatInt(len)} / 20,000`;
      if (len >= 10) errorBox.hidden = true;
    },
  });

  const submitBtn = h(
    "button",
    { type: "submit", className: "btn btn-primary", disabled: state.decks.length === 0 },
    createIcon("sparkles", 15),
    "Generar tarjetas"
  );

  const form = h(
    "form",
    {
      className: "panel form-grid",
      onSubmit: async (e) => {
        e.preventDefault();
        const text = textArea.value.trim();
        if (text.length < 10) {
          errorBox.textContent = "Escribe al menos 10 caracteres para generar tarjetas.";
          errorBox.hidden = false;
          textArea.focus();
          return;
        }
        errorBox.hidden = true;
        submitBtn.disabled = true;
        submitBtn.textContent = "Generando…";
        const ok = await actions.generateCards({
          deck_id: deckSelect.value,
          text,
          max_cards: Math.max(1, Math.min(20, Number(maxInput.value) || 6)),
        });
        submitBtn.disabled = false;
        submitBtn.replaceChildren(createIcon("sparkles", 15), "Generar tarjetas");
        if (ok) {
          textArea.value = "";
          charCounter.textContent = "0 / 20,000";
        }
      },
    },
    h(
      "div",
      { className: "panel-title-group" },
      h("h2", { className: "panel-title", textContent: "Generador desde texto" }),
      h("p", {
        className: "panel-subtitle",
        textContent: "Usa POST /cards/generate para crear tarjetas listas para estudiar hoy.",
      })
    ),
    state.decks.length === 0
      ? h(
          "div",
          { className: "inline-error-box" },
          h("span", { textContent: "Crea un mazo antes de generar tarjetas." }),
          h(
            "button",
            { type: "button", className: "btn btn-primary btn-sm", onClick: actions.openNewDeckModal },
            "Crear mazo"
          )
        )
      : null,
    h(
      "div",
      { className: "form-row-2" },
      h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Mazo destino" }), deckSelect),
      h(
        "div",
        { className: "field" },
        h("label", { className: "field-label", textContent: "Máximo de tarjetas (1–20)" }),
        maxInput
      )
    ),
    h(
      "div",
      { className: "field" },
      h("div", { className: "field-label-row" }, h("label", { className: "field-label", textContent: "Texto fuente" }), charCounter),
      textArea,
      errorBox
    ),
    h("div", { className: "form-actions" }, submitBtn)
  );

  const recentPanel = h(
    "section",
    { className: "panel" },
    h(
      "div",
      { className: "panel-header" },
      h(
        "div",
        { className: "panel-title-group" },
        h("h2", { className: "panel-title", textContent: "Últimas tarjetas generadas" }),
        h("p", {
          className: "panel-subtitle",
          textContent: state.lastGeneratedCards.length
            ? pluralize(state.lastGeneratedCards.length, "tarjeta creada", "tarjetas creadas")
            : "Aquí verás las tarjetas recién creadas.",
        })
      ),
      state.lastGeneratedCards.length
        ? h(
            "button",
            {
              type: "button",
              className: "btn btn-secondary btn-sm",
              onClick: () => actions.startStudy(state.lastGeneratedCards[0].deck_id),
            },
            createIcon("focus", 14),
            "Estudiar ahora"
          )
        : null
    ),
    state.lastGeneratedCards.length
      ? h(
          "div",
          { className: "card-preview-list" },
          ...state.lastGeneratedCards.map((c) =>
            h(
              "article",
              { className: "card-preview-item" },
              h(
                "div",
                { className: "card-preview-head" },
                h("span", { className: "kind-chip kind-chip-accent", textContent: kindLabel(c.kind) }),
                h("span", { className: "mono muted", style: "font-size:12px", textContent: `#${c.id}` })
              ),
              h("p", { className: "card-preview-front", dir: "auto", textContent: c.front }),
              h("p", { className: "card-preview-back", dir: "auto", textContent: c.back })
            )
          )
        )
      : createEmptyState({
          icon: "sparkles",
          title: "Sin generación reciente",
          description: "Pega un texto técnico a la izquierda para extraer preguntas de entrevista y vocabulario.",
        })
  );

  return h("div", { className: "studio-split" }, form, recentPanel);
}

function renderManualCardTab(ctx) {
  const { state, actions } = ctx;
  const selectedDeckId = state.selectedDeckId || state.decks[0]?.id || "";
  const validationHint = h("p", { className: "field-error", hidden: true });

  const deckSelect = h(
    "select",
    { className: "select", name: "deck_id", required: true, disabled: state.decks.length === 0 },
    ...buildDeckOptions(state.decks, selectedDeckId)
  );
  const kindSelect = h(
    "select",
    { className: "select", name: "kind" },
    ...KIND_OPTIONS.map((opt) => h("option", { value: opt.value, textContent: opt.label }))
  );
  const frontInput = h("textarea", {
    className: "textarea",
    rows: "3",
    required: true,
    placeholder: "Pregunta o frase en inglés/español (para Cloze usa exactamente un ____)",
  });
  const backInput = h("textarea", {
    className: "textarea",
    rows: "3",
    required: true,
    placeholder: "Respuesta esperada o transcripción (máx. 1,000 caracteres si es Listening)",
  });
  const acceptedInput = h("textarea", {
    className: "textarea",
    rows: "2",
    placeholder: "Respuestas alternativas aceptadas (una por línea, opcional)",
  });
  const explanationInput = h("textarea", {
    className: "textarea",
    rows: "2",
    placeholder: "Nota técnica o recordatorio de pronunciación/contexto (opcional)",
  });
  const sourceLabelInput = h("input", {
    className: "input",
    type: "text",
    maxlength: "255",
    placeholder: "Etiqueta de origen (opcional, ej. AWS VPC Docs)",
  });

  function validateInline() {
    const kind = kindSelect.value;
    const front = frontInput.value.trim();
    const back = backInput.value.trim();
    if (kind === "cloze") {
      const blanks = front.match(/_{4,}/g) || [];
      if (blanks.length !== 1 || blanks[0] !== "____") {
        validationHint.textContent = "Las tarjetas Cloze requieren exactamente un hueco '____' en el anverso.";
        validationHint.hidden = false;
        return false;
      }
    }
    if (kind === "listening" && back.length > 1000) {
      validationHint.textContent = "Las tarjetas Listening permiten máximo 1,000 caracteres en la transcripción.";
      validationHint.hidden = false;
      return false;
    }
    validationHint.hidden = true;
    return true;
  }

  kindSelect.addEventListener("change", validateInline);
  frontInput.addEventListener("input", validateInline);
  backInput.addEventListener("input", validateInline);

  const submitBtn = h(
    "button",
    { type: "submit", className: "btn btn-primary", disabled: state.decks.length === 0 },
    createIcon("create", 15),
    "Guardar tarjeta"
  );

  return h(
    "form",
    {
      className: "panel form-grid",
      onSubmit: async (e) => {
        e.preventDefault();
        if (!validateInline()) return;
        submitBtn.disabled = true;
        const accepted = acceptedInput.value
          .split("\n")
          .map((s) => s.trim())
          .filter(Boolean);
        const ok = await actions.createCard({
          deck_id: deckSelect.value,
          kind: kindSelect.value,
          front: frontInput.value.trim(),
          back: backInput.value.trim(),
          accepted_answers: accepted,
          explanation: explanationInput.value.trim() || null,
          source_label: sourceLabelInput.value.trim() || null,
        });
        submitBtn.disabled = false;
        if (ok) {
          frontInput.value = "";
          backInput.value = "";
          acceptedInput.value = "";
          explanationInput.value = "";
          sourceLabelInput.value = "";
        }
      },
    },
    h(
      "div",
      { className: "panel-title-group" },
      h("h2", { className: "panel-title", textContent: "Nueva tarjeta manual" }),
      h("p", {
        className: "panel-subtitle",
        textContent: "Soporta los 7 formatos de práctica: vocabulario, entrevista, STAR, cloze, ES→EN y listening.",
      })
    ),
    h(
      "div",
      { className: "form-row-2" },
      h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Mazo" }), deckSelect),
      h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Formato" }), kindSelect)
    ),
    h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Pregunta (anverso)" }), frontInput),
    h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Respuesta (reverso)" }), backInput),
    validationHint,
    h(
      "div",
      { className: "form-row-2" },
      h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Respuestas aceptadas" }), acceptedInput),
      h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Explicación" }), explanationInput)
    ),
    h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Etiqueta de fuente" }), sourceLabelInput),
    h("div", { className: "form-actions" }, submitBtn)
  );
}

function renderTemplatesTab(ctx) {
  const { state, actions } = ctx;

  if (state.templatesLoading) {
    return h(
      "div",
      { className: "template-grid", "aria-busy": "true" },
      h("div", { className: "skeleton-card" }),
      h("div", { className: "skeleton-card" }),
      h("div", { className: "skeleton-card" })
    );
  }

  if (state.templatesError) {
    return h(
      "div",
      { className: "inline-error-box", role: "alert" },
      h("span", { textContent: state.templatesError }),
      h("button", { type: "button", className: "btn btn-secondary btn-sm", onClick: actions.loadTemplates }, "Reintentar")
    );
  }

  const catFilter = state.templateCategory || "all";
  const targetDeckId = state.selectedDeckId || state.decks[0]?.id || "";
  const filtered =
    catFilter === "all"
      ? state.templates
      : state.templates.filter((t) => t.category === catFilter);

  const controls = h(
    "div",
    { className: "panel-header" },
    h(
      "div",
      { className: "segmented compact", role: "group", "aria-label": "Filtrar categoría de plantilla" },
      ...[
        { id: "all", label: "Todas" },
        { id: "star", label: "STAR" },
        { id: "networking", label: "Networking" },
      ].map((cat) =>
        h(
          "button",
          {
            type: "button",
            className: "segment-btn",
            "aria-pressed": String(catFilter === cat.id),
            onClick: () => actions.setTemplateCategory(cat.id),
          },
          cat.label
        )
      )
    ),
    state.decks.length > 0
      ? h(
          "div",
          { style: "display:flex;align-items:center;gap:8px;flex-wrap:wrap;min-width:0;max-width:100%;" },
          h("label", { className: "field-label", htmlFor: "template-deck-target", textContent: "Añadir al mazo:" }),
          h(
            "select",
            {
              id: "template-deck-target",
              className: "select",
              style: "width:min(260px, 100%);max-width:100%;",
              onChange: (e) => actions.setSelectedDeckId(e.target.value),
            },
            ...buildDeckOptions(state.decks, targetDeckId)
          )
        )
      : h(
          "button",
          { type: "button", className: "btn btn-primary btn-sm", onClick: actions.openNewDeckModal },
          "Crea un mazo para añadir"
        )
  );

  if (filtered.length === 0) {
    return h(
      "div",
      { className: "studio-stack" },
      controls,
      createEmptyState({
        icon: "layers",
        title: "No hay plantillas en esta categoría",
        description: "Cambia el filtro para ver las plantillas disponibles en el catálogo.",
      })
    );
  }

  const grid = h(
    "div",
    { className: "template-grid" },
    ...filtered.map((tpl) => {
      const added = state.addedTemplateIds.has(tpl.id);
      return h(
        "article",
        { className: "template-card" },
        h(
          "div",
          null,
          h(
            "div",
            { className: "template-card-head" },
            h("span", {
              className: `kind-chip ${tpl.category === "star" ? "kind-chip-warn" : "kind-chip-accent"}`,
              textContent: tpl.category === "star" ? "STAR" : "Networking",
            }),
            h("span", { className: "kind-chip", textContent: kindLabel(tpl.kind) })
          ),
          h("h3", { className: "template-title", textContent: tpl.title }),
          h("p", { className: "template-front", textContent: tpl.front }),
          h(
            "details",
            { className: "template-details" },
            h("summary", { textContent: "Ver guía de respuesta y follow-ups" }),
            h("p", { className: "template-scaffold", textContent: tpl.back }),
            tpl.follow_up_questions?.length
              ? h(
                  "ul",
                  { className: "template-followups" },
                  ...tpl.follow_up_questions.map((q) => h("li", { textContent: q }))
                )
              : null,
            tpl.explanation
              ? h("p", { className: "field-hint", style: "margin-top:8px", textContent: tpl.explanation })
              : null
          )
        ),
        h(
          "div",
          { className: "template-actions" },
          h("span", { className: "mono muted", style: "font-size:12px", textContent: tpl.id }),
          h(
            "button",
            {
              type: "button",
              className: added ? "btn btn-success btn-sm" : "btn btn-primary btn-sm",
              disabled: state.decks.length === 0,
              onClick: () => actions.addTemplateToDeck(tpl.id, targetDeckId),
            },
            createIcon(added ? "check" : "create", 14),
            added ? "Añadida" : "Añadir al mazo"
          )
        )
      );
    })
  );

  return h("div", { className: "studio-stack" }, controls, grid);
}

function renderSourcesTab(ctx) {
  const { state, actions } = ctx;
  const filter = state.sourceFilter || "all";

  const labelInput = h("input", {
    className: "input",
    type: "text",
    required: true,
    maxlength: "255",
    placeholder: "Ej. AWS Well-Architected Reliability Pillar",
  });
  const urlInput = h("input", {
    className: "input",
    type: "url",
    maxlength: "2048",
    placeholder: "https://… (opcional, único por fuente)",
  });
  const excerptInput = h("textarea", {
    className: "textarea",
    rows: "3",
    maxlength: "20000",
    placeholder: "Extracto o nota clave para convertir en tarjeta después (opcional)",
  });
  const submitBtn = h("button", { type: "submit", className: "btn btn-primary" }, createIcon("create", 15), "Guardar fuente");

  const createForm = h(
    "form",
    {
      className: "panel form-grid",
      onSubmit: async (e) => {
        e.preventDefault();
        submitBtn.disabled = true;
        const ok = await actions.createSource({
          label: labelInput.value.trim(),
          url: urlInput.value.trim() || null,
          excerpt: excerptInput.value.trim() || null,
        });
        submitBtn.disabled = false;
        if (ok) {
          labelInput.value = "";
          urlInput.value = "";
          excerptInput.value = "";
        }
      },
    },
    h(
      "div",
      { className: "panel-title-group" },
      h("h2", { className: "panel-title", textContent: "Nueva fuente de estudio" }),
      h("p", {
        className: "panel-subtitle",
        textContent: "Guarda referencias técnicas en borrador y conviértelas en tarjetas verificadas.",
      })
    ),
    h(
      "div",
      { className: "form-row-2" },
      h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Título / etiqueta" }), labelInput),
      h("div", { className: "field" }, h("label", { className: "field-label", textContent: "URL (opcional)" }), urlInput)
    ),
    h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Extracto" }), excerptInput),
    h("div", { className: "form-actions" }, submitBtn)
  );

  const filtered =
    filter === "all" ? state.sources : state.sources.filter((s) => s.status === filter);

  const filterBar = h(
    "div",
    { className: "section-bar" },
    h(
      "div",
      { className: "segmented compact", role: "group", "aria-label": "Filtrar fuentes por estado" },
      ...[
        { id: "all", label: "Todas" },
        { id: "draft", label: "Borrador" },
        { id: "approved", label: "Aprobadas" },
        { id: "discarded", label: "Descartadas" },
      ].map((st) =>
        h(
          "button",
          {
            type: "button",
            className: "segment-btn",
            "aria-pressed": String(filter === st.id),
            onClick: () => actions.setSourceFilter(st.id),
          },
          st.label
        )
      )
    ),
    h(
      "button",
      { type: "button", className: "btn btn-ghost btn-sm", onClick: actions.loadSources },
      createIcon("refresh", 14),
      "Actualizar"
    )
  );

  let listContent;
  if (state.sourcesLoading) {
    listContent = h("div", { className: "skeleton-block", style: "height: 160px" });
  } else if (state.sourcesError) {
    listContent = h(
      "div",
      { className: "inline-error-box", role: "alert" },
      h("span", { textContent: state.sourcesError }),
      h("button", { type: "button", className: "btn btn-secondary btn-sm", onClick: actions.loadSources }, "Reintentar")
    );
  } else if (filtered.length === 0) {
    listContent = createEmptyState({
      icon: "layers",
      title: "Sin fuentes en esta vista",
      description: "Registra documentación técnica o artículos para curarlos antes de llevarlos a tus mazos.",
    });
  } else {
    listContent = h(
      "div",
      { className: "source-list" },
      ...filtered.map((src) => {
        const statusChipClass =
          src.status === "approved"
            ? "kind-chip-success"
            : src.status === "draft"
              ? "kind-chip-warn"
              : "";
        const statusLabel =
          src.status === "approved"
            ? "Aprobada"
            : src.status === "draft"
              ? "Borrador"
              : "Descartada";
        return h(
          "article",
          { className: "source-item" },
          h(
            "div",
            { className: "source-item-top" },
            h(
              "div",
              { style: "min-width:0;flex:1;" },
              h("h3", { className: "source-title", dir: "auto", textContent: src.label }),
              src.url
                ? h(
                    "a",
                    {
                      className: "source-url",
                      href: src.url,
                      target: "_blank",
                      rel: "noopener noreferrer",
                      title: src.url,
                    },
                    createIcon("external", 13),
                    truncateMiddle(src.url, 56)
                  )
                : null
            ),
            h("span", { className: `kind-chip ${statusChipClass}`, textContent: statusLabel })
          ),
          src.excerpt
            ? h("p", { className: "source-excerpt", dir: "auto", title: src.excerpt, textContent: src.excerpt })
            : null,
          h(
            "div",
            { className: "source-actions" },
            src.status === "draft"
              ? h(
                  "button",
                  {
                    type: "button",
                    className: "btn btn-primary btn-sm",
                    disabled: state.decks.length === 0,
                    onClick: () => actions.openApproveSourceModal(src),
                  },
                  createIcon("check", 14),
                  "Aprobar a tarjeta"
                )
              : null,
            src.status === "draft"
              ? h(
                  "button",
                  {
                    type: "button",
                    className: "btn btn-secondary btn-sm",
                    onClick: () => actions.openEditSourceModal(src),
                  },
                  createIcon("edit", 14),
                  "Editar"
                )
              : null,
            src.status === "draft"
              ? h(
                  "button",
                  {
                    type: "button",
                    className: "btn btn-ghost btn-sm",
                    onClick: () => actions.discardSource(src.id),
                  },
                  "Descartar"
                )
              : null,
            h(
              "button",
              {
                type: "button",
                className: "btn btn-danger btn-sm",
                onClick: () => actions.deleteSource(src.id),
              },
              createIcon("trash", 14),
              "Eliminar"
            )
          )
        );
      })
    );
  }

  return h("div", { className: "studio-stack" }, createForm, filterBar, listContent);
}

/* ==========================================================================
   View 4 · Registro de Errores (3-Column Kanban Board)
   ========================================================================== */

export function renderErrorsView(ctx) {
  const { state, actions } = ctx;
  const mobileCol = state.errorsMobileCol || "draft";

  const drafts = state.errors.filter((e) => e.status === "draft");
  const approved = state.errors.filter((e) => e.status === "approved");
  const discarded = state.errors.filter((e) => e.status === "discarded");

  const header = h(
    "div",
    { className: "view-header" },
    h(
      "div",
      null,
      h("span", { className: "view-eyebrow", textContent: "Bucle de remediación" }),
      h("h1", { className: "view-title", textContent: "Tablero de errores" }),
      h("p", {
        className: "view-desc",
        textContent:
          "Captura frases o respuestas reales de práctica, recibe sugerencias determinísticas y promueve las valiosas a tarjetas de repaso.",
      })
    ),
    h(
      "div",
      { className: "view-actions" },
      h(
        "button",
        { type: "button", className: "btn btn-ghost btn-sm", onClick: actions.exportErrors },
        createIcon("download", 14),
        "Exportar JSON"
      ),
      h(
        "button",
        { type: "button", className: "btn btn-primary", onClick: () => actions.openCaptureErrorModal() },
        createIcon("sparkles", 15),
        "Registrar / Sugerir error"
      )
    )
  );

  if (state.errorsLoading) {
    return h(
      "div",
      { className: "studio-stack", "aria-busy": "true" },
      header,
      h(
        "div",
        { className: "kanban-board" },
        h("div", { className: "skeleton-card" }),
        h("div", { className: "skeleton-card" }),
        h("div", { className: "skeleton-card" })
      )
    );
  }

  if (state.errorsError) {
    return h(
      "div",
      { className: "studio-stack" },
      header,
      h(
        "div",
        { className: "inline-error-box", role: "alert" },
        h("span", { textContent: state.errorsError }),
        h("button", { type: "button", className: "btn btn-secondary btn-sm", onClick: actions.loadErrors }, "Reintentar")
      )
    );
  }

  const columns = [
    { id: "draft", title: "Pendiente", dotClass: "col-dot-draft", items: drafts },
    { id: "approved", title: "Aprobado", dotClass: "col-dot-approved", items: approved },
    { id: "discarded", title: "Descartado", dotClass: "col-dot-discarded", items: discarded },
  ];

  const mobileTabs = h(
    "div",
    { className: "segmented kanban-mobile-tabs", role: "tablist", "aria-label": "Columnas de errores" },
    ...columns.map((col) =>
      h(
        "button",
        {
          type: "button",
          role: "tab",
          className: "segment-btn",
          "aria-selected": String(mobileCol === col.id),
          onClick: () => actions.setErrorsMobileCol(col.id),
        },
        `${col.title} (${formatInt(col.items.length)})`
      )
    )
  );

  const board = h(
    "div",
    { className: "kanban-board" },
    ...columns.map((col) =>
      h(
        "section",
        {
          className: "kanban-col",
          dataset: { mobileHidden: String(mobileCol !== col.id) },
          "aria-label": `Columna ${col.title}`,
        },
        h(
          "div",
          { className: "kanban-col-head" },
          h(
            "h2",
            { className: "kanban-col-title" },
            h("span", { className: `col-dot ${col.dotClass}`, "aria-hidden": "true" }),
            col.title
          ),
          h("span", { className: "stat-pill tabular", textContent: formatInt(col.items.length) })
        ),
        col.items.length === 0
          ? h("div", {
              className: "kanban-empty",
              textContent:
                col.id === "draft"
                  ? "Sin errores pendientes por revisar."
                  : col.id === "approved"
                    ? "Los errores aprobados aparecen aquí con su tarjeta enlazada."
                    : "Sin errores descartados.",
            })
          : h(
              "div",
              { className: "kanban-cards" },
              ...col.items.map((err) =>
                h(
                  "article",
                  { className: "error-card" },
                  h(
                    "div",
                    { className: "error-diff" },
                    h("p", { className: "error-attempted", dir: "auto", textContent: err.attempted }),
                    h("p", { className: "error-corrected", dir: "auto", textContent: err.corrected })
                  ),
                  h("p", { className: "error-rationale", dir: "auto", textContent: err.rationale }),
                  h(
                    "div",
                    { className: "error-card-meta" },
                    h("span", { className: "mono", textContent: `ERR-${err.id}` }),
                    err.card_id
                      ? h("span", { className: "kind-chip kind-chip-success mono", textContent: `Tarjeta #${err.card_id}` })
                      : null
                  ),
                  h(
                    "div",
                    { className: "error-card-actions" },
                    err.status === "draft"
                      ? h(
                          "button",
                          {
                            type: "button",
                            className: "btn btn-primary btn-sm",
                            disabled: state.decks.length === 0,
                            onClick: () => actions.openApproveErrorModal(err),
                          },
                          createIcon("check", 14),
                          "Aprobar"
                        )
                      : null,
                    err.status === "draft"
                      ? h(
                          "button",
                          {
                            type: "button",
                            className: "btn btn-secondary btn-sm",
                            onClick: () => actions.openEditErrorModal(err),
                          },
                          createIcon("edit", 14),
                          "Editar"
                        )
                      : null,
                    err.status === "draft"
                      ? h(
                          "button",
                          {
                            type: "button",
                            className: "btn btn-ghost btn-sm",
                            onClick: () => actions.discardError(err.id),
                          },
                          "Descartar"
                        )
                      : null,
                    h(
                      "button",
                      {
                        type: "button",
                        className: "btn btn-danger btn-sm",
                        onClick: () => actions.openDeleteErrorModal(err),
                      },
                      createIcon("trash", 14),
                      "Eliminar"
                    )
                  )
                )
              )
            )
      )
    )
  );

  return h("div", { className: "studio-stack" }, header, mobileTabs, board);
}

/* ==========================================================================
   View 5 · Analítica (GET /analytics/learning — Honest Empty States)
   ========================================================================== */

export function renderAnalyticsView(ctx) {
  const { state, actions } = ctx;
  const an = state.analytics;

  const header = h(
    "div",
    { className: "view-header" },
    h(
      "div",
      null,
      h("span", { className: "view-eyebrow", textContent: "Telemetría real" }),
      h("h1", { className: "view-title", textContent: "Analítica de aprendizaje" }),
      h("p", {
        className: "view-desc",
        textContent:
          "Métricas exactas de /analytics/learning. Cuando no hay datos suficientes mostramos el estado vacío honestamente.",
      })
    ),
    h(
      "div",
      { className: "view-actions" },
      h("span", {
        className: "stat-pill",
        textContent: `Zona horaria: ${an.data?.date_timezone || "America/Cancun"}`,
      }),
      h(
        "button",
        { type: "button", className: "btn btn-secondary btn-sm", onClick: actions.loadAnalytics },
        createIcon("refresh", 14),
        "Actualizar"
      )
    )
  );

  const dateError = h("p", { className: "field-error", hidden: true });
  const startInput = h("input", {
    className: "input",
    type: "date",
    value: an.start || "",
    "aria-label": "Fecha inicial",
  });
  const endInput = h("input", {
    className: "input",
    type: "date",
    value: an.end || "",
    "aria-label": "Fecha final",
  });

  const filterBar = h(
    "section",
    { className: "panel" },
    h(
      "div",
      { className: "analytics-filter-bar" },
      h(
        "div",
        { className: "segmented compact", role: "group", "aria-label": "Rangos rápidos" },
        ...[
          { id: "all", label: "Todo" },
          { id: "7d", label: "7 días" },
          { id: "30d", label: "30 días" },
          { id: "84d", label: "12 semanas" },
        ].map((preset) =>
          h(
            "button",
            {
              type: "button",
              className: "segment-btn",
              "aria-pressed": String(an.preset === preset.id),
              onClick: () => actions.applyAnalyticsPreset(preset.id),
            },
            preset.label
          )
        )
      ),
      h(
        "form",
        {
          className: "date-inputs",
          onSubmit: (e) => {
            e.preventDefault();
            if (startInput.value && endInput.value && startInput.value > endInput.value) {
              dateError.textContent = "La fecha inicial debe ser igual o anterior a la fecha final (422).";
              dateError.hidden = false;
              return;
            }
            dateError.hidden = true;
            actions.applyAnalyticsRange(startInput.value, endInput.value);
          },
        },
        h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Desde" }), startInput),
        h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Hasta" }), endInput),
        h("button", { type: "submit", className: "btn btn-primary btn-sm" }, "Aplicar")
      )
    ),
    dateError
  );

  if (an.loading) {
    return h(
      "div",
      { className: "analytics-stack", "aria-busy": "true" },
      header,
      filterBar,
      h(
        "div",
        { className: "kpi-grid" },
        h("div", { className: "skeleton-card" }),
        h("div", { className: "skeleton-card" }),
        h("div", { className: "skeleton-card" }),
        h("div", { className: "skeleton-card" })
      )
    );
  }

  if (an.error) {
    return h(
      "div",
      { className: "analytics-stack" },
      header,
      filterBar,
      h(
        "div",
        { className: "inline-error-box", role: "alert" },
        h("span", { textContent: an.error }),
        h("button", { type: "button", className: "btn btn-secondary btn-sm", onClick: actions.loadAnalytics }, "Reintentar")
      )
    );
  }

  const summary = an.data;
  const recall = summary?.reviews?.recall || { numerator: 0, denominator: 0 };
  const lapse = summary?.reviews?.lapse || { numerator: 0, denominator: 0 };
  const practice = summary?.practice || {};
  const errCorr = summary?.error_correction || {};
  const dq = summary?.data_quality || {};

  const kpis = h(
    "div",
    { className: "kpi-grid" },
    h(
      "article",
      { className: "kpi-card" },
      h("span", { className: "kpi-label", textContent: "Tasa de recuerdo (Recall)" }),
      h("span", { className: "kpi-value tabular", textContent: formatPercent(recall.numerator, recall.denominator) }),
      h(
        "div",
        { className: "meter-track" },
        h("div", {
          className: "meter-fill",
          style: `transform: scaleX(${(clampPercent(recall.numerator, recall.denominator) / 100).toFixed(4)})`,
        })
      ),
      h("span", {
        className: "kpi-sub tabular",
        textContent:
          recall.denominator > 0
            ? `${formatInt(recall.numerator)} aprobados de ${pluralize(recall.denominator, "repaso", "repasos")}`
            : "Sin repasos en el rango seleccionado",
      })
    ),
    h(
      "article",
      { className: "kpi-card" },
      h("span", { className: "kpi-label", textContent: "Tasa de recaída (Lapse)" }),
      h("span", { className: "kpi-value tabular", textContent: formatPercent(lapse.numerator, lapse.denominator) }),
      h(
        "div",
        { className: "meter-track" },
        h("div", {
          className: "meter-fill",
          style: `transform: scaleX(${(clampPercent(lapse.numerator, lapse.denominator) / 100).toFixed(4)})`,
        })
      ),
      h("span", {
        className: "kpi-sub tabular",
        textContent:
          lapse.denominator > 0
            ? `${formatInt(lapse.numerator)} recaídas tras ${formatInt(lapse.denominator)} tarjetas previas aprobadas`
            : "Aún sin tarjetas elegibles para medir recaída",
      })
    ),
    h(
      "article",
      { className: "kpi-card" },
      h("span", { className: "kpi-label", textContent: "Sesiones de práctica" }),
      h("span", { className: "kpi-value tabular", textContent: formatInt(practice.sessions ?? 0) }),
      h("span", {
        className: "kpi-sub tabular",
        textContent: practice.sessions
          ? `Duración observada: ${formatDurationSeconds(practice.observed_span_seconds)} · Último: ${formatTimestamp(practice.last_review_at)}`
          : "Sin sesiones registradas en este rango",
      })
    ),
    h(
      "article",
      { className: "kpi-card" },
      h("span", { className: "kpi-label", textContent: "Recuerdo 1.er repaso (Errores)" }),
      h("span", {
        className: "kpi-value tabular",
        textContent: formatPercent(
          errCorr.first_review_recall?.numerator ?? 0,
          errCorr.first_review_recall?.denominator ?? 0
        ),
      }),
      h("span", {
        className: "kpi-sub tabular",
        textContent:
          (errCorr.first_review_recall?.denominator ?? 0) > 0
            ? `${formatInt(errCorr.first_review_recall.numerator)} / ${formatInt(errCorr.first_review_recall.denominator)} tarjetas de remediación aprobadas al primer repaso`
            : "Sin primeros repasos de tarjetas de error todavía",
      })
    )
  );

  const heatmap = createHeatmapCard({
    dateKeys: state.heatmap.dateKeys,
    counts: state.heatmap.counts,
    loading: state.heatmap.loading,
    error: state.heatmap.error,
    isDemo: state.demoMode,
    onRetry: actions.refreshHeatmap,
  });

  const remediationAndQuality = h(
    "section",
    { className: "panel" },
    h(
      "div",
      { className: "panel-header" },
      h(
        "div",
        { className: "panel-title-group" },
        h("h2", { className: "panel-title", textContent: "Remediación y calidad de datos" }),
        h("p", {
          className: "panel-subtitle",
          textContent: `Semántica v${summary?.semantics_version ?? 1} · Ventana: ${
            practice.first_review_cancun_date
              ? `${formatIsoDate(practice.first_review_cancun_date)} → ${formatIsoDate(practice.last_review_cancun_date)}`
              : "Sin actividad aún"
          }`,
        })
      )
    ),
    h(
      "div",
      { className: "quality-grid" },
      h("div", { className: "quality-row" }, h("span", { textContent: "Errores en borrador" }), h("strong", { className: "tabular", textContent: formatInt(errCorr.current_drafts ?? 0) })),
      h("div", { className: "quality-row" }, h("span", { textContent: "Errores aprobados" }), h("strong", { className: "tabular", textContent: formatInt(errCorr.current_approved ?? 0) })),
      h("div", { className: "quality-row" }, h("span", { textContent: "Errores descartados" }), h("strong", { className: "tabular", textContent: formatInt(errCorr.current_discarded ?? 0) })),
      h("div", { className: "quality-row" }, h("span", { textContent: "Aprobados sin tarjeta" }), h("strong", { className: "tabular", textContent: formatInt(errCorr.current_approved_without_card ?? 0) })),
      h("div", { className: "quality-row" }, h("span", { textContent: "Repasos sin fecha" }), h("strong", { className: "tabular", textContent: formatInt(dq.reviews_without_timestamp ?? 0) })),
      h("div", { className: "quality-row" }, h("span", { textContent: "Calificaciones inválidas" }), h("strong", { className: "tabular", textContent: formatInt(dq.reviews_with_invalid_grade ?? 0) })),
      h("div", { className: "quality-row" }, h("span", { textContent: "Posibles duplicados" }), h("strong", { className: "tabular", textContent: formatInt(dq.possible_duplicate_reviews ?? 0) })),
      h("div", { className: "quality-row" }, h("span", { textContent: "Tiempo activo / respuesta" }), h("strong", { className: "muted", textContent: "No medido aún" }))
    )
  );

  return h("div", { className: "analytics-stack" }, header, filterBar, kpis, heatmap, remediationAndQuality);
}

/* ==========================================================================
   Modals: Deck Form, Deck Card Inspector (Chunked), Capture Error, Approvals
   ========================================================================== */

export function buildDeckModalContent({ deck = null, onSubmit, onCancel }) {
  const nameInput = h("input", {
    className: "input",
    type: "text",
    required: true,
    maxlength: "120",
    value: deck?.name || "",
    placeholder: "Ej. Cloud interviews",
  });
  const descInput = h("textarea", {
    className: "textarea",
    rows: "3",
    maxlength: "5000",
    value: deck?.description || "",
    placeholder: "Objetivo del mazo y temas técnicos clave (opcional)",
  });
  const submitBtn = h(
    "button",
    { type: "submit", className: "btn btn-primary" },
    deck ? "Guardar cambios" : "Crear mazo"
  );

  return h(
    "form",
    {
      className: "form-grid",
      onSubmit: async (e) => {
        e.preventDefault();
        if (!nameInput.value.trim()) return;
        submitBtn.disabled = true;
        await onSubmit({ name: nameInput.value.trim(), description: descInput.value.trim() });
        submitBtn.disabled = false;
      },
    },
    h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Nombre del mazo" }), nameInput),
    h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Descripción" }), descInput),
    h(
      "div",
      { className: "form-actions" },
      h("button", { type: "button", className: "btn btn-ghost", onClick: onCancel }, "Cancelar"),
      submitBtn
    )
  );
}

export function buildDeckInspectorContent({
  deck,
  cards,
  stats,
  onStudy,
  onEditDeck,
  onDeleteDeck,
  onEditCard,
  onDeleteCard,
  onClose,
}) {
  const PAGE_SIZE = 40;
  let visibleCount = PAGE_SIZE;

  const listWrap = h("div", { className: "card-preview-list" });
  const loadMoreWrap = h("div", { className: "form-actions", style: "justify-content:center;margin-top:12px;" });

  function renderSlice() {
    listWrap.replaceChildren();
    loadMoreWrap.replaceChildren();
    if (cards.length === 0) {
      listWrap.append(
        createEmptyState({
          icon: "layers",
          title: "Este mazo todavía no tiene tarjetas",
          description: "Genera tarjetas desde texto o añade plantillas STAR/Networking.",
        })
      );
      return;
    }

    const slice = cards.slice(0, visibleCount);
    slice.forEach((card) => {
      listWrap.append(
        h(
          "article",
          { className: "card-preview-item" },
          h(
            "div",
            { className: "card-preview-head" },
            h(
              "div",
              { style: "display:flex;flex-wrap:wrap;gap:6px;align-items:center;" },
              h("span", { className: "kind-chip kind-chip-accent", textContent: kindLabel(card.kind) }),
              h("span", {
                className: "muted tabular",
                style: "font-size:12px",
                textContent: `Vence: ${formatIsoDate(card.due_date)} · Rep ${formatInt(card.repetitions)}`,
              })
            ),
            h(
              "div",
              { style: "display:flex;flex-wrap:wrap;gap:6px;" },
              h(
                "button",
                {
                  type: "button",
                  className: "btn btn-secondary btn-sm",
                  "aria-label": `Editar tarjeta ${card.id}`,
                  onClick: () => onEditCard(card),
                },
                createIcon("edit", 13),
                "Editar"
              ),
              h(
                "button",
                {
                  type: "button",
                  className: "btn btn-danger btn-sm",
                  "aria-label": `Eliminar tarjeta ${card.id}`,
                  onClick: () => onDeleteCard(card.id),
                },
                createIcon("trash", 13),
                "Eliminar"
              )
            )
          ),
          h("p", { className: "card-preview-front", dir: "auto", textContent: card.front }),
          h("p", { className: "card-preview-back", dir: "auto", textContent: card.back })
        )
      );
    });

    if (cards.length > visibleCount) {
      const remaining = cards.length - visibleCount;
      loadMoreWrap.append(
        h(
          "button",
          {
            type: "button",
            className: "btn btn-secondary btn-sm",
            onClick: () => {
              visibleCount += PAGE_SIZE;
              renderSlice();
            },
          },
          `Mostrar más (${formatInt(remaining)} restantes)`
        )
      );
    }
  }

  renderSlice();

  return h(
    "div",
    { className: "form-grid" },
    deck.description
      ? h("p", { className: "muted", dir: "auto", style: "margin:0;overflow-wrap:anywhere;", textContent: deck.description })
      : null,
    h(
      "div",
      { style: "display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px;" },
      h(
        "div",
        { style: "display:flex;flex-wrap:wrap;gap:6px;" },
        h("span", { className: "stat-pill tabular", textContent: pluralize(stats.total, "tarjeta", "tarjetas") }),
        h("span", { className: "stat-pill stat-pill-accent tabular", textContent: `${formatInt(stats.due)} hoy` }),
        h("span", { className: "stat-pill mono", textContent: `ID ${deck.id}` })
      ),
      h(
        "div",
        { style: "display:flex;flex-wrap:wrap;gap:6px;" },
        h(
          "button",
          {
            type: "button",
            className: "btn btn-primary btn-sm",
            onClick: () => {
              onClose();
              onStudy(deck.id);
            },
          },
          createIcon("focus", 14),
          "Estudiar"
        ),
        h(
          "button",
          { type: "button", className: "btn btn-secondary btn-sm", onClick: () => onEditDeck(deck) },
          createIcon("edit", 14),
          "Editar"
        ),
        h(
          "button",
          { type: "button", className: "btn btn-danger btn-sm", onClick: () => onDeleteDeck(deck) },
          createIcon("trash", 14),
          "Eliminar mazo"
        )
      )
    ),
    listWrap,
    loadMoreWrap
  );
}

export function buildCaptureErrorModalContent({ prefill = {}, onSuggest, onManual, onCancel }) {
  let mode = "suggest";

  const formWrap = h("div");
  const modeBar = h(
    "div",
    { className: "segmented compact", role: "tablist" },
    h(
      "button",
      {
        type: "button",
        role: "tab",
        className: "segment-btn",
        "aria-selected": "true",
        onClick: (e) => {
          mode = "suggest";
          updateTabs(e.currentTarget);
          renderMode();
        },
      },
      "Sugerencia automática (/errors/suggest)"
    ),
    h(
      "button",
      {
        type: "button",
        role: "tab",
        className: "segment-btn",
        "aria-selected": "false",
        onClick: (e) => {
          mode = "manual";
          updateTabs(e.currentTarget);
          renderMode();
        },
      },
      "Registro manual (/errors)"
    )
  );

  function updateTabs(activeBtn) {
    modeBar.querySelectorAll("button").forEach((b) => b.setAttribute("aria-selected", String(b === activeBtn)));
  }

  function renderMode() {
    if (mode === "suggest") {
      const categorySelect = h(
        "select",
        { className: "select" },
        h("option", { value: "technical", textContent: "Técnica (technical)" }),
        h("option", { value: "star", textContent: "STAR / Conductual (star)" })
      );
      const promptInput = h("input", {
        className: "input",
        type: "text",
        value: prefill.prompt || "",
        placeholder: "Pregunta de entrevista (opcional)",
      });
      const answerInput = h("textarea", {
        className: "textarea",
        rows: "3",
        required: true,
        placeholder: "Tu respuesta literal (ej. The server did not responded in Monday and depends of DNS)",
      });
      const correctedInput = h("textarea", {
        className: "textarea",
        rows: "2",
        value: prefill.corrected || "",
        placeholder: "Corrección manual opcional (déjalo vacío para usar la heurística)",
      });
      const consentInput = h("input", { type: "checkbox", required: true });
      const errMsg = h("p", { className: "field-error", hidden: true });
      const submitBtn = h("button", { type: "submit", className: "btn btn-primary" }, createIcon("sparkles", 14), "Generar borrador");

      formWrap.replaceChildren(
        h(
          "form",
          {
            className: "form-grid",
            onSubmit: async (e) => {
              e.preventDefault();
              if (!consentInput.checked) {
                errMsg.textContent = "Debes confirmar el consentimiento explícito para guardar texto de entrevista.";
                errMsg.hidden = false;
                return;
              }
              errMsg.hidden = true;
              submitBtn.disabled = true;
              await onSuggest({
                category: categorySelect.value,
                prompt: promptInput.value.trim() || null,
                answer: answerInput.value.trim(),
                corrected: correctedInput.value.trim() || null,
                consent: true,
              });
              submitBtn.disabled = false;
            },
          },
          h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Categoría" }), categorySelect),
          h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Pregunta (opcional)" }), promptInput),
          h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Respuesta que dijiste" }), answerInput),
          h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Corrección (opcional)" }), correctedInput),
          h(
            "label",
            { className: "checkbox-row" },
            consentInput,
            h("span", {
              textContent:
                "Doy mi consentimiento explícito para almacenar este texto de entrevista en mi registro local de errores.",
            })
          ),
          errMsg,
          h(
            "div",
            { className: "form-actions" },
            h("button", { type: "button", className: "btn btn-ghost", onClick: onCancel }, "Cancelar"),
            submitBtn
          )
        )
      );
    } else {
      const attemptedInput = h("textarea", {
        className: "textarea",
        rows: "2",
        required: true,
        placeholder: "Frase o respuesta con error",
      });
      const correctedInput = h("textarea", {
        className: "textarea",
        rows: "2",
        required: true,
        value: prefill.corrected || "",
        placeholder: "Forma correcta en inglés técnico",
      });
      const rationaleInput = h("textarea", {
        className: "textarea",
        rows: "2",
        required: true,
        placeholder: "Por qué se corrige (regla gramatical, vocabulario o STAR)",
      });
      const submitBtn = h("button", { type: "submit", className: "btn btn-primary" }, "Guardar en Pendiente");

      formWrap.replaceChildren(
        h(
          "form",
          {
            className: "form-grid",
            onSubmit: async (e) => {
              e.preventDefault();
              submitBtn.disabled = true;
              await onManual({
                attempted: attemptedInput.value.trim(),
                corrected: correctedInput.value.trim(),
                rationale: rationaleInput.value.trim(),
              });
              submitBtn.disabled = false;
            },
          },
          h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Lo que dijiste" }), attemptedInput),
          h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Versión corregida" }), correctedInput),
          h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Explicación / motivo" }), rationaleInput),
          h(
            "div",
            { className: "form-actions" },
            h("button", { type: "button", className: "btn btn-ghost", onClick: onCancel }, "Cancelar"),
            submitBtn
          )
        )
      );
    }
  }

  renderMode();
  return h("div", { className: "form-grid" }, modeBar, formWrap);
}

export function buildApproveErrorModalContent({ errorItem, decks, selectedDeckId, onApprove, onCancel }) {
  const isStar = errorItem.rationale?.startsWith("[STAR remediation]");
  const deckSelect = h(
    "select",
    { className: "select", required: true },
    ...buildDeckOptions(decks, selectedDeckId || decks[0]?.id || "")
  );
  const kindSelect = h(
    "select",
    { className: "select" },
    ...KIND_OPTIONS.map((opt) =>
      h("option", {
        value: opt.value,
        selected: opt.value === (isStar ? "behavioral" : "interview_phrase"),
        textContent: opt.label,
      })
    )
  );
  const frontInput = h("textarea", {
    className: "textarea",
    rows: "2",
    required: true,
    value: `Correct: ${errorItem.attempted}`,
  });
  const backInput = h("textarea", {
    className: "textarea",
    rows: "2",
    required: true,
    value: errorItem.corrected,
  });
  const explanationInput = h("textarea", {
    className: "textarea",
    rows: "2",
    value: errorItem.rationale || "",
  });
  const submitBtn = h("button", { type: "submit", className: "btn btn-primary" }, createIcon("check", 14), "Aprobar y crear tarjeta");

  return h(
    "form",
    {
      className: "form-grid",
      onSubmit: async (e) => {
        e.preventDefault();
        submitBtn.disabled = true;
        await onApprove({
          deck_id: deckSelect.value,
          kind: kindSelect.value,
          front: frontInput.value.trim(),
          back: backInput.value.trim(),
          explanation: explanationInput.value.trim() || null,
        });
        submitBtn.disabled = false;
      },
    },
    h(
      "div",
      { className: "form-row-2" },
      h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Mazo destino" }), deckSelect),
      h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Formato" }), kindSelect)
    ),
    h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Anverso de la tarjeta" }), frontInput),
    h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Reverso de la tarjeta" }), backInput),
    h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Explicación" }), explanationInput),
    h(
      "div",
      { className: "form-actions" },
      h("button", { type: "button", className: "btn btn-ghost", onClick: onCancel }, "Cancelar"),
      submitBtn
    )
  );
}

export function buildApproveSourceModalContent({ source, decks, selectedDeckId, onApprove, onCancel }) {
  const deckSelect = h(
    "select",
    { className: "select", required: true },
    ...buildDeckOptions(decks, selectedDeckId || decks[0]?.id || "")
  );
  const kindSelect = h(
    "select",
    { className: "select" },
    ...KIND_OPTIONS.map((opt) =>
      h("option", {
        value: opt.value,
        selected: opt.value === "interview_phrase",
        textContent: opt.label,
      })
    )
  );
  const frontInput = h("textarea", {
    className: "textarea",
    rows: "2",
    required: true,
    value: `Explain key takeaways from: ${source.label}`,
  });
  const backInput = h("textarea", {
    className: "textarea",
    rows: "3",
    required: true,
    value: source.excerpt || "",
    placeholder: "Respuesta clave extraída de la fuente",
  });
  const explanationInput = h("textarea", {
    className: "textarea",
    rows: "2",
    value: source.url ? `Referencia: ${source.url}` : "",
  });
  const submitBtn = h("button", { type: "submit", className: "btn btn-primary" }, createIcon("check", 14), "Aprobar fuente");

  return h(
    "form",
    {
      className: "form-grid",
      onSubmit: async (e) => {
        e.preventDefault();
        submitBtn.disabled = true;
        await onApprove({
          deck_id: deckSelect.value,
          kind: kindSelect.value,
          front: frontInput.value.trim(),
          back: backInput.value.trim(),
          explanation: explanationInput.value.trim() || null,
        });
        submitBtn.disabled = false;
      },
    },
    h(
      "div",
      { className: "form-row-2" },
      h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Mazo destino" }), deckSelect),
      h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Formato" }), kindSelect)
    ),
    h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Pregunta (anverso)" }), frontInput),
    h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Respuesta (reverso)" }), backInput),
    h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Explicación" }), explanationInput),
    h(
      "div",
      { className: "form-actions" },
      h("button", { type: "button", className: "btn btn-ghost", onClick: onCancel }, "Cancelar"),
      submitBtn
    )
  );
}


export function buildEditCardModalContent({ card, decks, onSubmit, onCancel }) {
  const validationHint = h("p", { className: "field-error", hidden: true });
  const deckSelect = h(
    "select",
    { className: "select", name: "deck_id", required: true },
    ...buildDeckOptions(decks, card.deck_id)
  );
  const kindSelect = h(
    "select",
    { className: "select", name: "kind" },
    ...KIND_OPTIONS.map((opt) =>
      h("option", { value: opt.value, selected: opt.value === card.kind, textContent: opt.label })
    )
  );
  const frontInput = h("textarea", {
    className: "textarea",
    rows: "3",
    required: true,
    maxlength: "5000",
    value: card.front || "",
    placeholder: "Pregunta o frase (para Cloze usa exactamente un ____)",
  });
  const backInput = h("textarea", {
    className: "textarea",
    rows: "3",
    required: true,
    maxlength: "5000",
    value: card.back || "",
    placeholder: "Respuesta esperada o transcripción (máx. 1,000 caracteres si es Listening)",
  });
  const acceptedInput = h("textarea", {
    className: "textarea",
    rows: "2",
    value: Array.isArray(card.accepted_answers) ? card.accepted_answers.join("\n") : "",
    placeholder: "Respuestas alternativas aceptadas (una por línea, opcional)",
  });
  const explanationInput = h("textarea", {
    className: "textarea",
    rows: "2",
    maxlength: "5000",
    value: card.explanation || "",
    placeholder: "Nota técnica o contexto (opcional)",
  });
  const sourceLabelInput = h("input", {
    className: "input",
    type: "text",
    maxlength: "255",
    value: card.source_label || "",
    placeholder: "Etiqueta de origen (opcional)",
  });

  function validateInline() {
    const kind = kindSelect.value;
    const front = frontInput.value.trim();
    const back = backInput.value.trim();
    if (kind === "cloze") {
      const blanks = front.match(/_{4,}/g) || [];
      if (blanks.length !== 1 || blanks[0] !== "____") {
        validationHint.textContent = "Las tarjetas Cloze requieren exactamente un hueco '____' en el anverso.";
        validationHint.hidden = false;
        return false;
      }
    }
    if (kind === "listening" && back.length > 1000) {
      validationHint.textContent = "Las tarjetas Listening permiten máximo 1,000 caracteres en la transcripción.";
      validationHint.hidden = false;
      return false;
    }
    validationHint.hidden = true;
    return true;
  }

  kindSelect.addEventListener("change", validateInline);
  frontInput.addEventListener("input", validateInline);
  backInput.addEventListener("input", validateInline);

  const submitBtn = h("button", { type: "submit", className: "btn btn-primary" }, "Guardar cambios");

  return h(
    "form",
    {
      className: "form-grid",
      onSubmit: async (e) => {
        e.preventDefault();
        if (!validateInline()) return;
        const front = frontInput.value.trim();
        const back = backInput.value.trim();
        if (!front || !back) return;
        submitBtn.disabled = true;
        const accepted = acceptedInput.value
          .split("\n")
          .map((s) => s.trim())
          .filter(Boolean);
        await onSubmit({
          deck_id: deckSelect.value,
          kind: kindSelect.value,
          front,
          back,
          accepted_answers: accepted,
          explanation: explanationInput.value.trim() || null,
          source_label: sourceLabelInput.value.trim() || null,
        });
        submitBtn.disabled = false;
      },
    },
    h("p", {
      className: "field-hint",
      style: "margin:0;",
      textContent: "Editar los campos conserva tu historial y calendario SM-2.",
    }),
    h(
      "div",
      { className: "form-row-2" },
      h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Mazo" }), deckSelect),
      h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Formato" }), kindSelect)
    ),
    h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Anverso" }), frontInput),
    h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Reverso" }), backInput),
    validationHint,
    h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Respuestas aceptadas" }), acceptedInput),
    h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Explicación" }), explanationInput),
    h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Etiqueta de origen" }), sourceLabelInput),
    h(
      "div",
      { className: "form-actions" },
      h("button", { type: "button", className: "btn btn-ghost", onClick: onCancel }, "Cancelar"),
      submitBtn
    )
  );
}

export function buildEditSourceModalContent({ source, onSubmit, onCancel }) {
  const labelInput = h("input", {
    className: "input",
    type: "text",
    required: true,
    maxlength: "255",
    value: source.label || "",
    placeholder: "Título o etiqueta de la fuente",
  });
  const urlInput = h("input", {
    className: "input",
    type: "url",
    maxlength: "2048",
    value: source.url || "",
    placeholder: "https://… (opcional, único por fuente)",
  });
  const excerptInput = h("textarea", {
    className: "textarea",
    rows: "4",
    maxlength: "20000",
    value: source.excerpt || "",
    placeholder: "Fragmento o notas clave (opcional)",
  });
  const submitBtn = h("button", { type: "submit", className: "btn btn-primary" }, "Guardar fuente");

  return h(
    "form",
    {
      className: "form-grid",
      onSubmit: async (e) => {
        e.preventDefault();
        const label = labelInput.value.trim();
        if (!label) return;
        submitBtn.disabled = true;
        await onSubmit({
          label,
          url: urlInput.value.trim() || null,
          excerpt: excerptInput.value.trim() || null,
        });
        submitBtn.disabled = false;
      },
    },
    h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Etiqueta" }), labelInput),
    h("div", { className: "field" }, h("label", { className: "field-label", textContent: "URL" }), urlInput),
    h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Extracto" }), excerptInput),
    h(
      "div",
      { className: "form-actions" },
      h("button", { type: "button", className: "btn btn-ghost", onClick: onCancel }, "Cancelar"),
      submitBtn
    )
  );
}

export function buildEditErrorModalContent({ errorItem, onSubmit, onCancel }) {
  const attemptedInput = h("textarea", {
    className: "textarea",
    rows: "3",
    required: true,
    maxlength: "5000",
    value: errorItem.attempted || "",
    placeholder: "Qué respondiste o intentaste decir",
  });
  const correctedInput = h("textarea", {
    className: "textarea",
    rows: "3",
    required: true,
    maxlength: "5000",
    value: errorItem.corrected || "",
    placeholder: "Forma natural y correcta en inglés técnico",
  });
  const rationaleInput = h("textarea", {
    className: "textarea",
    rows: "3",
    required: true,
    maxlength: "5000",
    value: errorItem.rationale || "",
    placeholder: "Regla o explicación breve",
  });
  const submitBtn = h("button", { type: "submit", className: "btn btn-primary" }, "Guardar error");

  return h(
    "form",
    {
      className: "form-grid",
      onSubmit: async (e) => {
        e.preventDefault();
        const attempted = attemptedInput.value.trim();
        const corrected = correctedInput.value.trim();
        const rationale = rationaleInput.value.trim();
        if (!attempted || !corrected || !rationale) return;
        submitBtn.disabled = true;
        await onSubmit({ attempted, corrected, rationale });
        submitBtn.disabled = false;
      },
    },
    h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Intento original" }), attemptedInput),
    h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Corrección" }), correctedInput),
    h("div", { className: "field" }, h("label", { className: "field-label", textContent: "Explicación" }), rationaleInput),
    h(
      "div",
      { className: "form-actions" },
      h("button", { type: "button", className: "btn btn-ghost", onClick: onCancel }, "Cancelar"),
      submitBtn
    )
  );
}
