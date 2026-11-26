import { api, isReadOnlyMode } from "../api.js";
import {
  KIND_META,
  clear,
  closeModal,
  createHoldDeleteButton,
  el,
  formatInt,
  openModal,
  plural,
  renderEmptyState,
  renderErrorBanner,
  renderKindBadge,
  renderSkeleton,
  renderStatusBadge,
  showToast,
} from "../ui.js";

const CLOZE_BLANK_RE = /_{4,}/g;
const MAX_LISTENING_CHARS = 1000;

export function mountCreate(container, ctx) {
  let disposed = false;
  let seq = 0;

  const validTabs = ["generar", "plantillas", "fuentes", "manual"];
  const state = {
    tab: validTabs.includes(ctx.params.tab) ? ctx.params.tab : "generar",
    decks: [],
    selectedDeckId: ctx.params.deck || "",
    templates: [],
    templateCategory: "all",
    sources: [],
    sourceStatusFilter: "",
    openApproveSourceId: null,
    lastGenerated: [],
    error: "",
  };

  async function loadBase() {
    const mySeq = ++seq;
    clear(container);
    container.append(renderSkeleton("dashboard"));

    const [decksRes, templatesRes, sourcesRes] = await Promise.all([
      api.listDecks(),
      api.listTemplates(),
      api.listSources(state.sourceStatusFilter),
    ]);
    if (disposed || mySeq !== seq) return;

    if (!decksRes.ok) {
      state.error = decksRes.error;
    } else {
      state.error = "";
      state.decks = decksRes.data || [];
      if (!state.selectedDeckId || !state.decks.some((d) => d.id === state.selectedDeckId)) {
        state.selectedDeckId = state.decks[0]?.id || "";
      }
    }

    if (templatesRes.ok) state.templates = templatesRes.data || [];
    if (sourcesRes.ok) state.sources = sourcesRes.data || [];

    render();
  }

  async function reloadSources() {
    const res = await api.listSources(state.sourceStatusFilter);
    if (disposed) return;
    if (!res.ok) {
      showToast(res.error, { tone: "error" });
      return;
    }
    state.sources = res.data || [];
    render();
  }

  function deckSelectElement(id, onChange) {
    if (state.decks.length === 0) {
      return el(
        "div",
        { className: "alert-banner alert-banner--info", style: "margin-bottom: 0;" },
        el("div", { className: "alert-copy" }, "Crea primero un mazo en la pestaña «Mazo / Manual» para guardar tarjetas.")
      );
    }
    return el(
      "select",
      {
        id,
        className: "select",
        onChange: (e) => {
          state.selectedDeckId = e.target.value;
          if (onChange) onChange(e.target.value);
        },
      },
      ...state.decks.map((d) =>
        el("option", { value: d.id, selected: d.id === state.selectedDeckId }, d.name)
      )
    );
  }

  function renderHeader() {
    return el(
      "header",
      { className: "page-header" },
      el(
        "div",
        { className: "page-header-copy" },
        el("p", { className: "eyebrow" }, "Taller de contenido"),
        el("h1", { className: "page-title" }, "Crear y curar material"),
        el(
          "p",
          { className: "page-lead" },
          "Genera fichas desde tus apuntes técnicos, añade plantillas de entrevista o aprueba fuentes curadas hacia tus mazos."
        )
      )
    );
  }

  function renderTabs() {
    const draftSources = state.sources.filter((s) => s.status === "draft").length;
    const tabs = [
      { id: "generar", label: "Generar desde texto", count: null },
      { id: "plantillas", label: "Plantillas", count: state.templates.length || null },
      { id: "fuentes", label: "Fuentes", count: draftSources || null },
      { id: "manual", label: "Mazo / Manual", count: null },
    ];

    return el(
      "div",
      { className: "tabs-bar", role: "tablist", "aria-label": "Modos de creación" },
      ...tabs.map((t) =>
        el(
          "button",
          {
            type: "button",
            role: "tab",
            className: "tab-btn",
            "aria-selected": String(state.tab === t.id),
            onClick: () => {
              state.tab = t.id;
              render();
            },
          },
          t.label,
          t.count !== null ? el("span", { className: "tab-count num" }, formatInt(t.count)) : null
        )
      )
    );
  }

  // --------------------------------------------------------------------------
  // Tab 1: Generate cards from text (POST /cards/generate)
  // --------------------------------------------------------------------------
  function renderGenerateTab() {
    const textArea = el("textarea", {
      id: "gen-text",
      className: "textarea",
      rows: "7",
      maxlength: "20000",
      placeholder:
        "Pega tus notas técnicas en inglés o español (mín. 10 caracteres). Ejemplo: AWS VPC networking, PostgreSQL transactions, Docker containers, Linux troubleshooting, Terraform...",
    });
    const charCounter = el("span", { className: "field-hint num" }, "0 / 20 000");
    textArea.addEventListener("input", () => {
      charCounter.textContent = `${formatInt(textArea.value.length)} / 20 000`;
    });

    const maxInput = el("input", {
      id: "gen-max",
      type: "number",
      className: "input",
      min: "1",
      max: "20",
      value: "6",
      inputmode: "numeric",
    });

    const errNode = el("div", { className: "field-error", role: "alert", hidden: true });
    const submitBtn = el(
      "button",
      { type: "submit", className: "btn btn--primary", disabled: state.decks.length === 0 },
      "Generar tarjetas"
    );

    const form = el(
      "form",
      {
        className: "form-grid",
        onSubmit: async (e) => {
          e.preventDefault();
          const text = textArea.value.trim();
          const maxCards = Number(maxInput.value);
          if (!state.selectedDeckId) {
            errNode.textContent = "Selecciona un mazo destino.";
            errNode.hidden = false;
            return;
          }
          if (text.length < 10) {
            errNode.textContent = "Escribe al menos 10 caracteres para generar tarjetas útiles.";
            errNode.hidden = false;
            textArea.focus();
            return;
          }
          if (!Number.isInteger(maxCards) || maxCards < 1 || maxCards > 20) {
            errNode.textContent = "El máximo de tarjetas debe estar entre 1 y 20.";
            errNode.hidden = false;
            maxInput.focus();
            return;
          }

          errNode.hidden = true;
          submitBtn.disabled = true;
          submitBtn.textContent = "Generando…";

          const res = await api.generateCards({
            deck_id: state.selectedDeckId,
            text,
            max_cards: maxCards,
          });

          submitBtn.disabled = false;
          submitBtn.textContent = "Generar tarjetas";

          if (!res.ok) {
            errNode.textContent = res.error;
            errNode.hidden = false;
            return;
          }

          state.lastGenerated = res.data || [];
          showToast(`Se generaron ${plural(state.lastGenerated.length, "tarjeta", "tarjetas")}.`, {
            tone: "success",
          });
          ctx.refreshGlobalBadges();
          render();
        },
      },
      el(
        "div",
        { className: "form-row-2" },
        el(
          "div",
          { className: "field" },
          el("label", { className: "field-label", for: "gen-deck" }, "Mazo destino"),
          deckSelectElement("gen-deck")
        ),
        el(
          "div",
          { className: "field" },
          el(
            "div",
            { className: "field-label-row" },
            el("label", { className: "field-label", for: "gen-max" }, "Máximo de tarjetas"),
            el("span", { className: "field-hint" }, "1 a 20")
          ),
          maxInput
        )
      ),
      el(
        "div",
        { className: "field" },
        el(
          "div",
          { className: "field-label-row" },
          el("label", { className: "field-label", for: "gen-text" }, "Texto fuente o notas técnicas"),
          charCounter
        ),
        textArea
      ),
      errNode,
      el("div", { className: "form-actions" }, submitBtn)
    );

    const resultsNode =
      state.lastGenerated.length > 0
        ? el(
            "section",
            { className: "panel" },
            el(
              "div",
              { className: "panel-header" },
              el(
                "div",
                {},
                el("h2", { className: "panel-title" }, "Tarjetas recién generadas"),
                el(
                  "p",
                  { className: "panel-subtitle" },
                  `${plural(state.lastGenerated.length, "ficha lista", "fichas listas")} para repasar hoy.`
                )
              ),
              el(
                "button",
                {
                  type: "button",
                  className: "btn btn--primary btn--sm",
                  onClick: () => ctx.navigate("estudiar", { deck: state.selectedDeckId }),
                },
                "Estudiar este mazo"
              )
            ),
            el(
              "div",
              { className: "stack" },
              ...state.lastGenerated.map((c) =>
                el(
                  "div",
                  { className: "card-row" },
                  el(
                    "div",
                    { className: "card-row-body" },
                    el("p", { className: "card-row-front", dir: "auto" }, c.front),
                    el("p", { className: "card-row-back", dir: "auto" }, c.back),
                    el("div", { className: "card-row-meta" }, renderKindBadge(c.kind))
                  )
                )
              )
            )
          )
        : null;

    return el(
      "div",
      { className: "stack" },
      el(
        "section",
        { className: "panel" },
        el(
          "div",
          { className: "panel-header" },
          el(
            "div",
            {},
            el("h2", { className: "panel-title" }, "Generar desde texto"),
            el(
              "p",
              { className: "panel-subtitle" },
              "Usa el generador local de la API (POST /cards/generate) para extraer vocabulario y prompts de práctica."
            )
          )
        ),
        form
      ),
      resultsNode
    );
  }

  // --------------------------------------------------------------------------
  // Tab 2: Template Gallery (GET /templates, POST /templates/{id}/cards)
  // --------------------------------------------------------------------------
  function renderTemplatesTab() {
    const filtered =
      state.templateCategory === "all"
        ? state.templates
        : state.templates.filter((t) => t.category === state.templateCategory);

    const toolbar = el(
      "section",
      { className: "study-toolbar" },
      el(
        "div",
        { className: "study-toolbar-field" },
        el("label", { className: "field-hint", for: "tpl-deck", style: "display:block;margin-bottom:4px;" }, "Guardar plantilla en el mazo:"),
        deckSelectElement("tpl-deck")
      ),
      el(
        "div",
        { className: "segmented", role: "group", "aria-label": "Filtrar categoría de plantillas" },
        ...[
          { id: "all", label: "Todas" },
          { id: "star", label: "STAR" },
          { id: "networking", label: "Networking" },
        ].map((cat) =>
          el(
            "button",
            {
              type: "button",
              className: "seg-btn",
              "aria-pressed": String(state.templateCategory === cat.id),
              onClick: () => {
                state.templateCategory = cat.id;
                render();
              },
            },
            cat.label
          )
        )
      )
    );

    if (filtered.length === 0) {
      return el(
        "div",
        { className: "stack" },
        toolbar,
        renderEmptyState({
          variant: "cards",
          title: "No hay plantillas en esta categoría",
          description: "Cambia el filtro para ver todo el catálogo disponible en /templates.",
        })
      );
    }

    const grid = el(
      "div",
      { className: "template-grid" },
      ...filtered.map((tpl) => {
        const addBtn = el(
          "button",
          {
            type: "button",
            className: "btn btn--primary btn--sm",
            disabled: state.decks.length === 0,
            onClick: async () => {
              if (!state.selectedDeckId) return;
              addBtn.disabled = true;
              addBtn.textContent = "Añadiendo…";
              const res = await api.createCardFromTemplate(tpl.id, state.selectedDeckId);
              addBtn.disabled = false;
              addBtn.textContent = "Añadir al mazo";
              if (!res.ok) {
                showToast(res.error, { tone: "error" });
                return;
              }
              showToast(`Plantilla «${tpl.title}» añadida al mazo.`, { tone: "success" });
              ctx.refreshGlobalBadges();
            },
          },
          "Añadir al mazo"
        );

        return el(
          "article",
          { className: "template-card" },
          el(
            "div",
            { className: "stack", style: "gap: 0.75rem;" },
            el(
              "div",
              { className: "item-card-head", style: "margin-bottom: 0;" },
              el("h3", { className: "item-title", dir: "auto" }, tpl.title),
              el(
                "div",
                { className: "folio-tags" },
                el("span", { className: "badge badge--info" }, tpl.category.toUpperCase()),
                renderKindBadge(tpl.kind)
              )
            ),
            el(
              "div",
              {},
              el("span", { className: "diff-label" }, "Pregunta / Prompt"),
              el("div", { className: "template-block", dir: "auto" }, tpl.front)
            ),
            el(
              "div",
              {},
              el("span", { className: "diff-label" }, "Guía de respuesta"),
              el("div", { className: "template-block", dir: "auto" }, tpl.back)
            ),
            tpl.follow_up_questions && tpl.follow_up_questions.length > 0
              ? el(
                  "div",
                  {},
                  el("span", { className: "diff-label" }, "Preguntas de seguimiento"),
                  el(
                    "ul",
                    { className: "followup-list" },
                    ...tpl.follow_up_questions.map((q) => el("li", {}, q))
                  )
                )
              : null,
            tpl.explanation ? el("p", { className: "field-hint", style: "margin: 0;" }, tpl.explanation) : null
          ),
          el("div", { className: "form-actions" }, addBtn)
        );
      })
    );

    return el("div", { className: "stack" }, toolbar, grid);
  }

  // --------------------------------------------------------------------------
  // Tab 3: Sources Curation (/sources, approve, discard)
  // --------------------------------------------------------------------------
  function renderSourcesTab() {
    const labelInput = el("input", {
      id: "src-label",
      type: "text",
      className: "input",
      required: true,
      maxlength: "255",
      placeholder: "Ej. AWS VPC User Guide — NAT Gateways",
    });
    const urlInput = el("input", {
      id: "src-url",
      type: "url",
      className: "input",
      maxlength: "2048",
      placeholder: "https://docs.aws.amazon.com/...",
      autocapitalize: "none",
      autocorrect: "off",
    });
    const excerptInput = el("textarea", {
      id: "src-excerpt",
      className: "textarea",
      rows: "3",
      maxlength: "20000",
      placeholder: "Fragmento relevante de documentación o artículo (opcional)",
    });
    const srcErr = el("div", { className: "field-error", role: "alert", hidden: true });
    const srcSubmit = el("button", { type: "submit", className: "btn btn--primary" }, "Guardar borrador de fuente");

    const createForm = el(
      "form",
      {
        className: "form-grid",
        onSubmit: async (e) => {
          e.preventDefault();
          const label = labelInput.value.trim();
          const url = urlInput.value.trim();
          const excerpt = excerptInput.value.trim();
          if (!label) {
            srcErr.textContent = "La etiqueta de la fuente es obligatoria.";
            srcErr.hidden = false;
            labelInput.focus();
            return;
          }
          srcErr.hidden = true;
          srcSubmit.disabled = true;

          const res = await api.createSource({
            label,
            url: url || null,
            excerpt: excerpt || null,
          });
          srcSubmit.disabled = false;

          if (!res.ok) {
            srcErr.textContent = res.error;
            srcErr.hidden = false;
            return;
          }
          labelInput.value = "";
          urlInput.value = "";
          excerptInput.value = "";
          showToast("Fuente registrada en borrador.", { tone: "success" });
          await reloadSources();
        },
      },
      el(
        "div",
        { className: "form-row-2" },
        el("div", { className: "field" }, el("label", { className: "field-label", for: "src-label" }, "Etiqueta / Título"), labelInput),
        el("div", { className: "field" }, el("label", { className: "field-label", for: "src-url" }, "URL (opcional, única)"), urlInput)
      ),
      el("div", { className: "field" }, el("label", { className: "field-label", for: "src-excerpt" }, "Extracto (opcional)"), excerptInput),
      srcErr,
      el("div", { className: "form-actions" }, srcSubmit)
    );

    const filterRow = el(
      "div",
      { className: "section-heading", style: "margin-top: 1.5rem;" },
      el("h2", { className: "section-title" }, "Bandeja de fuentes"),
      el(
        "div",
        { className: "segmented", role: "group", "aria-label": "Filtrar fuentes por estado" },
        ...[
          { id: "", label: "Todas" },
          { id: "draft", label: "Borradores" },
          { id: "approved", label: "Aprobadas" },
          { id: "discarded", label: "Descartadas" },
        ].map((st) =>
          el(
            "button",
            {
              type: "button",
              className: "seg-btn",
              "aria-pressed": String(state.sourceStatusFilter === st.id),
              onClick: async () => {
                state.sourceStatusFilter = st.id;
                await reloadSources();
              },
            },
            st.label
          )
        )
      )
    );

    const listNode =
      state.sources.length === 0
        ? renderEmptyState({
            variant: "cards",
            title: "No hay fuentes en esta vista",
            description: "Guarda enlaces o extractos técnicos para revisarlos y convertirlos en tarjetas verificadas.",
          })
        : el(
            "div",
            { className: "stack" },
            ...state.sources.map((src) => renderSourceCard(src))
          );

    return el(
      "div",
      { className: "stack" },
      el(
        "section",
        { className: "panel" },
        el(
          "div",
          { className: "panel-header" },
          el(
            "div",
            {},
            el("h2", { className: "panel-title" }, "Nueva fuente de estudio"),
            el("p", { className: "panel-subtitle" }, "Evita duplicados por URL normalizada (HTTP 409) y aprueba cada fuente hacia una tarjeta.")
          )
        ),
        createForm
      ),
      filterRow,
      listNode
    );
  }

  function renderSourceCard(src) {
    const isDraft = src.status === "draft";
    const isApproveOpen = state.openApproveSourceId === src.id;

    const actions = [];
    if (isDraft) {
      actions.push(
        el(
          "button",
          {
            type: "button",
            className: "btn btn--primary btn--sm",
            onClick: () => {
              state.openApproveSourceId = isApproveOpen ? null : src.id;
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
            onClick: () => openEditSourceModal(src),
          },
          "Editar"
        ),
        el(
          "button",
          {
            type: "button",
            className: "btn btn--ghost btn--sm",
            onClick: async () => {
              const res = await api.discardSource(src.id);
              if (!res.ok) {
                showToast(res.error, { tone: "error" });
                return;
              }
              showToast("Fuente descartada.", { tone: "warning" });
              await reloadSources();
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
          const res = await api.deleteSource(src.id);
          if (!res.ok) {
            showToast(res.error, { tone: "error" });
            return;
          }
          showToast("Fuente eliminada.", { tone: "warning" });
          await reloadSources();
        },
      })
    );

    let approveDrawer = null;
    if (isDraft && isApproveOpen) {
      const frontInput = el("textarea", {
        className: "textarea",
        rows: "2",
        required: true,
        value: `Explain key concepts from: ${src.label}`,
      });
      const backInput = el("textarea", {
        className: "textarea",
        rows: "3",
        required: true,
        value: src.excerpt || "",
        placeholder: "Respuesta concreta para la tarjeta",
      });
      const kindSelect = el(
        "select",
        { className: "select" },
        ...Object.entries(KIND_META).map(([k, meta]) =>
          el("option", { value: k, selected: k === "vocabulary" }, meta.label)
        )
      );
      const expInput = el("input", {
        type: "text",
        className: "input",
        placeholder: "Explicación breve (opcional)",
      });
      const approveErr = el("div", { className: "field-error", role: "alert", hidden: true });
      const approveSubmit = el(
        "button",
        { type: "submit", className: "btn btn--success btn--sm", disabled: state.decks.length === 0 },
        "Confirmar y crear tarjeta"
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
            const validationError = validateCardFormat(front, back, kind);
            if (validationError) {
              approveErr.textContent = validationError;
              approveErr.hidden = false;
              return;
            }
            approveErr.hidden = true;
            approveSubmit.disabled = true;

            const res = await api.approveSource(src.id, {
              deck_id: state.selectedDeckId,
              front,
              back,
              kind,
              explanation: expInput.value.trim() || null,
            });
            approveSubmit.disabled = false;

            if (!res.ok) {
              approveErr.textContent = res.error;
              approveErr.hidden = false;
              return;
            }
            state.openApproveSourceId = null;
            showToast("Fuente aprobada y convertida en tarjeta.", { tone: "success" });
            ctx.refreshGlobalBadges();
            await reloadSources();
          },
        },
        el(
          "div",
          { className: "form-row-2" },
          el("div", { className: "field" }, el("label", { className: "field-label" }, "Mazo destino"), deckSelectElement(`src-deck-${src.id}`)),
          el("div", { className: "field" }, el("label", { className: "field-label" }, "Formato"), kindSelect)
        ),
        el("div", { className: "field" }, el("label", { className: "field-label" }, "Pregunta (frente)"), frontInput),
        el("div", { className: "field" }, el("label", { className: "field-label" }, "Respuesta (reverso)"), backInput),
        el("div", { className: "field" }, el("label", { className: "field-label" }, "Explicación (opcional)"), expInput),
        approveErr,
        el("div", { className: "form-actions" }, approveSubmit)
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
          { style: "min-width: 0; flex: 1 1 220px;" },
          el("h3", { className: "item-title", dir: "auto" }, src.label),
          src.url
            ? el(
                "a",
                {
                  className: "source-url",
                  href: src.url,
                  target: "_blank",
                  rel: "noopener noreferrer",
                },
                src.url
              )
            : null
        ),
        renderStatusBadge(src.status)
      ),
      src.excerpt ? el("p", { className: "template-block", dir: "auto", style: "margin: 0 0 0.85rem;" }, src.excerpt) : null,
      el("div", { className: "page-actions" }, ...actions),
      approveDrawer
    );
  }

  function openEditSourceModal(src) {
    const labelInput = el("input", { type: "text", className: "input", required: true, maxlength: "255", value: src.label });
    const urlInput = el("input", { type: "url", className: "input", maxlength: "2048", value: src.url || "" });
    const excerptInput = el("textarea", { className: "textarea", rows: "4", maxlength: "20000", value: src.excerpt || "" });
    const errNode = el("div", { className: "field-error", role: "alert", hidden: true });
    const saveBtn = el("button", { type: "submit", className: "btn btn--primary" }, "Guardar cambios");

    const form = el(
      "form",
      {
        className: "form-grid",
        onSubmit: async (e) => {
          e.preventDefault();
          errNode.hidden = true;
          saveBtn.disabled = true;
          const res = await api.updateSource(src.id, {
            label: labelInput.value.trim(),
            url: urlInput.value.trim() || null,
            excerpt: excerptInput.value.trim() || null,
          });
          saveBtn.disabled = false;
          if (!res.ok) {
            errNode.textContent = res.error;
            errNode.hidden = false;
            return;
          }
          closeModal();
          showToast("Fuente actualizada.", { tone: "success" });
          await reloadSources();
        },
      },
      el("div", { className: "field" }, el("label", { className: "field-label" }, "Etiqueta"), labelInput),
      el("div", { className: "field" }, el("label", { className: "field-label" }, "URL"), urlInput),
      el("div", { className: "field" }, el("label", { className: "field-label" }, "Extracto"), excerptInput),
      errNode,
      el(
        "div",
        { className: "form-actions" },
        el("button", { type: "button", className: "btn btn--secondary", onClick: closeModal }, "Cancelar"),
        saveBtn
      )
    );

    openModal({ title: "Editar fuente", content: form });
  }

  // --------------------------------------------------------------------------
  // Tab 4: Manual Deck & Manual Card (POST /decks, POST /cards)
  // --------------------------------------------------------------------------
  function renderManualTab() {
    // Deck creation panel
    const deckName = el("input", {
      id: "manual-deck-name",
      type: "text",
      className: "input",
      required: true,
      maxlength: "120",
      placeholder: "Ej. Cloud interviews",
    });
    const deckDesc = el("textarea", {
      id: "manual-deck-desc",
      className: "textarea",
      rows: "3",
      maxlength: "5000",
      placeholder: "Descripción breve del mazo (opcional)",
    });
    const deckErr = el("div", { className: "field-error", role: "alert", hidden: true });
    const deckSubmit = el("button", { type: "submit", className: "btn btn--primary" }, "Crear mazo");

    const deckForm = el(
      "form",
      {
        className: "form-grid",
        onSubmit: async (e) => {
          e.preventDefault();
          const name = deckName.value.trim();
          if (!name) {
            deckErr.textContent = "Escribe un nombre para el mazo.";
            deckErr.hidden = false;
            return;
          }
          deckErr.hidden = true;
          deckSubmit.disabled = true;
          const res = await api.createDeck({ name, description: deckDesc.value.trim() });
          deckSubmit.disabled = false;
          if (!res.ok) {
            deckErr.textContent = res.error;
            deckErr.hidden = false;
            return;
          }
          state.selectedDeckId = res.data.id;
          deckName.value = "";
          deckDesc.value = "";
          showToast(`Mazo «${res.data.name}» creado.`, { tone: "success" });
          await loadBase();
        },
      },
      el("div", { className: "field" }, el("label", { className: "field-label", for: "manual-deck-name" }, "Nombre"), deckName),
      el("div", { className: "field" }, el("label", { className: "field-label", for: "manual-deck-desc" }, "Descripción"), deckDesc),
      deckErr,
      el("div", { className: "form-actions" }, deckSubmit)
    );

    // Manual card creation panel
    const cardKind = el(
      "select",
      { id: "manual-card-kind", className: "select" },
      ...Object.entries(KIND_META).map(([k, meta]) => el("option", { value: k }, meta.label))
    );
    const formatHint = el("span", { className: "field-hint" }, "");
    const cardFront = el("textarea", {
      id: "manual-card-front",
      className: "textarea",
      rows: "3",
      required: true,
      maxlength: "5000",
      placeholder: "Pregunta, frase en español o texto con hueco ____",
    });
    const cardBack = el("textarea", {
      id: "manual-card-back",
      className: "textarea",
      rows: "3",
      required: true,
      maxlength: "5000",
      placeholder: "Respuesta esperada o transcripción (listening: máx. 1000 caracteres)",
    });
    const cardAccepted = el("input", {
      id: "manual-card-accepted",
      type: "text",
      className: "input",
      placeholder: "Variantes aceptadas separadas por | (opcional)",
    });
    const cardSource = el("input", {
      id: "manual-card-source",
      type: "text",
      className: "input",
      maxlength: "255",
      placeholder: "Etiqueta de origen (opcional)",
    });
    const cardExpl = el("textarea", {
      id: "manual-card-expl",
      className: "textarea",
      rows: "2",
      maxlength: "5000",
      placeholder: "Nota o explicación que aparece al revelar (opcional)",
    });
    const cardErr = el("div", { className: "field-error", role: "alert", hidden: true });
    const cardSubmit = el(
      "button",
      { type: "submit", className: "btn btn--primary", disabled: state.decks.length === 0 },
      "Guardar tarjeta"
    );

    const syncHint = () => {
      if (cardKind.value === "cloze") {
        formatHint.textContent = "Formato cloze: la pregunta debe contener exactamente un hueco «____» (4 guiones bajos).";
      } else if (cardKind.value === "listening") {
        formatHint.textContent = "Formato listening: la respuesta/transcripción admite hasta 1000 caracteres.";
      } else {
        formatHint.textContent = "";
      }
    };
    cardKind.addEventListener("change", syncHint);
    syncHint();

    const cardForm = el(
      "form",
      {
        className: "form-grid",
        onSubmit: async (e) => {
          e.preventDefault();
          const front = cardFront.value.trim();
          const back = cardBack.value.trim();
          const kind = cardKind.value;
          const validationError = validateCardFormat(front, back, kind);
          if (validationError) {
            cardErr.textContent = validationError;
            cardErr.hidden = false;
            return;
          }
          cardErr.hidden = true;
          cardSubmit.disabled = true;

          const accepted = cardAccepted.value
            .split("|")
            .map((s) => s.trim())
            .filter(Boolean);

          const res = await api.createCard({
            deck_id: state.selectedDeckId,
            front,
            back,
            kind,
            source_label: cardSource.value.trim() || null,
            accepted_answers: accepted,
            explanation: cardExpl.value.trim() || null,
          });
          cardSubmit.disabled = false;

          if (!res.ok) {
            cardErr.textContent = res.error;
            cardErr.hidden = false;
            return;
          }
          cardFront.value = "";
          cardBack.value = "";
          cardAccepted.value = "";
          cardSource.value = "";
          cardExpl.value = "";
          showToast("Tarjeta guardada y programada para hoy.", { tone: "success" });
          ctx.refreshGlobalBadges();
        },
      },
      el(
        "div",
        { className: "form-row-2" },
        el("div", { className: "field" }, el("label", { className: "field-label", for: "manual-card-deck" }, "Mazo"), deckSelectElement("manual-card-deck")),
        el("div", { className: "field" }, el("label", { className: "field-label", for: "manual-card-kind" }, "Formato"), cardKind)
      ),
      formatHint,
      el("div", { className: "field" }, el("label", { className: "field-label", for: "manual-card-front" }, "Pregunta (frente)"), cardFront),
      el("div", { className: "field" }, el("label", { className: "field-label", for: "manual-card-back" }, "Respuesta (reverso)"), cardBack),
      el(
        "div",
        { className: "form-row-2" },
        el("div", { className: "field" }, el("label", { className: "field-label", for: "manual-card-accepted" }, "Respuestas aceptadas"), cardAccepted),
        el("div", { className: "field" }, el("label", { className: "field-label", for: "manual-card-source" }, "Origen"), cardSource)
      ),
      el("div", { className: "field" }, el("label", { className: "field-label", for: "manual-card-expl" }, "Explicación"), cardExpl),
      cardErr,
      el("div", { className: "form-actions" }, cardSubmit)
    );

    return el(
      "div",
      { className: "split-layout" },
      el(
        "section",
        { className: "panel" },
        el(
          "div",
          { className: "panel-header" },
          el("div", {}, el("h2", { className: "panel-title" }, "Crear tarjeta manual"), el("p", { className: "panel-subtitle" }, "Compatible con los 7 formatos del esquema."))
        ),
        cardForm
      ),
      el(
        "section",
        { className: "panel" },
        el(
          "div",
          { className: "panel-header" },
          el("div", {}, el("h2", { className: "panel-title" }, "Nuevo mazo"), el("p", { className: "panel-subtitle" }, "Organiza tus entrevistas o temas por colección."))
        ),
        deckForm
      )
    );
  }

  function validateCardFormat(front, back, kind) {
    if (!state.selectedDeckId) return "Selecciona un mazo destino.";
    if (!front || !back) return "Completa tanto la pregunta como la respuesta.";
    if (kind === "cloze") {
      const blanks = front.match(CLOZE_BLANK_RE) || [];
      if (blanks.length !== 1 || blanks[0] !== "____") {
        return "Las tarjetas cloze deben incluir exactamente un hueco «____» (4 guiones bajos).";
      }
    }
    if (kind === "listening" && back.length > MAX_LISTENING_CHARS) {
      return `La transcripción de audio admite como máximo ${MAX_LISTENING_CHARS} caracteres.`;
    }
    return "";
  }

  function render() {
    clear(container);
    container.append(renderHeader(), renderTabs());

    if (state.error) {
      container.append(renderErrorBanner(state.error, loadBase));
    }

    if (state.tab === "generar") container.append(renderGenerateTab());
    else if (state.tab === "plantillas") container.append(renderTemplatesTab());
    else if (state.tab === "fuentes") container.append(renderSourcesTab());
    else container.append(renderManualTab());
  }

  loadBase();

  return () => {
    disposed = true;
    seq += 1;
  };
}
