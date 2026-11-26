/**
 * API client for TechCards SRS.
 *
 * Guarantees:
 * - Big-integer IDs (> Number.MAX_SAFE_INTEGER) are preserved as decimal strings on parse
 *   and serialized back as raw unquoted integer digits in request JSON bodies.
 * - Never performs arithmetic on IDs.
 * - Handles HTTP 404, 409, 422, 429, 503 and network errors with clear Spanish messages.
 * - In Demo / Worst-case / Empty modes, serves read-only synthetic fixtures and NEVER writes to the API.
 */

import { buildDemoDataset, buildEmptyDataset, buildWorstCaseDataset } from "./demo-data.js";

const ID_DIGITS_RE = /^[1-9]\d*$/;
const STRING_OR_INT_PROP_RE = /("(?:[^"\\]|\\.)*")(?:(\s*:\s*)([1-9]\d*)(?=\s*[,}]))?/g;

export function isValidId(value) {
  return typeof value === "string" && ID_DIGITS_RE.test(value);
}

/**
 * Parse JSON while converting integer values of `id` and `*_id` properties to strings
 * before JSON.parse so IDs above Number.MAX_SAFE_INTEGER never lose precision.
 * Whole strings are matched first so ID-like text inside card content is untouched.
 */
export function parseApiJson(raw) {
  const rewritten = raw.replace(STRING_OR_INT_PROP_RE, (token, quoted, colon, digits) => {
    if (!digits) return token;
    const key = JSON.parse(quoted);
    return key === "id" || key.endsWith("_id") ? `${quoted}${colon}"${digits}"` : token;
  });
  return JSON.parse(rewritten, (key, value) => {
    if (typeof value === "number" && (key === "id" || key.endsWith("_id"))) {
      throw new RangeError("La API devolvió un identificador numérico con formato inesperado.");
    }
    return value;
  });
}

/**
 * Serialize payload to JSON, emitting validated integer ID strings for `id` / `*_id`
 * keys as raw JSON digits without converting through IEEE-754 Number.
 */
export function serializeApiJson(value, key = "") {
  if (value === null) return "null";
  if (typeof value === "string") {
    if ((key === "id" || key.endsWith("_id")) && ID_DIGITS_RE.test(value)) {
      return value;
    }
    return JSON.stringify(value);
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => (item === undefined ? "null" : serializeApiJson(item))).join(",")}]`;
  }
  if (typeof value === "object") {
    const entries = [];
    for (const [k, v] of Object.entries(value)) {
      if (v === undefined) continue;
      entries.push(`${JSON.stringify(k)}:${serializeApiJson(v, k)}`);
    }
    return `{${entries.join(",")}}`;
  }
  return "null";
}

function formatHttpError(status, data) {
  const detail = data?.detail;
  let serverMsg = "";
  if (typeof detail === "string") {
    serverMsg = detail;
  } else if (Array.isArray(detail)) {
    serverMsg = detail
      .map((item) => {
        const loc = Array.isArray(item.loc) ? item.loc.filter((p) => p !== "body").join(".") : "";
        const msg = item.msg || String(item);
        return loc ? `${loc}: ${msg}` : msg;
      })
      .join(" · ");
  }

  if (status === 404) {
    return serverMsg ? `No encontrado (404): ${serverMsg}` : "El recurso solicitado no existe (404).";
  }
  if (status === 409) {
    return serverMsg
      ? `Conflicto de estado o duplicado (409): ${serverMsg}`
      : "Conflicto: la acción ya no aplica al estado actual (409).";
  }
  if (status === 422) {
    return serverMsg
      ? `Revisa los datos enviados (422): ${serverMsg}`
      : "Los datos no cumplen la validación del servidor (422).";
  }
  if (status === 429) {
    return serverMsg || "Se alcanzó el límite de síntesis de audio (429). Revela la tarjeta para leer el texto.";
  }
  if (status === 503) {
    return serverMsg || "Audio no disponible en este entorno (503). Revela la tarjeta para estudiar en texto.";
  }
  return serverMsg ? `Error HTTP ${status}: ${serverMsg}` : `Error inesperado del servidor (HTTP ${status}).`;
}

// ============================================================================
// Data mode manager (live | demo | worst | empty)
// ============================================================================

let currentDataMode = "live";
let syntheticCache = null;

export function getDataMode() {
  return currentDataMode;
}

export function isReadOnlyMode() {
  return currentDataMode !== "live";
}

export function setDataMode(mode) {
  const normalized = ["live", "demo", "worst", "empty"].includes(mode) ? mode : "live";
  currentDataMode = normalized;
  if (normalized === "demo") syntheticCache = buildDemoDataset();
  else if (normalized === "worst") syntheticCache = buildWorstCaseDataset();
  else if (normalized === "empty") syntheticCache = buildEmptyDataset();
  else syntheticCache = null;
}

function getSynthetic() {
  if (!syntheticCache) {
    setDataMode(currentDataMode === "live" ? "demo" : currentDataMode);
  }
  return syntheticCache;
}

function readOnlyBlockedResponse() {
  return {
    ok: false,
    status: 403,
    data: null,
    error: "Modo de vista previa activo: las escrituras están bloqueadas para no modificar tu API real. Cambia a «API real» para guardar cambios.",
  };
}

// ============================================================================
// Low-level fetch wrapper
// ============================================================================

async function request(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  if (isReadOnlyMode() && method !== "GET") {
    return readOnlyBlockedResponse();
  }

  try {
    const headers = { ...(options.headers || {}) };
    let body = options.body;
    if (body !== undefined && typeof body !== "string") {
      headers["Content-Type"] = "application/json";
      body = serializeApiJson(body);
    }
    const res = await fetch(path, { ...options, method, headers, body });
    if (res.status === 204) {
      return { ok: true, status: 204, data: null, error: "" };
    }
    const raw = await res.text();
    let data = null;
    if (raw) {
      try {
        data = parseApiJson(raw);
      } catch (err) {
        if (res.ok) {
          return {
            ok: false,
            status: res.status,
            data: null,
            error: err instanceof RangeError ? err.message : "La API devolvió JSON no válido.",
          };
        }
        data = { detail: raw };
      }
    }
    if (!res.ok) {
      return { ok: false, status: res.status, data, error: formatHttpError(res.status, data) };
    }
    return { ok: true, status: res.status, data, error: "" };
  } catch {
    return {
      ok: false,
      status: 0,
      data: null,
      error: "No se pudo conectar con la API local. Comprueba que el servidor esté activo e inténtalo de nuevo.",
    };
  }
}

async function fetchAllPages(buildPath, { limit = 100, maxPages = 10 } = {}) {
  const items = [];
  let truncated = false;
  for (let page = 0; page < maxPages; page += 1) {
    const offset = page * limit;
    const res = await request(buildPath(offset, limit));
    if (!res.ok) return res;
    const batch = Array.isArray(res.data) ? res.data : [];
    items.push(...batch);
    if (batch.length < limit) {
      return { ok: true, status: 200, data: items, truncated: false, error: "" };
    }
    if (page === maxPages - 1) {
      truncated = true;
    }
  }
  return { ok: true, status: 200, data: items, truncated, error: "" };
}

// ============================================================================
// High-level Domain Endpoints (100% real API routes)
// ============================================================================

export const api = {
  // Decks
  async listDecks() {
    if (isReadOnlyMode()) {
      return { ok: true, status: 200, data: [...getSynthetic().decks], truncated: false, error: "" };
    }
    return fetchAllPages((offset, limit) => `/decks?offset=${offset}&limit=${limit}`);
  },

  async createDeck({ name, description = "" }) {
    return request("/decks", { method: "POST", body: { name, description } });
  },

  async updateDeck(deckId, { name, description = "" }) {
    if (!isValidId(deckId)) return { ok: false, status: 422, data: null, error: "ID de mazo no válido." };
    return request(`/decks/${deckId}`, { method: "PUT", body: { name, description } });
  },

  async deleteDeck(deckId) {
    if (!isValidId(deckId)) return { ok: false, status: 422, data: null, error: "ID de mazo no válido." };
    return request(`/decks/${deckId}`, { method: "DELETE" });
  },

  async listDueCards(deckId) {
    if (isReadOnlyMode()) {
      const ds = getSynthetic();
      const deck = ds.decks.find((d) => d.id === deckId);
      if (!deck) return { ok: false, status: 404, data: null, error: "No encontrado (404): Deck not found" };
      const today = new Date().toISOString().slice(0, 10);
      const due = ds.cards.filter((c) => c.deck_id === deckId && c.due_date <= today);
      return {
        ok: true,
        status: 200,
        data: due,
        syntheticCount: deck._syntheticDue,
        truncated: false,
        error: "",
      };
    }
    if (!isValidId(deckId)) return { ok: false, status: 422, data: null, error: "ID de mazo no válido." };
    return fetchAllPages((offset, limit) => `/decks/${deckId}/due?offset=${offset}&limit=${limit}`);
  },

  // Cards
  async listCards(deckId = null, { offset = 0, limit = 100 } = {}) {
    if (isReadOnlyMode()) {
      const ds = getSynthetic();
      const filtered = deckId ? ds.cards.filter((c) => c.deck_id === deckId) : ds.cards;
      const deck = deckId ? ds.decks.find((d) => d.id === deckId) : null;
      return {
        ok: true,
        status: 200,
        data: filtered.slice(offset, offset + limit),
        syntheticCount: deck?._syntheticTotal,
        error: "",
      };
    }
    const qs = new URLSearchParams({ offset: String(offset), limit: String(limit) });
    if (deckId) {
      if (!isValidId(deckId)) return { ok: false, status: 422, data: null, error: "ID de mazo no válido." };
      qs.set("deck_id", deckId);
    }
    return request(`/cards?${qs.toString()}`);
  },

  async listAllCardsForDeck(deckId) {
    if (isReadOnlyMode()) {
      const ds = getSynthetic();
      const deck = ds.decks.find((d) => d.id === deckId);
      const filtered = ds.cards.filter((c) => c.deck_id === deckId);
      return {
        ok: true,
        status: 200,
        data: filtered,
        syntheticCount: deck?._syntheticTotal,
        truncated: false,
        error: "",
      };
    }
    if (!isValidId(deckId)) return { ok: false, status: 422, data: null, error: "ID de mazo no válido." };
    return fetchAllPages((offset, limit) => `/cards?deck_id=${deckId}&offset=${offset}&limit=${limit}`);
  },

  async createCard(payload) {
    return request("/cards", { method: "POST", body: payload });
  },

  async deleteCard(cardId) {
    if (!isValidId(cardId)) return { ok: false, status: 422, data: null, error: "ID de tarjeta no válido." };
    return request(`/cards/${cardId}`, { method: "DELETE" });
  },

  async generateCards({ deck_id, text, max_cards }) {
    return request("/cards/generate", { method: "POST", body: { deck_id, text, max_cards } });
  },

  // Study (Recall-first)
  async studyNext({ deckId, kind = "", remediationOnly = false }) {
    if (isReadOnlyMode()) {
      const ds = getSynthetic();
      const today = new Date().toISOString().slice(0, 10);
      const candidates = ds.cards.filter((c) => {
        if (c.deck_id !== deckId) return false;
        if (c.due_date > today) return false;
        if (kind && c.kind !== kind) return false;
        if (remediationOnly && !c.error_id) return false;
        return true;
      });
      if (!candidates.length) {
        return { ok: true, status: 204, data: null, error: "" };
      }
      const card = candidates[0];
      return {
        ok: true,
        status: 200,
        data: {
          card_id: card.id,
          deck_id: card.deck_id,
          front: card.front,
          kind: card.kind,
          source_label: card.source_label,
          error_id: card.error_id,
          due_date: card.due_date,
          repetitions: card.repetitions,
          interval_days: card.interval_days,
          ease_factor: card.ease_factor,
        },
        error: "",
      };
    }
    if (!isValidId(deckId)) return { ok: false, status: 422, data: null, error: "Selecciona un mazo válido." };
    const qs = new URLSearchParams({ deck_id: deckId });
    if (kind) qs.set("kind", kind);
    if (remediationOnly) qs.set("remediation_only", "true");
    return request(`/study/next?${qs.toString()}`);
  },

  async studyReveal(cardId) {
    if (isReadOnlyMode()) {
      const card = getSynthetic().cards.find((c) => c.id === cardId);
      if (!card) return { ok: false, status: 404, data: null, error: "Tarjeta no encontrada en modo demo." };
      return {
        ok: true,
        status: 200,
        data: {
          card_id: card.id,
          deck_id: card.deck_id,
          back: card.back,
          accepted_answers: card.accepted_answers || [],
          explanation: card.explanation || null,
        },
        error: "",
      };
    }
    if (!isValidId(cardId)) return { ok: false, status: 422, data: null, error: "ID de tarjeta no válido." };
    return request(`/study/${cardId}/reveal`, { method: "POST" });
  },

  async studyGrade(cardId, quality) {
    if (isReadOnlyMode()) {
      return readOnlyBlockedResponse();
    }
    if (!isValidId(cardId)) return { ok: false, status: 422, data: null, error: "ID de tarjeta no válido." };
    return request(`/study/${cardId}/grade`, { method: "POST", body: { quality } });
  },

  async studyAudio(cardId) {
    if (isReadOnlyMode()) {
      return {
        ok: false,
        status: 503,
        data: null,
        error: "Audio Polly desactivado en vista previa demo. Cambia a «API real» para probar audio local.",
      };
    }
    if (!isValidId(cardId)) return { ok: false, status: 422, data: null, error: "ID de tarjeta no válido." };
    try {
      const res = await fetch(`/study/${cardId}/audio`, {
        method: "POST",
        headers: { "polly-opt-in": "true" },
      });
      if (!res.ok) {
        let data = null;
        try {
          data = JSON.parse(await res.text());
        } catch {
          data = null;
        }
        return { ok: false, status: res.status, data: null, error: formatHttpError(res.status, data) };
      }
      const blob = await res.blob();
      return { ok: true, status: 200, data: blob, error: "" };
    } catch {
      return { ok: false, status: 0, data: null, error: "No se pudo solicitar el audio a la API local." };
    }
  },

  // Templates
  async listTemplates() {
    if (isReadOnlyMode()) {
      return { ok: true, status: 200, data: [...getSynthetic().templates], error: "" };
    }
    return request("/templates");
  },

  async createCardFromTemplate(templateId, deckId) {
    return request(`/templates/${encodeURIComponent(templateId)}/cards`, {
      method: "POST",
      body: { deck_id: deckId },
    });
  },

  // Sources
  async listSources(status = "") {
    if (isReadOnlyMode()) {
      const all = getSynthetic().sources;
      const filtered = status ? all.filter((s) => s.status === status) : all;
      return { ok: true, status: 200, data: filtered, truncated: false, error: "" };
    }
    return fetchAllPages((offset, limit) => {
      const qs = new URLSearchParams({ offset: String(offset), limit: String(limit) });
      if (status) qs.set("status", status);
      return `/sources?${qs.toString()}`;
    });
  },

  async createSource(payload) {
    return request("/sources", { method: "POST", body: payload });
  },

  async updateSource(sourceId, payload) {
    if (!isValidId(sourceId)) return { ok: false, status: 422, data: null, error: "ID de fuente no válido." };
    return request(`/sources/${sourceId}`, { method: "PUT", body: payload });
  },

  async discardSource(sourceId) {
    if (!isValidId(sourceId)) return { ok: false, status: 422, data: null, error: "ID de fuente no válido." };
    return request(`/sources/${sourceId}/discard`, { method: "POST" });
  },

  async approveSource(sourceId, payload) {
    if (!isValidId(sourceId)) return { ok: false, status: 422, data: null, error: "ID de fuente no válido." };
    return request(`/sources/${sourceId}/approve`, { method: "POST", body: payload });
  },

  async deleteSource(sourceId) {
    if (!isValidId(sourceId)) return { ok: false, status: 422, data: null, error: "ID de fuente no válido." };
    return request(`/sources/${sourceId}`, { method: "DELETE" });
  },

  // Errors (Remediation loop)
  async listErrors(status = "") {
    if (isReadOnlyMode()) {
      const all = getSynthetic().errors;
      const filtered = status ? all.filter((e) => e.status === status) : all;
      return { ok: true, status: 200, data: filtered, truncated: false, error: "" };
    }
    return fetchAllPages((offset, limit) => {
      const qs = new URLSearchParams({ offset: String(offset), limit: String(limit) });
      if (status) qs.set("status", status);
      return `/errors?${qs.toString()}`;
    });
  },

  async createError(payload) {
    return request("/errors", { method: "POST", body: payload });
  },

  async suggestError(payload) {
    return request("/errors/suggest", { method: "POST", body: payload });
  },

  async approveError(errorId, payload) {
    if (!isValidId(errorId)) return { ok: false, status: 422, data: null, error: "ID de error no válido." };
    return request(`/errors/${errorId}/approve`, { method: "POST", body: payload });
  },

  async discardError(errorId) {
    if (!isValidId(errorId)) return { ok: false, status: 422, data: null, error: "ID de error no válido." };
    return request(`/errors/${errorId}/discard`, { method: "POST" });
  },

  async deleteError(errorId, deleteCard = false) {
    if (!isValidId(errorId)) return { ok: false, status: 422, data: null, error: "ID de error no válido." };
    const qs = deleteCard ? "?delete_card=true" : "";
    return request(`/errors/${errorId}${qs}`, { method: "DELETE" });
  },

  async exportErrors(status = "") {
    if (isReadOnlyMode()) {
      const items = status
        ? getSynthetic().errors.filter((e) => e.status === status)
        : getSynthetic().errors;
      return {
        ok: true,
        status: 200,
        data: { exported_at: new Date().toISOString(), count: items.length, items },
        error: "",
      };
    }
    const qs = new URLSearchParams({ limit: "1000" });
    if (status) qs.set("status", status);
    return request(`/errors/export?${qs.toString()}`);
  },

  // Analytics
  async getLearningAnalytics({ start = "", end = "" } = {}) {
    if (isReadOnlyMode()) {
      return {
        ok: true,
        status: 200,
        data: { ...getSynthetic().analytics, start: start || null, end: end || null },
        error: "",
      };
    }
    const qs = new URLSearchParams();
    if (start) qs.set("start", start);
    if (end) qs.set("end", end);
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return request(`/analytics/learning${suffix}`);
  },
};
