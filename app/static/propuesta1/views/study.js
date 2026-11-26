import { api, isReadOnlyMode } from "../api.js";
import {
  GRADE_OPTIONS,
  KIND_META,
  clear,
  el,
  formatCompact,
  formatInt,
  formatIsoDate,
  plural,
  previewSm2IntervalDays,
  renderEmptyState,
  renderErrorBanner,
  renderKindBadge,
  renderPromptText,
  renderSkeleton,
  showToast,
} from "../ui.js";

export function mountStudy(container, ctx) {
  let disposed = false;
  let loadSeq = 0;

  const state = {
    decks: [],
    deckId: ctx.params.deck || "",
    kind: ctx.params.kind || "",
    remediationOnly: ctx.params.remediation === "1",
    initialDueCount: 0,
    remainingDueCount: 0,
    card: null,
    reveal: null,
    revealing: false,
    grading: false,
    audioUrl: null,
    audioLoading: false,
    audioError: "",
    error: "",
    sessionResults: [], // array of { quality, due_date, interval_days }
    demoSkipIds: new Set(),
  };

  function revokeAudio() {
    if (state.audioUrl) {
      URL.revokeObjectURL(state.audioUrl);
      state.audioUrl = null;
    }
    state.audioError = "";
    state.audioLoading = false;
  }

  async function init() {
    const mySeq = ++loadSeq;
    clear(container);
    container.append(renderSkeleton("study"));

    const decksRes = await api.listDecks();
    if (disposed || mySeq !== loadSeq) return;

    if (!decksRes.ok) {
      clear(container);
      container.append(renderHeader(), renderErrorBanner(decksRes.error, init));
      return;
    }

    state.decks = decksRes.data || [];
    if (state.decks.length === 0) {
      clear(container);
      container.append(
        renderHeader(),
        renderEmptyState({
          variant: "cards",
          title: "Crea un mazo para empezar a estudiar",
          description: "Aún no tienes mazos registrados. Crea uno y añade tus primeras tarjetas.",
          action: el(
            "button",
            {
              type: "button",
              className: "btn btn--primary",
              onClick: () => ctx.navigate("crear", { tab: "manual" }),
            },
            "Ir a Crear"
          ),
        })
      );
      return;
    }

    // Pick requested deck or first deck with due cards
    if (!state.deckId || !state.decks.some((d) => d.id === state.deckId)) {
      let chosen = state.decks[0].id;
      for (const d of state.decks) {
        const dueRes = await api.listDueCards(d.id);
        if (disposed || mySeq !== loadSeq) return;
        const count =
          typeof dueRes.syntheticCount === "number"
            ? dueRes.syntheticCount
            : dueRes.ok
              ? (dueRes.data || []).length
              : 0;
        if (count > 0) {
          chosen = d.id;
          break;
        }
      }
      state.deckId = chosen;
    }

    await resetAndLoadQueue();
  }

  async function resetAndLoadQueue() {
    state.sessionResults = [];
    state.demoSkipIds.clear();
    await refreshQueueCount();
    await loadNextCard();
  }

  async function refreshQueueCount() {
    if (!state.deckId) return;
    const dueRes = await api.listDueCards(state.deckId);
    if (!dueRes.ok) return;
    if (typeof dueRes.syntheticCount === "number" && !state.kind && !state.remediationOnly) {
      state.remainingDueCount = Math.max(0, dueRes.syntheticCount - state.demoSkipIds.size);
    } else {
      const dueList = (dueRes.data || []).filter((c) => {
        if (state.kind && c.kind !== state.kind) return false;
        if (state.remediationOnly && !c.error_id) return false;
        if (state.demoSkipIds.has(c.id)) return false;
        return true;
      });
      state.remainingDueCount = dueList.length;
    }
    if (state.sessionResults.length === 0) {
      state.initialDueCount = state.remainingDueCount;
    }
  }

  async function loadNextCard() {
    const mySeq = ++loadSeq;
    revokeAudio();
    state.card = null;
    state.reveal = null;
    state.revealing = false;
    state.grading = false;
    state.error = "";
    render();

    const res = await api.studyNext({
      deckId: state.deckId,
      kind: state.kind,
      remediationOnly: state.remediationOnly,
    });
    if (disposed || mySeq !== loadSeq) return;

    if (!res.ok) {
      state.error = res.error;
      render();
      return;
    }

    if (res.status === 204 || !res.data) {
      state.card = null;
      state.remainingDueCount = 0;
      render();
      return;
    }

    // In read-only demo/worst mode, skip cards already previewed in this session
    if (isReadOnlyMode() && state.demoSkipIds.has(res.data.card_id)) {
      const dueRes = await api.listDueCards(state.deckId);
      const nextDemo = (dueRes.data || []).find((c) => {
        if (state.demoSkipIds.has(c.id)) return false;
        if (state.kind && c.kind !== state.kind) return false;
        if (state.remediationOnly && !c.error_id) return false;
        return true;
      });
      if (!nextDemo) {
        state.card = null;
        state.remainingDueCount = 0;
        render();
        return;
      }
      state.card = {
        card_id: nextDemo.id,
        deck_id: nextDemo.deck_id,
        front: nextDemo.front,
        kind: nextDemo.kind,
        source_label: nextDemo.source_label,
        error_id: nextDemo.error_id,
        due_date: nextDemo.due_date,
        repetitions: nextDemo.repetitions,
        interval_days: nextDemo.interval_days,
        ease_factor: nextDemo.ease_factor,
      };
      render();
      return;
    }

    state.card = res.data;
    render();
  }

  async function handleReveal() {
    if (!state.card || state.reveal || state.revealing) return;
    const targetId = state.card.card_id;
    state.revealing = true;
    state.error = "";
    render();

    const res = await api.studyReveal(targetId);
    if (disposed || !state.card || state.card.card_id !== targetId) return;

    state.revealing = false;
    if (!res.ok) {
      state.error = res.error;
      render();
      return;
    }

    state.reveal = res.data;
    render();
  }

  async function handleGrade(quality) {
    if (!state.card || !state.reveal || state.grading) return;

    if (isReadOnlyMode()) {
      showToast("Modo vista previa: calificación simulada localmente (sin escribir en la API).", {
        tone: "warning",
      });
      state.demoSkipIds.add(state.card.card_id);
      const nextDays = previewSm2IntervalDays(state.card, quality);
      const nextDate = new Date(Date.now() + nextDays * 86400000).toISOString().slice(0, 10);
      state.sessionResults.push({ quality, interval_days: nextDays, due_date: nextDate });
      state.remainingDueCount = Math.max(0, state.remainingDueCount - 1);
      await loadNextCard();
      return;
    }

    const targetId = state.card.card_id;
    state.grading = true;
    state.error = "";
    render();

    const res = await api.studyGrade(targetId, quality);
    if (disposed || !state.card || state.card.card_id !== targetId) return;

    state.grading = false;
    if (!res.ok) {
      state.error = res.error;
      render();
      return;
    }

    state.sessionResults.push({
      quality: res.data.quality,
      interval_days: res.data.interval_days,
      due_date: res.data.due_date,
    });
    state.remainingDueCount = Math.max(0, state.remainingDueCount - 1);
    ctx.refreshGlobalBadges();
    await loadNextCard();
  }

  async function handleAudio() {
    if (!state.card || state.audioLoading) return;
    const targetId = state.card.card_id;
    state.audioLoading = true;
    state.audioError = "";
    render();

    const res = await api.studyAudio(targetId);
    if (disposed || !state.card || state.card.card_id !== targetId) return;

    state.audioLoading = false;
    if (!res.ok) {
      state.audioError = res.error;
      render();
      return;
    }

    revokeAudio();
    state.audioUrl = URL.createObjectURL(res.data);
    render();
  }

  function onKeyDown(e) {
    if (disposed) return;
    const dialog = document.getElementById("app-dialog");
    if (dialog && dialog.open) return;

    const tag = e.target?.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || e.target?.isContentEditable) {
      return;
    }
    if (e.metaKey || e.ctrlKey || e.altKey) return;

    if (!state.card) return;

    if (!state.reveal && (e.code === "Space" || e.key === "Enter")) {
      // Avoid hijacking Enter/Space if user focused a toolbar button
      if (tag === "BUTTON" && !e.target.dataset.revealBtn) return;
      e.preventDefault();
      handleReveal();
      return;
    }

    if (state.reveal && !state.grading && /^[0-5]$/.test(e.key)) {
      e.preventDefault();
      handleGrade(Number(e.key));
    }
  }

  window.addEventListener("keydown", onKeyDown);

  function renderHeader() {
    return el(
      "header",
      { className: "page-header" },
      el(
        "div",
        { className: "page-header-copy" },
        el("p", { className: "eyebrow" }, "Sesión recall-first"),
        el("h1", { className: "page-title" }, "Mesa de estudio")
      )
    );
  }

  function renderToolbar() {
    const deckSelect = el(
      "select",
      {
        className: "select",
        "aria-label": "Seleccionar mazo para estudiar",
        onChange: (e) => {
          state.deckId = e.target.value;
          resetAndLoadQueue();
        },
      },
      ...state.decks.map((d) =>
        el("option", { value: d.id, selected: d.id === state.deckId }, d.name)
      )
    );

    const kindSelect = el(
      "select",
      {
        className: "select",
        "aria-label": "Filtrar por formato de tarjeta",
        onChange: (e) => {
          state.kind = e.target.value;
          resetAndLoadQueue();
        },
      },
      el("option", { value: "", selected: state.kind === "" }, "Todos los formatos"),
      ...Object.entries(KIND_META).map(([k, meta]) =>
        el("option", { value: k, selected: state.kind === k }, meta.label)
      )
    );

    const remediationToggle = el(
      "button",
      {
        type: "button",
        className: "chip-toggle",
        "aria-pressed": String(state.remediationOnly),
        onClick: () => {
          state.remediationOnly = !state.remediationOnly;
          resetAndLoadQueue();
        },
      },
      state.remediationOnly ? "✓ Solo remediación" : "Solo remediación"
    );

    return el(
      "section",
      { className: "study-toolbar", "aria-label": "Controles de sesión" },
      el("div", { className: "study-toolbar-field" }, deckSelect),
      el("div", { className: "study-toolbar-field" }, kindSelect),
      remediationToggle
    );
  }

  function renderProgress() {
    const done = state.sessionResults.length;
    const total = Math.max(done + state.remainingDueCount, state.initialDueCount, done);
    const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;

    return el(
      "div",
      { className: "study-progress-wrap" },
      el(
        "div",
        { className: "study-progress-row" },
        el(
          "span",
          { className: "num" },
          `Sesión actual: ${plural(done, "repasada", "repasadas")} · ${plural(state.remainingDueCount, "pendiente", "pendientes")}`
        ),
        el("span", { className: "num" }, `${pct} %`)
      ),
      el(
        "div",
        {
          className: "progress-track",
          role: "progressbar",
          "aria-label": "Progreso de la sesión actual",
          "aria-valuemin": "0",
          "aria-valuemax": "100",
          "aria-valuenow": String(pct),
        },
        el("div", { className: "progress-fill progress-fill--accent", style: `width: ${pct}%;` })
      )
    );
  }

  function renderStudyCard() {
    const card = state.card;
    const easeLabel = Number.isFinite(Number(card.ease_factor))
      ? Number(card.ease_factor).toFixed(2)
      : "2.50";

    const folioTags = el(
      "div",
      { className: "folio-tags" },
      renderKindBadge(card.kind),
      card.error_id ? el("span", { className: "badge badge--warning" }, "Remediación") : null,
      card.source_label
        ? el(
            "span",
            {
              className: "badge",
              title: card.source_label,
              style: "max-width: 220px; overflow: hidden; text-overflow: ellipsis;",
            },
            card.source_label
          )
        : null
    );

    const folioStats = el(
      "div",
      { className: "folio-stats" },
      el("span", {}, `Rep ${formatInt(card.repetitions)}`),
      el("span", {}, `Int ${formatInt(card.interval_days)} d`),
      el("span", {}, `EF ${easeLabel}`)
    );

    const listeningBlock =
      card.kind === "listening"
        ? el(
            "div",
            { className: "listening-bar" },
            el(
              "button",
              {
                type: "button",
                className: "btn btn--secondary btn--sm",
                disabled: state.audioLoading,
                onClick: handleAudio,
              },
              state.audioLoading ? "Generando audio…" : "Escuchar audio (Polly)"
            ),
            state.audioUrl ? el("audio", { controls: true, src: state.audioUrl }) : null,
            state.audioError ? el("span", { className: "field-error" }, state.audioError) : null
          )
        : null;

    const frontFace = el(
      "div",
      { className: "study-card-face" },
      el("span", { className: "face-kicker" }, "Pregunta · Recuerdo activo"),
      renderPromptText(card.front, card.kind),
      listeningBlock
    );

    let lowerHalf;
    if (!state.reveal) {
      lowerHalf = el(
        "div",
        { className: "study-reveal-prompt" },
        el("p", { className: "reveal-hint" }, "Formula tu respuesta mentalmente o en voz alta antes de mirar."),
        el(
          "button",
          {
            type: "button",
            className: "btn btn--primary btn--lg",
            disabled: state.revealing,
            dataset: { revealBtn: "true" },
            onClick: handleReveal,
          },
          state.revealing ? "Revelando…" : "Revelar respuesta",
          el("span", { className: "kbd", "aria-hidden": "true" }, "Espacio")
        )
      );
    } else {
      const accepted = state.reveal.accepted_answers || [];
      lowerHalf = el(
        "div",
        { className: "study-card-back" },
        el("span", { className: "face-kicker" }, "Respuesta esperada"),
        el("p", { className: "card-answer-text", dir: "auto" }, state.reveal.back),
        accepted.length > 0
          ? el(
              "div",
              { className: "accepted-answers" },
              el("span", { className: "field-hint" }, "Variantes aceptadas:"),
              ...accepted.map((ans) => el("span", { className: "answer-chip", dir: "auto" }, ans))
            )
          : null,
        state.reveal.explanation
          ? el("div", { className: "explanation-box", dir: "auto" }, state.reveal.explanation)
          : null
      );
    }

    const cardNode = el(
      "article",
      { className: "study-card", "aria-label": "Ficha de estudio" },
      el("div", { className: "study-card-folio" }, folioTags, folioStats),
      frontFace,
      lowerHalf
    );

    if (!state.reveal) {
      return cardNode;
    }

    const gradeDock = el(
      "section",
      { className: "grade-dock", "aria-label": "Calificar recuerdo SM-2" },
      el(
        "div",
        { className: "grade-dock-head" },
        el("h2", { className: "grade-dock-title" }, "¿Qué tan sólido fue tu recuerdo?"),
        el("span", { className: "field-hint" }, "Teclas 0–5 · ≥ 3 aprueba y espacia")
      ),
      el(
        "div",
        { className: "grade-grid" },
        ...GRADE_OPTIONS.map((opt) => {
          const days = previewSm2IntervalDays(card, opt.q);
          return el(
            "button",
            {
              type: "button",
              className: `grade-btn grade-btn--${opt.tone}`,
              disabled: state.grading,
              "aria-label": `Calificar ${opt.q}: ${opt.label}, próximo repaso en ${plural(days, "día", "días")}`,
              onClick: () => handleGrade(opt.q),
            },
            el(
              "span",
              { className: "grade-btn-top" },
              el("span", { className: "grade-score" }, String(opt.q)),
              el("span", { className: "grade-interval" }, `${formatCompact(days)} d`)
            ),
            el("span", { className: "grade-label" }, opt.label)
          );
        })
      )
    );

    return el("div", { className: "stack" }, cardNode, gradeDock);
  }

  function renderSessionSummary() {
    const results = state.sessionResults;
    const total = results.length;
    const passed = results.filter((r) => r.quality >= 3).length;
    const toReinforce = total - passed;
    const earliestDue = results
      .map((r) => r.due_date)
      .filter(Boolean)
      .sort()[0];

    const countsByGrade = [0, 1, 2, 3, 4, 5].map((q) => ({
      q,
      count: results.filter((r) => r.quality === q).length,
    }));

    return el(
      "section",
      { className: "summary-card", "aria-label": "Resumen de la sesión" },
      el(
        "div",
        { className: "summary-lead" },
        el("span", { className: "badge badge--success" }, "Sesión completada"),
        el("h2", { className: "focus-hero-title" }, "Buen trabajo: cola de hoy terminada"),
        el(
          "p",
          { className: "page-lead" },
          "Cada calificación ya actualizó el intervalo SM-2 real de tus tarjetas."
        )
      ),
      el(
        "div",
        { className: "summary-metrics" },
        el(
          "div",
          { className: "stat-tile" },
          el("span", { className: "stat-label" }, "Repasadas"),
          el("strong", { className: "stat-value" }, formatInt(total))
        ),
        el(
          "div",
          { className: "stat-tile" },
          el("span", { className: "stat-label" }, "Aprobadas (3–5)"),
          el("strong", { className: "stat-value stat-value--success" }, formatInt(passed))
        ),
        el(
          "div",
          { className: "stat-tile" },
          el("span", { className: "stat-label" }, "A reforzar (0–2)"),
          el("strong", { className: "stat-value stat-value--accent" }, formatInt(toReinforce))
        ),
        el(
          "div",
          { className: "stat-tile" },
          el("span", { className: "stat-label" }, "Próximo vencimiento"),
          el("strong", { className: "stat-value", style: "font-size: 1.25rem;" }, formatIsoDate(earliestDue))
        )
      ),
      el(
        "div",
        { className: "summary-breakdown" },
        el("span", { className: "field-label" }, "Distribución real de esta sesión"),
        el(
          "div",
          { className: "legend-row", style: "margin-top: 0.5rem;" },
          ...countsByGrade.map((g) =>
            el("span", { className: "badge num" }, `${g.q}: ${formatInt(g.count)}`)
          )
        ),
        el(
          "div",
          { className: "page-actions", style: "margin-top: 1.35rem;" },
          el(
            "button",
            { type: "button", className: "btn btn--primary", onClick: () => ctx.navigate("inicio") },
            "Volver a Inicio"
          ),
          el(
            "button",
            { type: "button", className: "btn btn--secondary", onClick: () => ctx.navigate("analitica") },
            "Ver analítica"
          )
        )
      )
    );
  }

  function render() {
    clear(container);
    container.classList.add("view-root--narrow");
    container.append(renderHeader(), renderToolbar());

    if (state.error) {
      container.append(renderErrorBanner(state.error, loadNextCard));
    }

    if (state.card) {
      container.append(renderProgress(), renderStudyCard());
      return;
    }

    if (state.sessionResults.length > 0) {
      container.append(renderSessionSummary());
      return;
    }

    if (!state.error) {
      const hasFilters = Boolean(state.kind || state.remediationOnly);
      container.append(
        renderEmptyState({
          variant: "done",
          title: hasFilters ? "Ninguna tarjeta pendiente con estos filtros" : "Sin tarjetas pendientes hoy en este mazo",
          description: hasFilters
            ? "Prueba quitar el filtro de formato o de remediación para ver el resto del mazo."
            : "Todas las tarjetas de este mazo están programadas para una fecha futura o el mazo aún está vacío.",
          action: el(
            "div",
            { className: "page-actions" },
            hasFilters
              ? el(
                  "button",
                  {
                    type: "button",
                    className: "btn btn--primary",
                    onClick: () => {
                      state.kind = "";
                      state.remediationOnly = false;
                      resetAndLoadQueue();
                    },
                  },
                  "Quitar filtros"
                )
              : null,
            el(
              "button",
              {
                type: "button",
                className: "btn btn--secondary",
                onClick: () => ctx.navigate("crear", { tab: "generar", deck: state.deckId }),
              },
              "Añadir tarjetas a este mazo"
            )
          ),
        })
      );
    }
  }

  init();

  return () => {
    disposed = true;
    loadSeq += 1;
    revokeAudio();
    container.classList.remove("view-root--narrow");
    window.removeEventListener("keydown", onKeyDown);
  };
}
