import { api } from "../api.js";
import {
  clear,
  el,
  formatDurationSeconds,
  formatInt,
  formatIsoDate,
  formatPercent,
  plural,
  renderEmptyState,
  renderErrorBanner,
  renderSkeleton,
} from "../ui.js";

function isoDaysAgo(days) {
  const d = new Date(Date.now() - days * 86400000);
  return d.toISOString().slice(0, 10);
}

export function mountAnalytics(container, ctx) {
  let disposed = false;
  let seq = 0;

  const state = {
    start: "",
    end: "",
    data: null,
    error: "",
    validationError: "",
  };

  async function load() {
    if (state.start && state.end && state.start > state.end) {
      state.validationError = "La fecha inicial debe ser anterior o igual a la fecha final.";
      render();
      return;
    }
    state.validationError = "";

    const mySeq = ++seq;
    clear(container);
    container.append(renderHeader(), renderFilters(), renderSkeleton("dashboard"));

    const res = await api.getLearningAnalytics({ start: state.start, end: state.end });
    if (disposed || mySeq !== seq) return;

    if (!res.ok) {
      state.error = res.error;
      state.data = null;
    } else {
      state.error = "";
      state.data = res.data;
    }
    render();
  }

  function renderHeader() {
    return el(
      "header",
      { className: "page-header" },
      el(
        "div",
        { className: "page-header-copy" },
        el("p", { className: "eyebrow" }, "Analítica de aprendizaje"),
        el("h1", { className: "page-title" }, "Pulso real de retención"),
        el(
          "p",
          { className: "page-lead" },
          "Datos estrictamente calculados por GET /analytics/learning. Cuando un denominador es cero o un campo no existe, se muestra vacío de forma explícita."
        )
      )
    );
  }

  function renderFilters() {
    const startInput = el("input", {
      id: "an-start",
      type: "date",
      className: "input",
      value: state.start,
      onChange: (e) => {
        state.start = e.target.value;
      },
    });
    const endInput = el("input", {
      id: "an-end",
      type: "date",
      className: "input",
      value: state.end,
      onChange: (e) => {
        state.end = e.target.value;
      },
    });

    const applyRange = (start, end) => {
      state.start = start;
      state.end = end;
      load();
    };

    return el(
      "section",
      { className: "panel", style: "margin-bottom: 1.5rem;" },
      el(
        "form",
        {
          className: "form-grid",
          onSubmit: (e) => {
            e.preventDefault();
            load();
          },
        },
        el(
          "div",
          { className: "form-row-2" },
          el("div", { className: "field" }, el("label", { className: "field-label", for: "an-start" }, "Desde (fecha Cancún)"), startInput),
          el("div", { className: "field" }, el("label", { className: "field-label", for: "an-end" }, "Hasta (fecha Cancún)"), endInput)
        ),
        state.validationError ? el("div", { className: "field-error", role: "alert" }, state.validationError) : null,
        el(
          "div",
          { className: "deck-card-actions", style: "border-top: 0; padding-top: 0;" },
          el(
            "div",
            { className: "page-actions" },
            el("button", { type: "button", className: "btn btn--ghost btn--sm", onClick: () => applyRange("", "") }, "Todo"),
            el("button", { type: "button", className: "btn btn--ghost btn--sm", onClick: () => applyRange(isoDaysAgo(0), isoDaysAgo(0)) }, "Hoy"),
            el("button", { type: "button", className: "btn btn--ghost btn--sm", onClick: () => applyRange(isoDaysAgo(7), isoDaysAgo(0)) }, "7 días"),
            el("button", { type: "button", className: "btn btn--ghost btn--sm", onClick: () => applyRange(isoDaysAgo(30), isoDaysAgo(0)) }, "30 días")
          ),
          el("button", { type: "submit", className: "btn btn--primary btn--sm" }, "Aplicar rango")
        )
      )
    );
  }

  function render() {
    clear(container);
    container.append(renderHeader(), renderFilters());

    if (state.error) {
      container.append(renderErrorBanner(state.error, load));
      return;
    }

    if (!state.data) return;

    const { reviews, practice, error_correction: ec, data_quality: dq, date_timezone, semantics_version } = state.data;

    const recallPct = formatPercent(reviews.recall.numerator, reviews.recall.denominator);
    const lapsePct = formatPercent(reviews.lapse.numerator, reviews.lapse.denominator);
    const errRecallPct = formatPercent(ec.first_review_recall.numerator, ec.first_review_recall.denominator);
    const spanText = formatDurationSeconds(practice.observed_span_seconds);

    const hasAnyReviews = reviews.recall.denominator > 0;
    const totalErrors = ec.current_drafts + ec.current_approved + ec.current_discarded;

    // Honest empty state when workspace has zero reviews and zero errors
    if (!hasAnyReviews && totalErrors === 0) {
      container.append(
        renderEmptyState({
          variant: "analytics",
          title: "Aún no hay actividad registrada en este rango",
          description:
            "Completa tu primera sesión de estudio o registra un error de entrevista para ver métricas reales de retención, recaídas y remediación.",
          action: el(
            "button",
            { type: "button", className: "btn btn--primary", onClick: () => ctx.navigate("estudiar") },
            "Ir a Estudiar"
          ),
        })
      );
      return;
    }

    // Main KPI Grid
    const kpiGrid = el(
      "section",
      { className: "kpi-grid", "aria-label": "Indicadores principales" },
      el(
        "article",
        { className: "kpi-card" },
        el("span", { className: "stat-label" }, "Retención en repasos (≥ 3)"),
        el("p", { className: `kpi-number ${recallPct ? "stat-value--success" : "kpi-number--empty"}` }, recallPct || "Sin datos"),
        el(
          "p",
          { className: "kpi-ratio" },
          reviews.recall.denominator > 0
            ? `${formatInt(reviews.recall.numerator)} / ${formatInt(reviews.recall.denominator)} repasos aprobados`
            : "Ningún repaso calificado en este rango"
        )
      ),
      el(
        "article",
        { className: "kpi-card" },
        el("span", { className: "stat-label" }, "Tasa de recaída (lapse)"),
        el("p", { className: `kpi-number ${lapsePct ? "" : "kpi-number--empty"}` }, lapsePct || "Sin datos"),
        el(
          "p",
          { className: "kpi-ratio" },
          reviews.lapse.denominator > 0
            ? `${formatInt(reviews.lapse.numerator)} / ${formatInt(reviews.lapse.denominator)} tarjetas previamente aprobadas`
            : "Requiere al menos un repaso posterior a una calificación aprobada"
        )
      ),
      el(
        "article",
        { className: "kpi-card" },
        el("span", { className: "stat-label" }, "Sesiones observadas"),
        el("p", { className: `kpi-number ${practice.sessions > 0 ? "" : "kpi-number--empty"}` }, formatInt(practice.sessions)),
        el(
          "p",
          { className: "kpi-ratio" },
          practice.sessions > 0
            ? `Duración observada: ${spanText || "0 s"} · ${formatIsoDate(practice.first_review_cancun_date)} → ${formatIsoDate(practice.last_review_cancun_date)}`
            : "Sin sesiones en el periodo seleccionado"
        )
      ),
      el(
        "article",
        { className: "kpi-card" },
        el("span", { className: "stat-label" }, "1.er repaso de errores aprobados"),
        el("p", { className: `kpi-number ${errRecallPct ? "stat-value--accent" : "kpi-number--empty"}` }, errRecallPct || "Sin datos"),
        el(
          "p",
          { className: "kpi-ratio" },
          ec.first_review_recall.denominator > 0
            ? `${formatInt(ec.first_review_recall.numerator)} / ${formatInt(ec.first_review_recall.denominator)} recordadas al primer intento`
            : "Ninguna tarjeta nacida de un error se ha repasado todavía"
        )
      )
    );

    container.append(kpiGrid);

    // Error Correction Funnel Panel
    const funnelSection = el(
      "section",
      { className: "panel", style: "margin-bottom: 1.25rem;" },
      el(
        "div",
        { className: "panel-header" },
        el(
          "div",
          {},
          el("h2", { className: "panel-title" }, "Embudo de corrección de errores"),
          el("p", { className: "panel-subtitle" }, "Estado actual de todos los borradores de remediación en la base de datos.")
        ),
        el("span", { className: "badge num" }, plural(totalErrors, "registro", "registros"))
      )
    );

    if (totalErrors === 0) {
      funnelSection.append(
        el("p", { className: "field-hint", style: "margin: 0;" }, "Aún no hay registros en /errors para mostrar el embudo.")
      );
    } else {
      const pctApproved = (ec.current_approved / totalErrors) * 100;
      const pctDrafts = (ec.current_drafts / totalErrors) * 100;
      const pctDiscarded = (ec.current_discarded / totalErrors) * 100;

      funnelSection.append(
        el(
          "div",
          { className: "funnel-bar", role: "img", "aria-label": `Aprobados ${ec.current_approved}, borradores ${ec.current_drafts}, descartados ${ec.current_discarded}` },
          ec.current_approved > 0 ? el("div", { className: "funnel-seg--approved", style: `width: ${pctApproved}%;` }) : null,
          ec.current_drafts > 0 ? el("div", { className: "funnel-seg--draft", style: `width: ${pctDrafts}%;` }) : null,
          ec.current_discarded > 0 ? el("div", { className: "funnel-seg--discarded", style: `width: ${pctDiscarded}%;` }) : null
        ),
        el(
          "div",
          { className: "legend-row" },
          el(
            "span",
            { className: "legend-item num" },
            el("span", { className: "legend-swatch", style: "background: var(--success);" }),
            `Aprobados: ${formatInt(ec.current_approved)}`
          ),
          el(
            "span",
            { className: "legend-item num" },
            el("span", { className: "legend-swatch", style: "background: var(--warning);" }),
            `Borradores: ${formatInt(ec.current_drafts)}`
          ),
          el(
            "span",
            { className: "legend-item num" },
            el("span", { className: "legend-swatch", style: "background: var(--ink-muted);" }),
            `Descartados: ${formatInt(ec.current_discarded)}`
          ),
          ec.current_approved_without_card > 0
            ? el(
                "span",
                { className: "badge badge--warning num" },
                `${formatInt(ec.current_approved_without_card)} aprobados sin tarjeta vinculada`
              )
            : null
        )
      );
    }

    container.append(funnelSection);

    // Data Quality & Honest Unmeasured Fields Panel
    const dqIssues =
      dq.reviews_without_timestamp + dq.reviews_with_invalid_grade + dq.possible_duplicate_reviews;

    container.append(
      el(
        "section",
        { className: "panel" },
        el(
          "div",
          { className: "panel-header" },
          el(
            "div",
            {},
            el("h2", { className: "panel-title" }, "Calidad y transparencia de datos"),
            el("p", { className: "panel-subtitle" }, `Zona horaria: ${date_timezone} · Semántica v${semantics_version}`)
          ),
          el(
            "span",
            { className: `badge ${dqIssues === 0 ? "badge--success" : "badge--warning"}` },
            dqIssues === 0 ? "Datos íntegros" : plural(dqIssues, "aviso detectado", "avisos detectados")
          )
        ),
        el(
          "div",
          { className: "quality-list" },
          el(
            "div",
            { className: "quality-item" },
            el("span", { className: "stat-label" }, "Repasos sin fecha"),
            el("strong", { className: "num" }, formatInt(dq.reviews_without_timestamp))
          ),
          el(
            "div",
            { className: "quality-item" },
            el("span", { className: "stat-label" }, "Calificaciones inválidas"),
            el("strong", { className: "num" }, formatInt(dq.reviews_with_invalid_grade))
          ),
          el(
            "div",
            { className: "quality-item" },
            el("span", { className: "stat-label" }, "Posibles duplicados"),
            el("strong", { className: "num" }, formatInt(dq.possible_duplicate_reviews))
          )
        ),
        el(
          "p",
          { className: "field-hint", style: "margin: 1rem 0 0;" },
          "Nota honesta: active_study_seconds y response_seconds devuelven null en esta versión de la API; la interfaz no inventa ni estima tiempos de respuesta."
        )
      )
    );
  }

  load();

  return () => {
    disposed = true;
    seq += 1;
  };
}
