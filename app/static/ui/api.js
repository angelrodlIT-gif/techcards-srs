/**
 * Precision-safe API client for TechCards SRS.
 *
 * All numeric `*id` fields are parsed as strings before JSON.parse so IDs larger
 * than Number.MAX_SAFE_INTEGER never lose precision, and serialized back as raw
 * JSON integer digits in request payloads.
 */

const ID_KEY_RE = /^(?:id|.*_id)$/;
const POSITIVE_INT_RE = /^[1-9]\d*$/;
const INT_LITERAL_RE = /^-?\d+(?=[,\}\]\s]|$)/;

/**
 * Quotes raw integer values for `id` / `*_id` keys in a JSON payload without
 * altering anything inside string literals.
 */
export function quoteLargeIdFields(rawText) {
  if (!rawText || typeof rawText !== "string") return rawText;
  let out = "";
  let i = 0;
  const len = rawText.length;

  while (i < len) {
    const ch = rawText[i];
    if (ch === '"') {
      const start = i;
      i += 1;
      while (i < len) {
        if (rawText[i] === "\\") {
          i += 2;
        } else if (rawText[i] === '"') {
          i += 1;
          break;
        } else {
          i += 1;
        }
      }
      const token = rawText.slice(start, i);
      out += token;

      // Look ahead for optional whitespace and a colon (object property key).
      let j = i;
      while (j < len && /\s/.test(rawText[j])) j += 1;
      if (j < len && rawText[j] === ":") {
        let keyName = "";
        try {
          keyName = JSON.parse(token);
        } catch {
          keyName = "";
        }
        if (ID_KEY_RE.test(keyName)) {
          let k = j + 1;
          while (k < len && /\s/.test(rawText[k])) k += 1;
          const rest = rawText.slice(k);
          const match = INT_LITERAL_RE.exec(rest);
          if (match) {
            out += rawText.slice(i, k) + '"' + match[0] + '"';
            i = k + match[0].length;
            continue;
          }
        }
      }
      continue;
    }
    out += ch;
    i += 1;
  }
  return out;
}

export function parseJsonPreservingIds(rawText) {
  if (!rawText) return null;
  return JSON.parse(quoteLargeIdFields(rawText));
}

/**
 * Serializes a JS value to JSON, emitting numeric string IDs (`deck_id`,
 * `card_id`, `error_id`, `id`) as raw unquoted integer digits so big integers
 * round-trip without passing through IEEE-754 Number.
 */
export function serializeJsonWithRawIds(value, keyName = "") {
  if (value === null || value === undefined) return "null";
  if (typeof value === "string") {
    if (ID_KEY_RE.test(keyName) && POSITIVE_INT_RE.test(value)) {
      return value;
    }
    return JSON.stringify(value);
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return "[" + value.map((item) => serializeJsonWithRawIds(item, "")).join(",") + "]";
  }
  if (typeof value === "object") {
    const entries = Object.entries(value).filter(([, v]) => v !== undefined);
    return (
      "{" +
      entries
        .map(([k, v]) => `${JSON.stringify(k)}:${serializeJsonWithRawIds(v, k)}`)
        .join(",") +
      "}"
    );
  }
  return JSON.stringify(value);
}

export function isValidId(value) {
  return typeof value === "string" && POSITIVE_INT_RE.test(value.trim());
}

export function formatApiError(status, data) {
  const detail = data?.detail;
  let detailText = "";
  if (typeof detail === "string") {
    detailText = detail;
  } else if (Array.isArray(detail)) {
    detailText = detail
      .map((item) => {
        const loc = Array.isArray(item.loc)
          ? item.loc.filter((part) => part !== "body").join(".")
          : "";
        return loc ? `${loc}: ${item.msg}` : item.msg || String(item);
      })
      .join(" · ");
  }

  switch (status) {
    case 0:
      return "No se pudo conectar con la API local. Verifica que el servidor esté encendido.";
    case 403:
      return detailText || "Acción permitida solo en conexión local directa (loopback).";
    case 404:
      return detailText
        ? `No encontrado (404): ${detailText}`
        : "El recurso solicitado no existe o fue eliminado (404).";
    case 409:
      return detailText
        ? `Conflicto de estado (409): ${detailText}`
        : "Conflicto: este elemento ya cambió de estado o está duplicado (409).";
    case 422:
      return detailText
        ? `Datos inválidos (422): ${detailText}`
        : "Revisa los campos del formulario (422).";
    case 429:
      return detailText || "Límite de síntesis alcanzado (429). Revela la tarjeta para leer el texto.";
    case 503:
      return detailText || "Servicio temporalmente no disponible (503).";
    default:
      return detailText ? `Error ${status}: ${detailText}` : `Error HTTP ${status}`;
  }
}

export async function apiRequest(path, options = {}) {
  const { method = "GET", body, headers = {}, signal } = options;
  const reqHeaders = { ...headers };
  let serializedBody;
  if (body !== undefined) {
    reqHeaders["Content-Type"] = "application/json";
    serializedBody = typeof body === "string" ? body : serializeJsonWithRawIds(body);
  }

  try {
    const res = await fetch(path, {
      method,
      headers: reqHeaders,
      body: serializedBody,
      signal,
    });
    if (res.status === 204) {
      return { ok: true, status: 204, data: null, error: "" };
    }
    const raw = await res.text();
    let data = null;
    if (raw) {
      try {
        data = parseJsonPreservingIds(raw);
      } catch {
        data = { detail: raw };
      }
    }
    return {
      ok: res.ok,
      status: res.status,
      data,
      error: res.ok ? "" : formatApiError(res.status, data),
    };
  } catch (err) {
    if (err?.name === "AbortError") {
      return { ok: false, status: -1, data: null, error: "Solicitud cancelada", aborted: true };
    }
    return { ok: false, status: 0, data: null, error: formatApiError(0, null) };
  }
}

export async function fetchAllPages(basePath, { limit = 100, maxPages = 10, signal } = {}) {
  const items = [];
  let offset = 0;
  let hasMore = false;
  const sep = basePath.includes("?") ? "&" : "?";

  for (let page = 0; page < maxPages; page += 1) {
    const res = await apiRequest(`${basePath}${sep}offset=${offset}&limit=${limit}`, { signal });
    if (!res.ok) return { ok: false, status: res.status, data: items, hasMore: false, error: res.error };
    const chunk = Array.isArray(res.data) ? res.data : [];
    items.push(...chunk);
    if (chunk.length < limit) {
      hasMore = false;
      break;
    }
    offset += limit;
    hasMore = page === maxPages - 1;
  }
  return { ok: true, status: 200, data: items, hasMore, error: "" };
}

export const api = {
  health: (signal) => apiRequest("/health", { signal }),

  // Decks
  listDecks: (signal) => fetchAllPages("/decks", { limit: 100, maxPages: 10, signal }),
  createDeck: (payload) => apiRequest("/decks", { method: "POST", body: payload }),
  updateDeck: (deckId, payload) =>
    apiRequest(`/decks/${encodeURIComponent(deckId)}`, { method: "PUT", body: payload }),
  deleteDeck: (deckId) => apiRequest(`/decks/${encodeURIComponent(deckId)}`, { method: "DELETE" }),
  listDueCards: (deckId, signal) =>
    fetchAllPages(`/decks/${encodeURIComponent(deckId)}/due`, { limit: 100, maxPages: 10, signal }),

  // Cards
  listCards: (deckId, signal) => {
    const path = deckId ? `/cards?deck_id=${encodeURIComponent(deckId)}` : "/cards";
    return fetchAllPages(path, { limit: 100, maxPages: 10, signal });
  },
  createCard: (payload) => apiRequest("/cards", { method: "POST", body: payload }),
  updateCard: (cardId, payload) =>
    apiRequest(`/cards/${encodeURIComponent(cardId)}`, { method: "PUT", body: payload }),
  deleteCard: (cardId) => apiRequest(`/cards/${encodeURIComponent(cardId)}`, { method: "DELETE" }),
  generateCards: (payload) => apiRequest("/cards/generate", { method: "POST", body: payload }),

  // Study
  studyNext: (deckId, { kind = "", remediationOnly = false, signal } = {}) => {
    const params = new URLSearchParams();
    params.set("deck_id", deckId);
    if (kind) params.set("kind", kind);
    if (remediationOnly) params.set("remediation_only", "true");
    return apiRequest(`/study/next?${params.toString()}`, { signal });
  },
  studyReveal: (cardId) =>
    apiRequest(`/study/${encodeURIComponent(cardId)}/reveal`, { method: "POST" }),
  studyGrade: (cardId, quality) =>
    apiRequest(`/study/${encodeURIComponent(cardId)}/grade`, {
      method: "POST",
      body: { quality: Number(quality) },
    }),
  async studyAudio(cardId) {
    try {
      const res = await fetch(`/study/${encodeURIComponent(cardId)}/audio`, {
        method: "POST",
        headers: { "polly-opt-in": "true" },
      });
      if (!res.ok) {
        const raw = await res.text();
        let data = null;
        try {
          data = raw ? parseJsonPreservingIds(raw) : null;
        } catch {
          data = { detail: raw };
        }
        return { ok: false, status: res.status, blob: null, error: formatApiError(res.status, data) };
      }
      const blob = await res.blob();
      return { ok: true, status: 200, blob, error: "" };
    } catch {
      return { ok: false, status: 0, blob: null, error: formatApiError(0, null) };
    }
  },

  // Templates
  listTemplates: (signal) => apiRequest("/templates", { signal }),
  createCardFromTemplate: (templateId, deckId) =>
    apiRequest(`/templates/${encodeURIComponent(templateId)}/cards`, {
      method: "POST",
      body: { deck_id: deckId },
    }),

  // Sources
  listSources: (status = "", signal) => {
    const path = status ? `/sources?status=${encodeURIComponent(status)}` : "/sources";
    return fetchAllPages(path, { limit: 100, maxPages: 10, signal });
  },
  createSource: (payload) => apiRequest("/sources", { method: "POST", body: payload }),
  updateSource: (sourceId, payload) =>
    apiRequest(`/sources/${encodeURIComponent(sourceId)}`, { method: "PUT", body: payload }),
  deleteSource: (sourceId) =>
    apiRequest(`/sources/${encodeURIComponent(sourceId)}`, { method: "DELETE" }),
  approveSource: (sourceId, payload) =>
    apiRequest(`/sources/${encodeURIComponent(sourceId)}/approve`, {
      method: "POST",
      body: payload,
    }),
  discardSource: (sourceId) =>
    apiRequest(`/sources/${encodeURIComponent(sourceId)}/discard`, { method: "POST" }),

  // Errors
  listErrors: (status = "", signal) => {
    const path = status ? `/errors?status=${encodeURIComponent(status)}` : "/errors";
    return fetchAllPages(path, { limit: 100, maxPages: 10, signal });
  },
  createError: (payload) => apiRequest("/errors", { method: "POST", body: payload }),
  suggestError: (payload) => apiRequest("/errors/suggest", { method: "POST", body: payload }),
  updateError: (errorId, payload) =>
    apiRequest(`/errors/${encodeURIComponent(errorId)}`, { method: "PUT", body: payload }),
  deleteError: (errorId, deleteCard = false) =>
    apiRequest(
      `/errors/${encodeURIComponent(errorId)}${deleteCard ? "?delete_card=true" : ""}`,
      { method: "DELETE" }
    ),
  approveError: (errorId, payload) =>
    apiRequest(`/errors/${encodeURIComponent(errorId)}/approve`, {
      method: "POST",
      body: payload,
    }),
  discardError: (errorId) =>
    apiRequest(`/errors/${encodeURIComponent(errorId)}/discard`, { method: "POST" }),
  exportErrors: (status = "") => {
    const path = status ? `/errors/export?status=${encodeURIComponent(status)}` : "/errors/export";
    return apiRequest(path);
  },

  // Analytics
  learningSummary: ({ start = "", end = "", signal } = {}) => {
    const params = new URLSearchParams();
    if (start) params.set("start", start);
    if (end) params.set("end", end);
    const qs = params.toString();
    return apiRequest(qs ? `/analytics/learning?${qs}` : "/analytics/learning", { signal });
  },
};

/**
 * Runs async tasks with bounded concurrency so we never flood SQLite/uvicorn.
 */
async function mapWithConcurrency(items, concurrency, fn) {
  const results = new Array(items.length);
  let cursor = 0;

  async function worker() {
    while (cursor < items.length) {
      const idx = cursor;
      cursor += 1;
      results[idx] = await fn(items[idx], idx);
    }
  }

  const workers = Array.from({ length: Math.min(concurrency, items.length) }, () => worker());
  await Promise.all(workers);
  return results;
}

/**
 * Fetches real per-day review counts for the last 84 days (12 weeks) using
 * GET /analytics/learning?start=...&end=... without inventing any data.
 *
 * Uses adaptive narrowing:
 * - 0 reviews in window -> 1 request total.
 * - All reviews on 1 day -> 1 request total.
 * - Multi-day span -> splits active span into 7-day chunks, drills only into non-empty chunks.
 */
export async function fetchRealHeatmap(dateKeys, signal) {
  const counts = Object.fromEntries(dateKeys.map((k) => [k, 0]));
  if (dateKeys.length === 0) return { ok: true, counts, total: 0, error: "" };

  const startDate = dateKeys[0];
  const endDate = dateKeys[dateKeys.length - 1];
  const windowRes = await api.learningSummary({ start: startDate, end: endDate, signal });
  if (!windowRes.ok) {
    return { ok: false, counts, total: 0, error: windowRes.error };
  }

  const total = windowRes.data?.reviews?.recall?.denominator ?? 0;
  if (total === 0) {
    return { ok: true, counts, total: 0, error: "" };
  }

  const first = windowRes.data?.practice?.first_review_cancun_date;
  const last = windowRes.data?.practice?.last_review_cancun_date;
  if (first && last && first === last) {
    if (first in counts) counts[first] = total;
    return { ok: true, counts, total, error: "" };
  }

  // Restrict probing strictly to the active date slice inside our 84-day window.
  const firstIdx = first ? Math.max(0, dateKeys.indexOf(first)) : 0;
  const lastIdx = last ? dateKeys.indexOf(last) : dateKeys.length - 1;
  const activeDates = dateKeys.slice(firstIdx, (lastIdx >= 0 ? lastIdx : dateKeys.length - 1) + 1);

  if (activeDates.length <= 7) {
    await mapWithConcurrency(activeDates, 4, async (day) => {
      const r = await api.learningSummary({ start: day, end: day, signal });
      if (r.ok) counts[day] = r.data?.reviews?.recall?.denominator ?? 0;
    });
    return { ok: true, counts, total, error: "" };
  }

  // Group active dates into 7-day chunks first.
  const chunks = [];
  for (let i = 0; i < activeDates.length; i += 7) {
    chunks.push(activeDates.slice(i, i + 7));
  }

  const nonEmptyChunks = [];
  await mapWithConcurrency(chunks, 4, async (chunk) => {
    const r = await api.learningSummary({
      start: chunk[0],
      end: chunk[chunk.length - 1],
      signal,
    });
    if (!r.ok) return;
    const chunkTotal = r.data?.reviews?.recall?.denominator ?? 0;
    if (chunkTotal === 0) return;
    const cFirst = r.data?.practice?.first_review_cancun_date;
    const cLast = r.data?.practice?.last_review_cancun_date;
    if (cFirst && cLast && cFirst === cLast) {
      if (cFirst in counts) counts[cFirst] = chunkTotal;
    } else {
      const s = cFirst && chunk.includes(cFirst) ? chunk.indexOf(cFirst) : 0;
      const e = cLast && chunk.includes(cLast) ? chunk.indexOf(cLast) : chunk.length - 1;
      nonEmptyChunks.push(chunk.slice(s, e + 1));
    }
  });

  const daysToProbe = nonEmptyChunks.flat();
  if (daysToProbe.length > 0) {
    await mapWithConcurrency(daysToProbe, 4, async (day) => {
      const r = await api.learningSummary({ start: day, end: day, signal });
      if (r.ok) counts[day] = r.data?.reviews?.recall?.denominator ?? 0;
    });
  }

  return { ok: true, counts, total, error: "" };
}
