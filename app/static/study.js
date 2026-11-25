(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const state = {
    card: null,
    loadSeq: 0,
    deckSeq: 0,
    decks: new Map(),
    selectionRevision: 0,
    creatingDeck: false,
    uncertainDeckNames: new Set(),
    grading: false,
    templatesLoaded: false,
    templateSeq: 0,
    activeTemplateId: null,
    templateWrites: new Map(),
    errorsLoaded: false,
    errorSeq: 0,
    pendingErrors: new Map(),
    errorOverrides: new Map(),
    errorRowStatus: new Map(),
  };

  function el(tag, props = {}, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (k === "ariaLabel") node.setAttribute("aria-label", v);
      else if (k === "role") node.setAttribute("role", v);
      else node[k] = v;
    }
    node.append(...children);
    return node;
  }

  function setStatus(node, text, kind = "") {
    node.textContent = text;
    node.className = kind ? `status ${kind}` : "status";
  }

  // Match whole JSON strings (including escapes), so ID-like text inside
  // card content is never rewritten. Only object properties with a complete
  // decimal integer value are candidates. JSON.parse validates the result.
  function parseApiJson(raw) {
    const stringWithInteger = /("(?:[^"\\]|\\.)*")(?:(\s*:\s*)([1-9]\d*)(?=\s*[,}]))?/g;
    const exact = raw.replace(stringWithInteger, (token, quoted, colon, digits) => {
      if (!digits) return token;
      const key = JSON.parse(quoted);
      return key === "id" || key.endsWith("_id") ? quoted + colon + '"' + digits + '"' : token;
    });
    return JSON.parse(exact, (key, value) => {
      if (typeof value === "number" && (key === "id" || key.endsWith("_id"))) {
        throw new RangeError("La API devolvió un ID con formato inesperado.");
      }
      return value;
    });
  }

  async function api(path, options = {}) {
    try {
      const headers = options.body ? { "Content-Type": "application/json" } : {};
      const res = await fetch(path, { ...options, headers: { ...headers, ...options.headers } });
      const raw = res.status === 204 ? "" : await res.text();
      let data = null;
      if (raw) {
        try {
          data = parseApiJson(raw);
        } catch (err) {
          if (res.ok) return { ok: false, status: res.status, error: err instanceof RangeError ? err.message : "La API devolvió una respuesta no válida." };
          data = { detail: raw };
        }
      }
      const d = data?.detail;
      const error = res.ok
        ? ""
        : typeof d === "string"
          ? d
          : Array.isArray(d) ? d.map((x) => x.msg || String(x)).join("; ") : `HTTP ${res.status}`;
      return { ok: res.ok, status: res.status, data, error };
    } catch {
      return { ok: false, status: 0, data: null, error: "No se pudo conectar con la API local. Comprueba la conexión y vuelve a intentarlo." };
    }
  }

  const post = (path, body) =>
    api(path, body === undefined ? { method: "POST" } : { method: "POST", body: JSON.stringify(body) });

  const deckIdValue = () => (/^[1-9]\d*$/.test($("deck-id").value.trim()) ? $("deck-id").value.trim() : null);
  const fillList = (ul, items) => ul.replaceChildren(...items.map((text) => el("li", { textContent: text })));
  const setGradeDisabled = (disabled) =>
    $("grade-controls").querySelectorAll("button[data-quality]").forEach((btn) => { btn.disabled = disabled; });
  const setStudyNavDisabled = (disabled) => {
    for (const id of ["deck-select", "deck-search", "deck-id", "load-next-btn", "refresh-decks-btn"]) $(id).disabled = disabled;
    $("deck-fields").disabled = disabled || state.creatingDeck;
  };

  function destinationLabel(deckId) {
    if (!deckId) return "Destino: selecciona un mazo o escribe un ID válido.";
    const deck = state.decks.get(deckId);
    return deck ? `Destino: ${deck.name} (#${deckId})` : `Destino: mazo #${deckId}`;
  }

  function syncDestinations() {
    const deckId = deckIdValue();
    $("template-destination").textContent = destinationLabel(deckId);
    for (const row of $("errors-list").querySelectorAll("[data-error-id]")) {
      const id = row.dataset.errorId;
      row.querySelector(".deck-destination").textContent = destinationLabel(state.pendingErrors.get(id) || deckId);
      row.querySelector(".approve-error").disabled = !deckId || state.pendingErrors.has(id);
    }
    syncTemplateAction();
  }

  function clearAnswer() {
    $("answer-panel").hidden = $("accepted-wrap").hidden = $("explanation-wrap").hidden = true;
    $("card-back").textContent = $("card-explanation").textContent = "";
    $("card-accepted").replaceChildren();
  }

  function renderDeckPicker() {
    const current = deckIdValue();
    const query = $("deck-search").value.trim().toLocaleLowerCase("es");
    const options = document.createDocumentFragment();
    options.append(new Option("Elige un mazo", ""));
    let matches = 0;
    for (const deck of state.decks.values()) {
      const matched = deck.name.toLocaleLowerCase("es").includes(query) || deck.id.includes(query);
      if (matched) matches++;
      if (matched || deck.id === current) {
        const prefix = matched ? "" : "Mazo actual: ";
        options.append(new Option(`${prefix}#${deck.id} — ${deck.name}`, deck.id));
      }
    }
    $("deck-select").replaceChildren(options);
    $("deck-select").value = state.decks.has(current) ? current : "";
    return matches;
  }

  function renderDeckList() {
    const matches = renderDeckPicker();
    let message = "";
    if ($("deck-search").value.trim()) message = `Coincidencias: ${matches}.`;
    else if (!state.decks.size) message = "Aún no hay mazos. Abre «Crear un mazo» para empezar.";
    setStatus($("deck-list-status"), message);
  }

  async function loadDecks(autoSelect = true) {
    const seq = ++state.deckSeq;
    const revision = state.selectionRevision;
    const decks = new Map();
    const pageSize = 100;
    setStatus($("deck-list-status"), "Cargando mazos…");
    for (let offset = 0; ; offset += pageSize) {
      const res = await api(`/decks?offset=${offset}&limit=${pageSize}`);
      if (seq !== state.deckSeq) return;
      if (!res.ok || !Array.isArray(res.data)) {
        return setStatus($("deck-list-status"), res.error || "No se pudo cargar la lista de mazos.", "error");
      }
      for (const deck of res.data) decks.set(deck.id, deck);
      if (res.data.length < pageSize) break;
    }
    state.decks = decks;
    const pickFirst = autoSelect && decks.size && revision === state.selectionRevision && !state.grading &&
      !$("deck-id").value.trim() && !$("deck-search").value.trim();
    if (pickFirst) $("deck-id").value = decks.keys().next().value;
    renderDeckList();
    syncDestinations();
    if (pickFirst) await loadNextCard();
  }

  async function createDeck(event) {
    event.preventDefault();
    if (state.grading || state.creatingDeck) return;
    const input = $("deck-name");
    const name = input.value.trim();
    const status = $("deck-create-status");
    if (!name) {
      input.focus();
      return setStatus(status, "Escribe un nombre para el mazo.", "error");
    }
    const uncertainMessage = "No se pudo confirmar la creación. Actualiza la lista y busca el mazo antes de volver a crearlo.";
    if (state.uncertainDeckNames.has(name)) return setStatus(status, uncertainMessage, "error");
    const revision = state.selectionRevision;
    state.creatingDeck = true;
    $("deck-fields").disabled = true;
    setStatus(status, "Creando mazo…");
    const res = await post("/decks", { name });
    state.creatingDeck = false;
    $("deck-fields").disabled = state.grading;
    if (!res.ok || !res.data?.id) {
      if (res.status >= 400 && res.status < 500) return setStatus(status, res.error, "error");
      state.uncertainDeckNames.add(name);
      return setStatus(status, uncertainMessage, "error");
    }
    input.value = "";
    const deck = res.data;
    state.decks.set(deck.id, deck);
    setStatus(status, `Mazo «${deck.name}» creado (#${deck.id}).`, "ok");
    const selectCreated = !state.grading && revision === state.selectionRevision;
    if (selectCreated) {
      state.selectionRevision++;
      $("deck-search").value = "";
      $("deck-id").value = deck.id;
    }
    renderDeckList();
    syncDestinations();
    if (selectCreated) loadNextCard();
    // A list request started before this POST can lack the new deck.
    loadDecks(false);
  }

  async function loadNextCard(note = "", focusFrom = null) {
    if (state.grading) return;
    const status = $("study-status");
    const deckId = deckIdValue();
    if (deckId === null) {
      state.loadSeq++;
      state.card = null;
      clearAnswer();
      $("study-card").hidden = true;
      return setStatus(status, "Selecciona un mazo o escribe un ID entero mayor que cero.", "error");
    }
    const select = $("deck-select");
    select.value = [...select.options].some((o) => o.value === String(deckId)) ? String(deckId) : "";
    const seq = ++state.loadSeq;
    state.card = null;
    clearAnswer();
    $("study-card").hidden = true;
    setStatus(status, note ? `${note} Cargando tarjeta…` : "Cargando tarjeta…");

    const res = await api(`/study/next?deck_id=${encodeURIComponent(deckId)}`);
    if (seq !== state.loadSeq || state.grading) return;
    const restoreFocus = focusFrom && document.activeElement === focusFrom;
    if (restoreFocus) $("load-next-btn").focus();
    if (res.status === 204) {
      return setStatus(status, note ? `${note} Terminaste las tarjetas pendientes.` : "Estás al día con este mazo. Puedes elegir otro o añadir una tarjeta desde Plantillas.", "ok");
    }
    if (res.status === 404) return setStatus(status, `No se encontró el mazo #${deckId}.`, "error");
    if (!res.ok || !res.data) return setStatus(status, res.error, "error");

    const c = res.data;
    state.card = c;
    $("card-meta").textContent = [
      `Tarjeta #${c.card_id}`, c.kind, c.source_label ? `fuente: ${c.source_label}` : null,
      `fecha de repaso: ${c.due_date}`, `repasos: ${c.repetitions}`, `intervalo: ${c.interval_days}d`, `facilidad: ${c.ease_factor}`,
    ].filter(Boolean).join(" · ");
    $("card-front").textContent = c.front;
    $("reveal-btn").disabled = false;
    setGradeDisabled(true);
    $("study-card").hidden = false;
    if (restoreFocus) $("reveal-btn").focus();
    setStatus(status, note, note ? "ok" : "");
  }

  async function revealCard() {
    if (!state.card || state.grading || $("reveal-btn").disabled) return;
    const cardId = state.card.card_id;
    const seq = state.loadSeq;
    $("card-heading").focus();
    $("reveal-btn").disabled = true;
    const res = await post(`/study/${encodeURIComponent(cardId)}/reveal`);
    if (seq !== state.loadSeq || state.grading || !state.card || state.card.card_id !== cardId) return;
    if (!res.ok || !res.data) {
      $("reveal-btn").disabled = false;
      if (document.activeElement === $("card-heading")) $("reveal-btn").focus();
      return setStatus($("study-status"), res.error, "error");
    }
    $("card-back").textContent = res.data.back;
    const accepted = Array.isArray(res.data.accepted_answers) ? res.data.accepted_answers : [];
    if (accepted.length > 0) {
      fillList($("card-accepted"), accepted);
      $("accepted-wrap").hidden = false;
    }
    if (res.data.explanation) {
      $("card-explanation").textContent = res.data.explanation;
      $("explanation-wrap").hidden = false;
    }
    $("answer-panel").hidden = false;
    setGradeDisabled(false);
    setStatus($("study-status"), "Respuesta disponible. Califica tu recuerdo del 0 al 5.");
    if (document.activeElement === $("card-heading")) $("card-back").focus();
  }

  async function gradeCard(quality) {
    if (!state.card || state.grading || $("answer-panel").hidden) return;
    const { card_id: cardId, deck_id: deckId } = state.card;
    $("card-heading").focus();
    state.selectionRevision++;
    state.grading = true;
    state.loadSeq++;
    setStudyNavDisabled(true);
    setGradeDisabled(true);
    $("reveal-btn").disabled = true;
    setStatus($("study-status"), "Guardando calificación…");
    const res = await post(`/study/${encodeURIComponent(cardId)}/grade`, { quality });
    state.grading = false;
    setStudyNavDisabled(false);
    if (!res.ok || !res.data) {
      setGradeDisabled(false);
      $("reveal-btn").disabled = !$("answer-panel").hidden;
      return setStatus($("study-status"), res.error, "error");
    }
    const nextFocus = document.activeElement === $("card-heading") ? $("load-next-btn") : null;
    nextFocus?.focus();
    $("deck-id").value = String(deckId);
    await loadNextCard(`Calificación: ${quality}. Próximo repaso: ${res.data.due_date} (intervalo: ${res.data.interval_days} d).`, nextFocus);
  }

  async function loadTemplates() {
    const seq = ++state.templateSeq;
    state.activeTemplateId = null;
    $("template-detail").hidden = true;
    $("create-from-template-btn").disabled = true;
    setStatus($("templates-status"), "Cargando plantillas…");
    const res = await api("/templates");
    if (seq !== state.templateSeq) return;
    if (!res.ok || !Array.isArray(res.data)) return setStatus($("templates-status"), res.error, "error");
    state.templatesLoaded = true;
    const select = $("template-select");
    select.replaceChildren(new Option("Elige una plantilla", ""));
    for (const t of res.data) select.append(new Option(`[${t.category}] ${t.title}`, t.id));
    setStatus($("templates-status"), `Plantillas disponibles: ${res.data.length}.`);
  }

  async function viewTemplate(id) {
    const seq = ++state.templateSeq;
    state.activeTemplateId = null;
    $("template-detail").hidden = true;
    $("create-from-template-btn").disabled = true;
    if (!id) return setStatus($("templates-status"), "");
    setStatus($("templates-status"), "Cargando plantilla…");
    const res = await api(`/templates/${encodeURIComponent(id)}`);
    if (seq !== state.templateSeq) return;
    if (!res.ok || !res.data) return setStatus($("templates-status"), res.error, "error");
    const t = res.data;
    state.activeTemplateId = t.id;
    $("tpl-title").textContent = t.title;
    $("tpl-meta").textContent = `(${t.category} · ${t.kind})`;
    $("tpl-front").textContent = t.front;
    $("tpl-back").textContent = t.back;
    const fups = Array.isArray(t.follow_up_questions) ? t.follow_up_questions : [];
    fillList($("tpl-followups"), fups);
    $("tpl-followups-wrap").hidden = fups.length === 0;
    $("tpl-explanation").textContent = t.explanation || "";
    $("tpl-explanation").hidden = !t.explanation;
    $("template-detail").hidden = false;
    syncTemplateAction();
  }

  function syncTemplateAction() {
    if (!state.activeTemplateId) return;
    const deckId = deckIdValue();
    const write = state.templateWrites.get(JSON.stringify([state.activeTemplateId, deckId]));
    $("create-from-template-btn").disabled = !deckId || Boolean(write);
    setStatus($("templates-status"), write?.message || "", write?.kind || "");
  }

  async function createCardFromTemplate() {
    const templateId = state.activeTemplateId;
    const deckId = deckIdValue();
    const key = JSON.stringify([templateId, deckId]);
    if (!templateId || !deckId || state.templateWrites.has(key)) return;
    state.templateWrites.set(key, { message: "Creando tarjeta…" });
    syncTemplateAction();
    const res = await post(`/templates/${encodeURIComponent(templateId)}/cards`, { deck_id: deckId });
    if (res.ok && res.data?.id) {
      state.templateWrites.set(key, { message: `Tarjeta #${res.data.id} creada en el mazo #${deckId}.`, kind: "ok" });
    } else if (res.status >= 400 && res.status < 500) {
      state.templateWrites.delete(key);
    } else {
      state.templateWrites.set(key, { message: `No se pudo confirmar la creación. Comprueba las tarjetas del mazo #${deckId}.`, kind: "error" });
    }
    if (state.activeTemplateId === templateId && deckIdValue() === deckId) {
      syncTemplateAction();
      if (!state.templateWrites.has(key)) setStatus($("templates-status"), res.error, "error");
    }
  }

  async function loadErrors(note = "") {
    const seq = ++state.errorSeq;
    const filter = $("error-filter").value;
    setStatus($("errors-status"), "Cargando errores…");
    const res = await api(filter ? `/errors?status=${encodeURIComponent(filter)}` : "/errors");
    if (seq !== state.errorSeq) return;
    if (!res.ok || !Array.isArray(res.data)) return setStatus($("errors-status"), res.error, "error");
    state.errorsLoaded = true;
    renderErrors(res.data);
    setStatus($("errors-status"), note || `Errores encontrados: ${res.data.length}.`, note ? "ok" : "");
  }

  function syncErrorRow(errId, focusOverride = false) {
    const row = [...$("errors-list").children].find((node) => node.dataset.errorId === String(errId));
    const rowStatus = state.errorRowStatus.get(errId);
    if (!row) {
      if (rowStatus) setStatus($("errors-status"), `Error #${errId}: ${rowStatus.text}`, rowStatus.kind);
      return;
    }
    const pending = state.pendingErrors.has(errId);
    const override = row.querySelector("input");
    for (const ctrl of row.querySelectorAll("input, button")) ctrl.disabled = pending;
    row.querySelector(".approve-error").disabled = pending || !deckIdValue();
    row.querySelector(".deck-destination").textContent = destinationLabel(state.pendingErrors.get(errId) || deckIdValue());
    const statusEl = row.querySelector("p.status");
    if (statusEl) setStatus(statusEl, rowStatus ? rowStatus.text : "", rowStatus ? rowStatus.kind : "");
    if (focusOverride && override && !pending) override.focus();
  }

  function renderErrors(items) {
    $("errors-list").replaceChildren(...items.map((err) => {
      const wrap = el(
        "div", { className: "item" },
        el("div", { className: "meta", textContent: `#${err.id} · ${({ draft: "Borrador", approved: "Aprobado", discarded: "Descartado" })[err.status] ?? err.status}${err.card_id ? ` · tarjeta #${err.card_id}` : ""}` }),
        el("div", {}, el("strong", { textContent: "Original: " }), err.attempted),
        el("div", {}, el("strong", { textContent: "Corrección: " }), err.corrected),
        el("div", {}, el("strong", { textContent: "Motivo: " }), err.rationale),
      );
      if (err.status !== "draft") {
        state.errorOverrides.delete(err.id);
        state.errorRowStatus.delete(err.id);
        return wrap;
      }
      wrap.dataset.errorId = String(err.id);
      const pending = state.pendingErrors.has(err.id);
      const savedStatus = state.errorRowStatus.get(err.id);
      const itemStatus = el("p", { className: "status", role: "status" });
      if (savedStatus) setStatus(itemStatus, savedStatus.text, savedStatus.kind);
      const override = el("input", {
        type: "text",
        value: state.errorOverrides.get(err.id) ?? "",
        disabled: pending,
        placeholder: "Anverso alternativo (obligatorio si supera los 5000 caracteres)",
        ariaLabel: `Anverso alternativo para el error ${err.id}`,
      });
      override.style.flex = "1";
      override.addEventListener("input", () => state.errorOverrides.set(err.id, override.value));
      const approveBtn = el("button", { type: "button", className: "approve-error", textContent: "Aprobar y crear tarjeta", disabled: pending });
      const discardBtn = el("button", { type: "button", textContent: "Descartar", disabled: pending });
      const runDraftAction = async (path, body, onOk) => {
        if (state.pendingErrors.has(err.id)) return;
        state.pendingErrors.set(err.id, body?.deck_id || null);
        state.errorRowStatus.delete(err.id);
        syncErrorRow(err.id);
        const res = await post(path, body);
        state.pendingErrors.delete(err.id);
        if (!res.ok) {
          const hint = res.status === 422 ? " Prueba con un anverso más corto." : "";
          state.errorRowStatus.set(err.id, { text: `${res.error}${hint}`, kind: "error" });
          syncErrorRow(err.id, res.status === 422);
          return;
        }
        state.errorOverrides.delete(err.id);
        state.errorRowStatus.delete(err.id);
        await loadErrors(onOk(res.data));
      };
      approveBtn.addEventListener("click", () => {
        const deckId = deckIdValue();
        if (deckId === null) {
          state.errorRowStatus.set(err.id, { text: "Selecciona un mazo o escribe un ID válido arriba.", kind: "error" });
          return syncErrorRow(err.id);
        }
        const customFront = (state.errorOverrides.get(err.id) ?? override.value).trim();
        const payload = customFront ? { deck_id: deckId, front: customFront } : { deck_id: deckId };
        runDraftAction(`/errors/${encodeURIComponent(err.id)}/approve`, payload, (d) => `Error #${err.id} aprobado. Tarjeta #${d.card.id} creada en el mazo #${deckId}.`);
      });
      discardBtn.addEventListener("click", () =>
        runDraftAction(`/errors/${encodeURIComponent(err.id)}/discard`, undefined, () => `Error #${err.id} descartado.`),
      );
      const destination = el("p", { className: "meta deck-destination", id: `error-destination-${err.id}` });
      approveBtn.setAttribute("aria-describedby", destination.id);
      wrap.append(destination, el("div", { className: "row" }, override, approveBtn, discardBtn), itemStatus);
      return wrap;
    }));
    syncDestinations();
  }

  async function createError(event) {
    event.preventDefault();
    const form = $("error-form");
    const controls = [...form.querySelectorAll("textarea, button[type=submit]")];
    if (controls.some((c) => c.disabled)) return;
    const payload = {
      attempted: $("err-attempted").value,
      corrected: $("err-corrected").value,
      rationale: $("err-rationale").value,
    };
    controls.forEach((c) => { c.disabled = true; });
    const res = await post("/errors", payload);
    if (!res.ok) {
      controls.forEach((c) => { c.disabled = false; });
      return setStatus($("errors-status"), res.error, "error");
    }
    form.reset();
    controls.forEach((c) => { c.disabled = false; });
    await loadErrors(`Borrador #${res.data.id} guardado.`);
  }

  $("deck-select").addEventListener("change", (e) => {
    if (state.grading) return;
    state.selectionRevision++;
    $("deck-id").value = e.target.value;
    renderDeckList();
    syncDestinations();
    if (e.target.value) loadNextCard();
    else { state.loadSeq++; state.card = null; clearAnswer(); $("study-card").hidden = true; setStatus($("study-status"), ""); }
  });
  $("deck-id").addEventListener("input", () => {
    syncDestinations();
    state.loadSeq++;
    state.selectionRevision++;
    state.card = null;
    clearAnswer();
    $("study-card").hidden = true;
    renderDeckPicker();
    setStatus($("study-status"), "");
  });
  $("deck-id").addEventListener("keydown", (e) => { if (e.key === "Enter" && !state.grading) loadNextCard("", e.target); });
  $("load-next-btn").addEventListener("click", (e) => loadNextCard("", e.currentTarget));
  $("deck-search").addEventListener("input", () => {
    state.selectionRevision++;
    renderDeckList();
  });
  $("deck-form").addEventListener("submit", createDeck);
  $("refresh-decks-btn").addEventListener("click", () => loadDecks());
  $("reveal-btn").addEventListener("click", () => revealCard());
  $("study-card").addEventListener("keydown", (e) => {
    if (e.defaultPrevented || e.repeat || e.isComposing || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
    if (e.key.toLowerCase() === "r") {
      e.preventDefault();
      revealCard();
    } else if (/^[0-5]$/.test(e.key) && !$("answer-panel").hidden) {
      e.preventDefault();
      gradeCard(Number(e.key));
    }
  });
  $("grade-controls").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-quality]");
    if (btn && !btn.disabled) gradeCard(Number(btn.dataset.quality));
  });
  $("templates-section").addEventListener("toggle", (e) => { if (e.target.open && !state.templatesLoaded) loadTemplates(); });
  $("load-templates-btn").addEventListener("click", () => loadTemplates());
  $("template-select").addEventListener("change", (e) => viewTemplate(e.target.value));
  $("create-from-template-btn").addEventListener("click", () => createCardFromTemplate());
  $("errors-section").addEventListener("toggle", (e) => { if (e.target.open && !state.errorsLoaded) loadErrors(); });
  $("error-form").addEventListener("submit", createError);
  $("error-filter").addEventListener("change", () => loadErrors());
  $("load-errors-btn").addEventListener("click", () => loadErrors());

  loadDecks();
})();
