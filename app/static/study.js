(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const state = {
    card: null,
    loadSeq: 0,
    pendingGradeCards: new Set(),
    templatesLoaded: false,
    templateSeq: 0,
    activeTemplateId: null,
    errorsLoaded: false,
    errorSeq: 0,
    pendingErrors: new Set(),
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

  async function api(path, options = {}) {
    try {
      const headers = options.body ? { "Content-Type": "application/json" } : {};
      const res = await fetch(path, { ...options, headers: { ...headers, ...options.headers } });
      const raw = res.status === 204 ? "" : await res.text();
      let data = null;
      if (raw) {
        try { data = JSON.parse(raw); } catch { data = { detail: raw }; }
      }
      const d = data?.detail;
      const error = res.ok
        ? ""
        : typeof d === "string"
          ? d
          : Array.isArray(d) ? d.map((x) => x.msg || String(x)).join("; ") : `HTTP ${res.status}`;
      return { ok: res.ok, status: res.status, data, error };
    } catch {
      return { ok: false, status: 0, data: null, error: "Network error reaching local API." };
    }
  }

  const post = (path, body) =>
    api(path, body === undefined ? { method: "POST" } : { method: "POST", body: JSON.stringify(body) });

  const deckIdValue = () => (/^[1-9]\d*$/.test($("deck-id").value.trim()) ? Number($("deck-id").value.trim()) : null);
  const fillList = (ul, items) => ul.replaceChildren(...items.map((text) => el("li", { textContent: text })));
  const setGradeDisabled = (disabled) =>
    $("grade-controls").querySelectorAll("button[data-quality]").forEach((btn) => { btn.disabled = disabled; });

  function clearAnswer() {
    $("answer-panel").hidden = $("accepted-wrap").hidden = $("explanation-wrap").hidden = true;
    $("card-back").textContent = $("card-explanation").textContent = "";
    $("card-accepted").replaceChildren();
  }

  async function loadDecks() {
    const res = await api("/decks");
    if (!res.ok || !Array.isArray(res.data)) return setStatus($("study-status"), res.error, "error");
    const select = $("deck-select");
    const current = $("deck-id").value.trim();
    select.replaceChildren(new Option("-- Choose a deck --", ""));
    for (const d of res.data) select.append(new Option(`#${d.id} — ${d.name}`, String(d.id)));
    if (current && res.data.some((d) => String(d.id) === current)) {
      select.value = current;
    } else if (!current && res.data.length > 0) {
      select.value = $("deck-id").value = String(res.data[0].id);
      await loadNextCard();
    } else if (res.data.length === 0) {
      setStatus($("study-status"), "No decks found yet. Create a deck via /docs, then refresh.");
    }
  }

  async function loadNextCard(note = "") {
    const status = $("study-status");
    const deckId = deckIdValue();
    if (deckId === null) {
      state.loadSeq++;
      state.card = null;
      clearAnswer();
      $("study-card").hidden = true;
      return setStatus(status, "Enter or select a valid positive Deck ID.", "error");
    }
    const select = $("deck-select");
    select.value = [...select.options].some((o) => o.value === String(deckId)) ? String(deckId) : "";
    const seq = ++state.loadSeq;
    state.card = null;
    clearAnswer();
    $("study-card").hidden = true;
    setStatus(status, note ? `${note} Loading next card...` : "Loading next card...");

    const res = await api(`/study/next?deck_id=${encodeURIComponent(deckId)}`);
    if (seq !== state.loadSeq) return;
    if (res.status === 204) {
      return setStatus(status, note ? `${note} No due cards left.` : "No due cards left in this deck.", "ok");
    }
    if (res.status === 404) return setStatus(status, `Deck #${deckId} not found.`, "error");
    if (!res.ok || !res.data) return setStatus(status, res.error, "error");

    const c = res.data;
    state.card = c;
    $("card-meta").textContent = [
      `Card #${c.card_id}`, c.kind, c.source_label ? `source: ${c.source_label}` : null,
      `due: ${c.due_date}`, `reps: ${c.repetitions}`, `interval: ${c.interval_days}d`, `ease: ${c.ease_factor}`,
    ].filter(Boolean).join(" · ");
    $("card-front").textContent = c.front;
    $("reveal-btn").disabled = false;
    setGradeDisabled(state.pendingGradeCards.has(c.card_id));
    $("study-card").hidden = false;
    setStatus(status, note, note ? "ok" : "");
  }

  async function revealCard() {
    if (!state.card) return;
    const cardId = state.card.card_id;
    const seq = state.loadSeq;
    $("reveal-btn").disabled = true;
    const res = await post(`/study/${encodeURIComponent(cardId)}/reveal`);
    if (seq !== state.loadSeq || !state.card || state.card.card_id !== cardId) return;
    if (!res.ok || !res.data) {
      $("reveal-btn").disabled = false;
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
  }

  async function gradeCard(quality) {
    if (!state.card || state.pendingGradeCards.has(state.card.card_id)) return;
    const cardId = state.card.card_id;
    const seq = state.loadSeq;
    state.pendingGradeCards.add(cardId);
    setGradeDisabled(true);
    const res = await post(`/study/${encodeURIComponent(cardId)}/grade`, { quality });
    state.pendingGradeCards.delete(cardId);
    if (seq !== state.loadSeq || !state.card || state.card.card_id !== cardId) {
      if (state.card && state.card.card_id === cardId) {
        if (!res.ok || !res.data) setGradeDisabled(false);
        else setStatus($("study-status"), `Card #${cardId} already graded (${quality}) — click Load next card.`, "ok");
      }
      return;
    }
    if (!res.ok || !res.data) {
      setGradeDisabled(false);
      return setStatus($("study-status"), res.error, "error");
    }
    await loadNextCard(`Graded ${quality} — next due ${res.data.due_date} (${res.data.interval_days}d).`);
  }

  async function loadTemplates() {
    const seq = ++state.templateSeq;
    state.activeTemplateId = null;
    $("template-detail").hidden = true;
    $("create-from-template-btn").disabled = true;
    const res = await api("/templates");
    if (seq !== state.templateSeq) return;
    if (!res.ok || !Array.isArray(res.data)) return setStatus($("templates-status"), res.error, "error");
    state.templatesLoaded = true;
    const select = $("template-select");
    select.replaceChildren(new Option("-- Choose a template --", ""));
    for (const t of res.data) select.append(new Option(`[${t.category}] ${t.title}`, t.id));
    setStatus($("templates-status"), `${res.data.length} templates available.`);
  }

  async function viewTemplate(id) {
    const seq = ++state.templateSeq;
    state.activeTemplateId = null;
    $("template-detail").hidden = true;
    $("create-from-template-btn").disabled = true;
    if (!id) return setStatus($("templates-status"), "");
    setStatus($("templates-status"), "Loading template...");
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
    $("create-from-template-btn").disabled = false;
    $("template-detail").hidden = false;
    setStatus($("templates-status"), "");
  }

  async function createCardFromTemplate() {
    const btn = $("create-from-template-btn");
    const templateId = state.activeTemplateId;
    const seq = state.templateSeq;
    const deckId = deckIdValue();
    if (!templateId) return;
    if (deckId === null) return setStatus($("templates-status"), "Select a valid Deck ID above first.", "error");
    btn.disabled = true;
    const res = await post(`/templates/${encodeURIComponent(templateId)}/cards`, { deck_id: deckId });
    if (seq === state.templateSeq && state.activeTemplateId === templateId) btn.disabled = false;
    if (!res.ok || !res.data) return setStatus($("templates-status"), res.error, "error");
    setStatus($("templates-status"), `Created card #${res.data.id} in deck #${deckId}.`, "ok");
  }

  async function loadErrors(note = "") {
    const seq = ++state.errorSeq;
    const filter = $("error-filter").value;
    const res = await api(filter ? `/errors?status=${encodeURIComponent(filter)}` : "/errors");
    if (seq !== state.errorSeq) return;
    if (!res.ok || !Array.isArray(res.data)) return setStatus($("errors-status"), res.error, "error");
    state.errorsLoaded = true;
    renderErrors(res.data);
    setStatus($("errors-status"), note || `${res.data.length} error entr${res.data.length === 1 ? "y" : "ies"}.`, note ? "ok" : "");
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
    const statusEl = row.querySelector("p.status");
    if (statusEl) setStatus(statusEl, rowStatus ? rowStatus.text : "", rowStatus ? rowStatus.kind : "");
    if (focusOverride && override && !pending) override.focus();
  }

  function renderErrors(items) {
    $("errors-list").replaceChildren(...items.map((err) => {
      const wrap = el(
        "div", { className: "item" },
        el("div", { className: "meta", textContent: `#${err.id} · ${err.status}${err.card_id ? ` · card #${err.card_id}` : ""}` }),
        el("div", {}, el("strong", { textContent: "Attempted: " }), err.attempted),
        el("div", {}, el("strong", { textContent: "Corrected: " }), err.corrected),
        el("div", {}, el("strong", { textContent: "Rationale: " }), err.rationale),
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
        placeholder: "Optional front override (required if >5000 chars)",
        ariaLabel: `Front override for error ${err.id}`,
      });
      override.style.flex = "1";
      override.addEventListener("input", () => state.errorOverrides.set(err.id, override.value));
      const approveBtn = el("button", { type: "button", textContent: "Approve into deck", disabled: pending });
      const discardBtn = el("button", { type: "button", textContent: "Discard", disabled: pending });
      const runDraftAction = async (path, body, onOk) => {
        if (state.pendingErrors.has(err.id)) return;
        state.pendingErrors.add(err.id);
        state.errorRowStatus.delete(err.id);
        syncErrorRow(err.id);
        const res = await post(path, body);
        state.pendingErrors.delete(err.id);
        if (!res.ok) {
          const hint = res.status === 422 ? " Enter a shorter front override and retry." : "";
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
          state.errorRowStatus.set(err.id, { text: "Select a valid Deck ID above first.", kind: "error" });
          return syncErrorRow(err.id);
        }
        const customFront = (state.errorOverrides.get(err.id) ?? override.value).trim();
        const payload = customFront ? { deck_id: deckId, front: customFront } : { deck_id: deckId };
        runDraftAction(`/errors/${encodeURIComponent(err.id)}/approve`, payload, (d) => `Approved error #${err.id} into card #${d.card.id}.`);
      });
      discardBtn.addEventListener("click", () =>
        runDraftAction(`/errors/${encodeURIComponent(err.id)}/discard`, undefined, () => `Discarded error #${err.id}.`),
      );
      wrap.append(el("div", { className: "row" }, override, approveBtn, discardBtn), itemStatus);
      return wrap;
    }));
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
    await loadErrors(`Logged draft error #${res.data.id}.`);
  }

  $("deck-select").addEventListener("change", (e) => {
    $("deck-id").value = e.target.value;
    if (e.target.value) loadNextCard();
    else { state.loadSeq++; state.card = null; clearAnswer(); $("study-card").hidden = true; setStatus($("study-status"), ""); }
  });
  $("deck-id").addEventListener("keydown", (e) => { if (e.key === "Enter") loadNextCard(); });
  $("load-next-btn").addEventListener("click", () => loadNextCard());
  $("refresh-decks-btn").addEventListener("click", () => loadDecks());
  $("reveal-btn").addEventListener("click", () => revealCard());
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
