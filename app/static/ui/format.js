/**
 * Formatting, locale, Spanish pluralization, Cancun date helpers, and safe text utilities.
 */

export const CANCUN_TZ = "America/Cancun";

const intFormatter = new Intl.NumberFormat("es-MX");
const compactFormatter = new Intl.NumberFormat("es-MX", {
  notation: "compact",
  maximumFractionDigits: 1,
});
const decimalFormatter = new Intl.NumberFormat("es-MX", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const shortDateFormatter = new Intl.DateTimeFormat("es-MX", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});
const dateTimeFormatter = new Intl.DateTimeFormat("es-MX", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: CANCUN_TZ,
});

export function formatInt(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return intFormatter.format(Number(value));
}

export function formatCompactCount(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  const num = Number(value);
  if (Math.abs(num) >= 10000) return compactFormatter.format(num);
  return intFormatter.format(num);
}

export function formatEase(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return decimalFormatter.format(Number(value));
}

export function formatPercent(numerator, denominator) {
  if (!denominator || denominator <= 0) return "—";
  const pct = Math.max(0, Math.min(100, Math.round((numerator / denominator) * 100)));
  return `${pct}%`;
}

export function clampPercent(numerator, denominator) {
  if (!denominator || denominator <= 0) return 0;
  return Math.max(0, Math.min(100, (numerator / denominator) * 100));
}

export function pluralize(count, singular, plural) {
  const n = Number(count);
  return `${formatInt(n)} ${n === 1 ? singular : plural}`;
}

export function formatDurationSeconds(seconds) {
  if (seconds === null || seconds === undefined || Number.isNaN(Number(seconds))) return "—";
  const total = Math.max(0, Math.round(Number(seconds)));
  if (total < 60) return `${total} s`;
  const mins = Math.floor(total / 60);
  if (mins < 60) return `${mins} min`;
  const hours = Math.floor(mins / 60);
  const remMins = mins % 60;
  if (hours < 24) return remMins > 0 ? `${hours} h ${remMins} min` : `${hours} h`;
  const days = Math.floor(hours / 24);
  const remHours = hours % 24;
  return remHours > 0 ? `${days} d ${remHours} h` : `${days} d`;
}

export function formatIsoDate(isoDate) {
  if (!isoDate || typeof isoDate !== "string") return "—";
  const parts = isoDate.split("-");
  if (parts.length !== 3) return isoDate;
  const dt = new Date(Date.UTC(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2])));
  if (Number.isNaN(dt.getTime())) return isoDate;
  return shortDateFormatter.format(dt);
}

export function formatTimestamp(isoTimestamp) {
  if (!isoTimestamp) return "—";
  const dt = new Date(isoTimestamp);
  if (Number.isNaN(dt.getTime())) return "—";
  return dateTimeFormatter.format(dt);
}

/**
 * Returns YYYY-MM-DD for a Date in America/Cancun (matching backend learning.py).
 */
export function toCancunDateKey(date = new Date()) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: CANCUN_TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date);
  const map = Object.fromEntries(parts.map((p) => [p.type, p.value]));
  return `${map.year}-${map.month}-${map.day}`;
}

/**
 * Adds `deltaDays` to a YYYY-MM-DD key using pure UTC calendar math.
 */
export function addDaysToKey(dateKey, deltaDays) {
  const [y, m, d] = dateKey.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d + deltaDays));
  const yy = dt.getUTCFullYear();
  const mm = String(dt.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(dt.getUTCDate()).padStart(2, "0");
  return `${yy}-${mm}-${dd}`;
}

/**
 * Returns the last `days` YYYY-MM-DD keys ending on today (America/Cancun),
 * aligned cleanly to 12 full weeks (84 days).
 */
export function getLastNDaysKeys(days = 84, anchorKey = toCancunDateKey()) {
  const keys = [];
  for (let i = days - 1; i >= 0; i -= 1) {
    keys.push(addDaysToKey(anchorKey, -i));
  }
  return keys;
}

/**
 * Computes current consecutive-day streak ending today (or yesterday if today is 0).
 */
export function computeStreak(dateKeys, countsByDate) {
  if (!dateKeys.length) return { current: 0, activeDays: 0 };
  let activeDays = 0;
  for (const key of dateKeys) {
    if ((countsByDate[key] || 0) > 0) activeDays += 1;
  }

  let idx = dateKeys.length - 1;
  if ((countsByDate[dateKeys[idx]] || 0) === 0) {
    // Allow streak to continue if yesterday had reviews and today hasn't started yet.
    idx -= 1;
  }
  let current = 0;
  while (idx >= 0 && (countsByDate[dateKeys[idx]] || 0) > 0) {
    current += 1;
    idx -= 1;
  }
  return { current, activeDays };
}

export function getGreeting() {
  const hour = Number(
    new Intl.DateTimeFormat("en-US", {
      hour: "numeric",
      hour12: false,
      timeZone: CANCUN_TZ,
    }).format(new Date())
  );
  if (hour >= 5 && hour < 12) return "Buenos días";
  if (hour >= 12 && hour < 19) return "Buenas tardes";
  return "Buenas noches";
}

export const KIND_META = {
  vocabulary: { label: "Vocabulario", short: "Vocab" },
  interview_phrase: { label: "Frase de entrevista", short: "Entrevista" },
  behavioral: { label: "STAR / Conductual", short: "STAR" },
  sentence: { label: "Oración", short: "Oración" },
  cloze: { label: "Completar (Cloze)", short: "Cloze" },
  es_en: { label: "ES → EN", short: "ES→EN" },
  listening: { label: "Listening (Audio)", short: "Audio" },
};

export function kindLabel(kind) {
  return KIND_META[kind]?.label || kind || "Tarjeta";
}

export const GRADE_META = [
  { quality: 0, label: "En blanco", hint: "No la recordé", tone: "danger" },
  { quality: 1, label: "Incorrecta", hint: "Error grave", tone: "danger" },
  { quality: 2, label: "Casi", hint: "Faltó precisión", tone: "danger" },
  { quality: 3, label: "Difícil", hint: "Con esfuerzo", tone: "warning" },
  { quality: 4, label: "Bien", hint: "Clara y fluida", tone: "success" },
  { quality: 5, label: "Dominada", hint: "Natural y exacta", tone: "success" },
];

/**
 * Computes honest deck mastery from card SRS state.
 * A card counts as mastered when repetitions >= 2 and interval_days >= 6.
 */
export function computeDeckMastery(cards) {
  const total = cards.length;
  if (total === 0) return { mastered: 0, learning: 0, total: 0, pct: 0 };
  let mastered = 0;
  let learning = 0;
  for (const c of cards) {
    if ((c.repetitions || 0) >= 2 && (c.interval_days || 0) >= 6) {
      mastered += 1;
    } else if ((c.repetitions || 0) >= 1) {
      learning += 1;
    }
  }
  return { mastered, learning, total, pct: Math.round((mastered / total) * 100) };
}

/**
 * Truncates long unbreakable strings (URLs, IDs) in the middle so differing
 * endings stay readable.
 */
export function truncateMiddle(str, maxLen = 46) {
  if (!str || str.length <= maxLen) return str || "";
  const half = Math.floor((maxLen - 1) / 2);
  return `${str.slice(0, half)}…${str.slice(str.length - half)}`;
}
