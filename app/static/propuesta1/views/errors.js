import { api, isReadOnlyMode } from "../api.js";
import {
  KIND_META,
  clear,
  createHoldDeleteButton,
  el,
  formatInt,
  plural,
  renderEmptyState,
  renderErrorBanner,
  renderKindBadge,
  renderSkeleton,
  renderStatusBadge,
  showToast,
} from "../ui.js";

const CLOZE_BLANK_RE = /_{4,}/g;

export function mountErrors(container, ctx) {
  let disposed = false;
  let seq = 0;

  const state = {
    decks: [],
    selectedDeckId: "",
    errors: [],
    statusFilter: "",
    composerMode: "suggest", // suggest | manual
    openApproveId: null,
    suggestedOverrides: new Map(), // errorId -> suggested_card
    error: "",
  };

  async function load() {
    const mySeq = ++seq;
    clear(container);
    container.append(renderSkeleton("dashboard"));

    const [decksRes, errorsRes] = await Promise.all([
      api.listDecks(),
      api.listErrors(state.statusFilter),
    ]);
    if (disposed || mySeq !== seq) return;

    if (!errorsRes.ok) {
      state.error = errorsRes.error;
    } else {
      state.error = "";
      state.errors = errorsRes.data || [];
    }

    if (decksRes.ok) {
      state.decks = decksRes.data || [];
      if (!state.selectedDeckId || !state.decks.some((d) => d.id === state.selectedDeckId)) {
        state.selectedDeckId = state.decks[0]?.id || "";
      }
    }

    render();
  }

  async function reloadErrors() {
    const res = await api.listErrors(state.statusFilter);
    if (disposed) return;
    if (!res.ok) {
      showToast(res.error, { tone: "error" });
      return;
    }
    state.errors = res.data || [];
    ctx.refreshGlobalBadges();
    render();
  }

  async function handleExport() {
    const res = await api.exportErrors(state.statusFilter);
    if (!res.ok) {
      showToast(res.error, { tone: "error" });
      return;
    }
    const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = el("a", {
      href: url,
      download: `techcards-errores-${new Date().toISOString().slice(0, 10)}.json`,
    });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    showToast(`Exportados ${plural(res.data.count, "registro", "registros")}.`, { tone: "success" });
  }

  function renderHeader() {
    return el(
      "header",
      { className: "page-header" },
      el(
        "div",
        { className: "page-header-copy" },
        el("p", { className: "eyebrow" }, "Ciclo de remediación"),
        el("h1", { className: "page-title" }, "Registro de errores"),
        el(
          "p",
          { className: "page-lead" },
          "Convierte tropiezos reales de entrevista en tarjetas corregidas con aprobación humana explícita."
        )
      ),
      el(
        "div",
        { className: "page-actions" },
        el(
          "button",
          { type: "button", className: "btn btn--secondary", onClick: handleExport },
          "Exportar JSON"
        )
      )
    );
  }

  function renderComposer() {
    const modeSwitch = el(
      "div",
      { className: "segmented", role: "group", "aria-label": "Modo de captura de error" },
      el(
        "button",
        {
          type: "button",
          className: "seg-btn",
          "aria-pressed": String(state.composerMode === "suggest"),
          onClick: () => {
            state.composerMode = "suggest";
            render();
          },
        },
        "Sugerir corrección"
      ),
      el(
        "button",
        {
          type: "button",
          className: "seg-btn",
          "aria-pressed": String(state.composerMode === "manual"),
          onClick: () => {
            state.composerMode = "manual";
            render();
          },
        },
        "Registro manual"
      )
    );

    const body = state.composerMode === "suggest" ? renderSuggestForm() : renderManualErrorForm();

    return el(
      "section",
      { className: "panel" },
      el(
        "div",
        { className: "panel-header" },
        el(
          "div",
          {},
          el(
            "h2",
            { className: "panel-title" },
            state.composerMode === "suggest"
              ? "Analizar respuesta de entrevista"
              : "Registrar corrección manual"
          ),
          el(
            "p",
            { className: "panel-subtitle" },
            state.composerMode === "suggest"
              ? "Heurística local offline (POST /errors/suggest): genera un borrador y una tarjeta sugerida para tu revisión."
              : "Guarda directamente un borrador con lo que dijiste, la forma correcta y la razón (POST /errors)."
          )
        ),
        modeSwitch
      ),
      body
    );
  }

  function renderSuggestForm() {
    const categorySelect = el(
      "select",
      { id: "sug-category", className: "select" },
      el("option", { value: "technical" }, "Técnica (interview_phrase)"),
      el("option", { value: "star" }, "Conductual STAR (behavioral)")
    );
    const promptInput = el("input", {
      id: "sug-prompt",
      type: "text",
      className: "input",
      maxlength: "2000",
      placeholder: "Pregunta de entrevista (opcional)",
    });
    const answerInput = el("textarea", {
      id: "sug-answer",
      className: "textarea",
      rows: "3",
      required: true,
      maxlength: "4991",
      placeholder:
        "Ej. The service did not responded in Monday because the timeout depends of the load balancer.",
    });
    const correctedInput = el("input", {
      id: "sug-corrected",
      type: "text",
      className: "input",
      maxlength: "5000",
      placeholder: "Corrección propuesta por ti (opcional; si lo dejas vacío, se sugiere una)",
    });
    const rationaleInput = el("input", {
      id: "sug-rationale",
      type: "text",
      className: "input",
      maxlength: "5000",
      placeholder: "Nota o razón (opcional)",
    });
    const consentCheck = el("input", {
      id: "sug-consent",
      type: "checkbox",
    });
    const errNode = el("div", { className: "field-error", role: "alert", hidden: true });
    const submitBtn = el("button", { type: "submit", className: "btn btn--primary" }, "Generar borrador y sugerencia");

    return el(
      "form",
      {
        className: "form-grid",
        onSubmit: async (e) => {
          e.preventDefault();
          const answer = answerInput.value.trim();
          if (!answer) {
            errNode.textContent = "Escribe la respuesta de entrevista que quieres revisar.";
            errNode.hidden = false;
            answerInput.focus();
            return;
          }
          if (!consentCheck.checked) {
            errNode.textContent = "Marca el consentimiento explícito para almacenar el texto localmente.";
            errNode.hidden = false;
            consentCheck.focus();
            return;
          }
          errNode.hidden = true;
          submitBtn.disabled = true;

          const res = await api.suggestError({
            answer,
            prompt: promptInput.value.trim() || null,
            category: categorySelect.value,
            corrected: correctedInput.value.trim() || null,
            rationale: rationaleInput.value.trim() || null,
            consent: true,
          });
          submitBtn.disabled = false;

          if (!res.ok) {
            errNode.textContent = res.error;
            errNode.hidden = false;
            return;
          }

          const created = res.data.error;
          state.suggestedOverrides.set(created.id, res.data.suggested_card);
          state.openApproveId = created.id;
          state.statusFilter = "";
          answerInput.value = "";
          promptInput.value = "";
          correctedInput.value = "";
          rationaleInput.value = "";
          consentCheck.checked = false;
          showToast("Borrador sugerido listo para revisar y aprobar.", { tone: "success" });
          await reloadErrors();
        },
      },
      el(
        "div",
        { className: "form-row-2" },
        el("div", { className: "field" }, el("label", { className: "field-label", for: "sug-category" }, "Categoría"), categorySelect),
        el("div", { className: "field" }, el("label", { className: "field-label", for: "sug-prompt" }, "Pregunta original (opcional)"), promptInput)
      ),
      el("div", { className: "field" }, el("label", { className: "field-label", for: "sug-answer" }, "Tu respuesta en entrevista"), answerInput),
      el(
        "div",
        { className: "form-row-2" },
        el("div", { className: "field" }, el("label", { className: "field-label", for: "sug-corrected" }, "Corrección manual (opcional)"), correctedInput),
        el("div", { className: "field" }, el("label", { className: "field-label", for: "sug-rationale" }, "Explicación (opcional)"), rationaleInput)
      ),
      el(
        "label",
        { className: "checkbox-row", for: "sug-consent" },
        consentCheck,
        el(
          "span",
          { className: "checkbox-copy" },
          "Doy mi consentimiento explícito para guardar este texto en mi base de datos local de TechCards SRS como borrador de remediación."
        )
      ),
      errNode,
      el("div", { className: "form-actions" }, submitBtn)
    );
  }

  function renderManualErrorForm() {
    const attemptedInput = el("textarea", {
      id: "err-attempted",
      className: "textarea",
      rows: "2",
      required: true,
      maxlength: "5000",
      placeholder: "Lo que dijiste o escribiste originalmente",
    });
    const correctedInput = el("textarea", {
      id: "err-corrected",
      className: "textarea",
      rows: "2",
      required: true,
      maxlength: "5000",
      placeholder: "Cómo deberías decirlo con naturalidad",
    });
    const rationaleInput = el("textarea", {
      id: "err-rationale",
      className: "textarea",
      rows: "2",
      required: true,
      maxlength: "5000",
      placeholder: "Por qué cambia (gramática, preposición, estructura STAR o precisión técnica)",
    });
    const errNode = el("div", { className: "field-error", role: "alert", hidden: true });
    const submitBtn = el("button", { type: "submit", className: "btn btn--primary" }, "Guardar borrador");

    return el(
      "form",
      {
        className: "form-grid",
        onSubmit: async (e) => {
          e.preventDefault();
          const attempted = attemptedInput.value.trim();
          const corrected = correctedInput.value.trim();
          const rationale = rationaleInput.value.trim();
          if (!attempted || !corrected || !rationale) {
            errNode.textContent = "Completa los tres campos para guardar el error.";
            errNode.hidden = false;
            return;
          }
          errNode.hidden = true;
          submitBtn.disabled = true;
          const res = await api.createError({ attempted, corrected, rationale });
          submitBtn.disabled = false;
          if (!res.ok) {
            errNode.textContent = res.error;
            errNode.hidden = false;
            return;
          }
          attemptedInput.value = "";
          correctedInput.value = "";
          rationaleInput.value = "";
          showToast("Error registrado como borrador.", { tone: "success" });
          await reloadErrors();
        },
      },
      el("div", { className: "field" }, el("label", { className: "field-label", for: "err-attempted" }, "Lo que dijiste"), attemptedInput),
      el("div", { className: "field" }, el("label", { className: "field-label", for: "err-corrected" }, "Forma corregida"), correctedInput),
      el("div", { className: "field" }, el("label", { className: "field-label", for: "err-rationale" }, "Explicación / Regla"), rationaleInput),
      errNode,
      el("div", { className: "form-actions" }, submitBtn)
    );
  }

  function renderErrorCard(errItem) {
    const isDraft = errItem.status === "draft";
    const isApproveOpen = state.openApproveId === errItem.id;
    const suggestion = state.suggestedOverrides.get(errItem.id) || null;

    const actions = [];
    if (isDraft) {
      actions.push(
        el(
          "button",
          {
            type: "button",
            className: "btn btn--primary btn--sm",
            onClick: () => {
              state.openApproveId = isApproveOpen ? null : errItem.id;
              render();
            },
          },
          isApproveOpen ? "Cerrar aprobación" : "Aprobar como tarjeta"
        ),
        el(
          "button",
          {
            type: "button",
            className: "btn btn--secondary btn--sm",
            onClick: async () => {
              const res = await api.discardError(errItem.id);
              if (!res.ok) {
                showToast(res.error, { tone: "error" });
                return;
              }
              showToast("Borrador descartado.", { tone: "warning" });
              await reloadErrors();
            },
          },
          "Descartar"
        )
      );
    }

    actions.push(
      createHoldDeleteButton({
        label: "Eliminar",
        disabled: isReadOnlyMode(),
        onConfirm: async () => {
          const res = await api.deleteError(errItem.id, false);
          if (!res.ok) {
            showToast(res.error, { tone: "error" });
            return;
          }
          showToast("Registro eliminado.", { tone: "warning" });
          await reloadErrors();
        },
      })
    );

    let approveDrawer = null;
    if (isDraft && isApproveOpen) {
      const defaultKind =
        suggestion?.kind ||
        (errItem.rationale.startsWith("[STAR remediation]") ? "behavioral" : "interview_phrase");

      const deckSelect =
        state.decks.length > 0
          ? el(
              "select",
              {
                className: "select",
                onChange: (e) => {
                  state.selectedDeckId = e.target.value;
                },
              },
              ...state.decks.map((d) =>
                el("option", { value: d.id, selected: d.id === state.selectedDeckId }, d.name)
              )
            )
          : el("p", { className: "field-error" }, "Crea primero un mazo para poder aprobar.");

      const kindSelect = el(
        "select",
        { className: "select" },
        ...Object.entries(KIND_META).map(([k, meta]) =>
          el("option", { value: k, selected: k === defaultKind }, meta.label)
        )
      );
      const frontInput = el("textarea", {
        className: "textarea",
        rows: "2",
        required: true,
        value: suggestion?.front || `Correct: ${errItem.attempted}`,
      });
      const backInput = el("textarea", {
        className: "textarea",
        rows: "2",
        required: true,
        value: suggestion?.back || errItem.corrected,
      });
      const explInput = el("textarea", {
        className: "textarea",
        rows: "2",
        value: suggestion?.explanation || errItem.rationale,
      });
      const approveErr = el("div", { className: "field-error", role: "alert", hidden: true });
      const confirmBtn = el(
        "button",
        { type: "submit", className: "btn btn--success btn--sm", disabled: state.decks.length === 0 },
        "Aprobar y crear tarjeta"
      );

      approveDrawer = el(
        "form",
        {
          className: "inline-drawer form-grid",
          onSubmit: async (e) => {
            e.preventDefault();
            const front = frontInput.value.trim();
            const back = backInput.value.trim();
            const kind = kindSelect.value;
            if (!state.selectedDeckId) {
              approveErr.textContent = "Selecciona un mazo destino.";
              approveErr.hidden = false;
              return;
            }
            if (kind === "cloze") {
              const blanks = front.match(CLOZE_BLANK_RE) || [];
              if (blanks.length !== 1 || blanks[0] !== "____") {
                approveErr.textContent = "Las tarjetas cloze requieren exactamente un hueco «____».";
                approveErr.hidden = false;
                return;
              }
            }
            approveErr.hidden = true;
            confirmBtn.disabled = true;

            const res = await api.approveError(errItem.id, {
              deck_id: state.selectedDeckId,
              front,
              back,
              kind,
              explanation: explInput.value.trim() || null,
            });
            confirmBtn.disabled = false;

            if (!res.ok) {
              approveErr.textContent = res.error;
              approveErr.hidden = false;
              return;
            }

            state.openApproveId = null;
            state.suggestedOverrides.delete(errItem.id);
            showToast("Error aprobado y tarjeta programada para hoy.", { tone: "success" });
            await reloadErrors();
          },
        },
        suggestion
          ? el(
              "div",
              { className: "alert-banner alert-banner--info", style: "margin-bottom: 0;" },
              el("div", { className: "alert-copy" }, "Vista previa sugerida por la heurística local. Ajusta cualquier campo antes de aprobar."),
              renderKindBadge(suggestion.kind)
            )
          : null,
        el(
          "div",
          { className: "form-row-2" },
          el("div", { className: "field" }, el("label", { className: "field-label" }, "Mazo destino"), deckSelect),
          el("div", { className: "field" }, el("label", { className: "field-label" }, "Formato"), kindSelect)
        ),
        el("div", { className: "field" }, el("label", { className: "field-label" }, "Pregunta de la tarjeta"), frontInput),
        el("div", { className: "field" }, el("label", { className: "field-label" }, "Respuesta esperada"), backInput),
        el("div", { className: "field" }, el("label", { className: "field-label" }, "Explicación"), explInput),
        approveErr,
        el("div", { className: "form-actions" }, confirmBtn)
      );
    }

    return el(
      "article",
      { className: "item-card" },
      el(
        "div",
        { className: "item-card-head" },
        el(
          "div",
          { className: "folio-tags" },
          renderStatusBadge(errItem.status),
          el("span", { className: "badge num" }, `ID ${errItem.id}`),
          errItem.card_id
            ? el("span", { className: "badge badge--info num" }, `Tarjeta ${errItem.card_id}`)
            : null
        )
      ),
      el(
        "div",
        { className: "diff-grid" },
        el(
          "div",
          { className: "diff-pane diff-pane--attempted" },
          el("span", { className: "diff-label" }, "Lo que dijiste"),
          el("p", { className: "diff-text", dir: "auto" }, errItem.attempted)
        ),
        el(
          "div",
          { className: "diff-pane diff-pane--corrected" },
          el("span", { className: "diff-label" }, "Forma corregida"),
          el("p", { className: "diff-text", dir: "auto" }, errItem.corrected)
        )
      ),
      el("p", { className: "explanation-box", dir: "auto", style: "margin: 0 0 0.9rem;" }, errItem.rationale),
      el("div", { className: "page-actions" }, ...actions),
      approveDrawer
    );
  }

  function render() {
    clear(container);
    container.append(renderHeader(), renderComposer());

    if (state.error) {
      container.append(renderErrorBanner(state.error, load));
    }

    container.append(
      el(
        "div",
        { className: "section-heading" },
        el("h2", { className: "section-title" }, `Historial (${formatInt(state.errors.length)})`),
        el(
          "div",
          { className: "segmented", role: "group", "aria-label": "Filtrar errores por estado" },
          ...[
            { id: "", label: "Todos" },
            { id: "draft", label: "Borradores" },
            { id: "approved", label: "Aprobados" },
            { id: "discarded", label: "Descartados" },
          ].map((f) =>
            el(
              "button",
              {
                type: "button",
                className: "seg-btn",
                "aria-pressed": String(state.statusFilter === f.id),
                onClick: async () => {
                  state.statusFilter = f.id;
                  await reloadErrors();
                },
              },
              f.label
            )
          )
        )
      )
    );

    if (state.errors.length === 0) {
      container.append(
        renderEmptyState({
          variant: "cards",
          title: "No hay errores registrados con este filtro",
          description:
            "Pega arriba una respuesta de entrevista que quieras pulir o registra un fallo manualmente para practicarlo con SM-2.",
        })
      );
      return;
    }

    const list = el("div", { className: "stack" });
    for (const item of state.errors) {
      list.append(renderErrorCard(item));
    }
    container.append(list);
  }

  load();

  return () => {
    disposed = true;
    seq += 1;
  };
}
