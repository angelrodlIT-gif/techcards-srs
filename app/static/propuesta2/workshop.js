import { api, all, esc } from './api.js';

const STAR_PREFIX = '[STAR remediation]';
const MAX_ACCEPTED_ANSWERS = 20;
const MAX_LISTENING_CHARS = 1000;
const POSITIVE_INT_RE = /^[1-9]\d*$/;

const KIND_OPTIONS = [
  ['vocabulary', 'Vocabulario'],
  ['interview_phrase', 'Frase de entrevista'],
  ['behavioral', 'Conductual (STAR)'],
  ['sentence', 'Oración'],
  ['cloze', 'Hueco (____)'],
  ['es_en', 'Español → Inglés'],
  ['listening', 'Comprensión auditiva'],
];

const KIND_LABELS = Object.fromEntries(KIND_OPTIONS);

const TEMPLATE_CATEGORY_LABELS = {
  star: 'STAR',
  networking: 'Redes',
};

const SOURCE_STATUS_LABELS = {
  draft: 'Borrador',
  approved: 'Aprobada',
  discarded: 'Descartada',
};

const ERROR_STATUS_LABELS = {
  draft: 'Borrador',
  approved: 'Aprobado',
  discarded: 'Descartado',
};

function idValue(value) {
  return String(value ?? '').trim();
}

function safe(value) {
  return esc(String(value ?? ''));
}

function lines(value) {
  return safe(value).replace(/\r?\n/g, '<br>');
}

function isHttpUrl(value) {
  return /^https?:\/\//i.test(String(value ?? '').trim());
}

function requirePositiveId(raw, label) {
  const value = idValue(raw);
  if (!POSITIVE_INT_RE.test(value)) {
    throw new Error(`Identificador de ${label} inválido.`);
  }
  return value;
}

function requireText(raw, label) {
  const value = String(raw ?? '').trim();
  if (!value) {
    throw new Error(`El campo «${label}» es obligatorio.`);
  }
  return value;
}

function optionalText(raw) {
  const value = String(raw ?? '').trim();
  return value || null;
}

function parseAcceptedAnswers(raw) {
  const items = String(raw ?? '')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  const unique = [...new Set(items)];
  if (unique.length > MAX_ACCEPTED_ANSWERS) {
    throw new Error(`Solo se permiten hasta ${MAX_ACCEPTED_ANSWERS} respuestas aceptadas.`);
  }
  return unique;
}

function validateCardFormat(kind, front, back) {
  if (kind === 'cloze' && front) {
    const blanks = front.match(/_{4,}/g) || [];
    if (blanks.length !== 1 || blanks[0] !== '____') {
      throw new Error(
        'Las tarjetas de hueco (cloze) deben incluir exactamente un espacio «____» en el anverso.',
      );
    }
  }
  if (kind === 'listening' && back && back.length > MAX_LISTENING_CHARS) {
    throw new Error(
      `La transcripción de comprensión auditiva no puede superar los ${MAX_LISTENING_CHARS} caracteres.`,
    );
  }
}

function deckSelect(decks, name = 'deck_id') {
  const options = decks
    .map((deck) => `<option value="${safe(idValue(deck.id))}">${safe(deck.name)}</option>`)
    .join('');
  return `<label>Mazo<select name="${safe(name)}" required>${options}</select></label>`;
}

function kindSelect(selected = 'vocabulary', name = 'kind') {
  const options = KIND_OPTIONS.map(
    ([value, label]) =>
      `<option value="${safe(value)}"${value === selected ? ' selected' : ''}>${safe(label)}</option>`,
  ).join('');
  return `<label>Formato<select name="${safe(name)}">${options}</select></label>`;
}

function renderCrear(decks) {
  const hasDecks = decks.length > 0;

  const deckPanel = `
    <section class="panel">
      <p class="kicker">Biblioteca</p>
      <h2>Nuevo mazo</h2>
      <form data-action="create-deck">
        <label>Nombre del mazo
          <input type="text" name="name" required maxlength="120" placeholder="Ej. Entrevista backend">
        </label>
        <label>Descripción (opcional)
          <textarea name="description" rows="2" maxlength="5000" placeholder="Tema, rol o alcance del mazo"></textarea>
        </label>
        <button type="submit" class="primary">Crear mazo</button>
      </form>
    </section>
  `;

  const generatePanel = `
    <section class="panel">
      <p class="kicker">Generador</p>
      <h2>Generar tarjetas desde texto</h2>
      ${
        hasDecks
          ? `<form data-action="generate-cards">
              ${deckSelect(decks)}
              <label>Texto fuente
                <textarea name="text" rows="5" required minlength="10" maxlength="20000" placeholder="Pega apuntes, documentación o conceptos técnicos (mínimo 10 caracteres)..."></textarea>
              </label>
              <label>Máximo de tarjetas (1–20)
                <input type="number" name="max_cards" min="1" max="20" step="1" value="6" required>
              </label>
              <button type="submit" class="primary">Generar tarjetas</button>
            </form>`
          : '<p class="empty">Crea primero un mazo para poder generar tarjetas desde texto.</p>'
      }
    </section>
  `;

  return `<div class="grid">${deckPanel}${generatePanel}</div>`;
}

async function renderPlantillas(decks) {
  const templates = (await api('/templates')) || [];
  if (!templates.length) {
    return '<section class="panel"><p class="kicker">Plantillas</p><p class="empty">No hay plantillas disponibles en el catálogo.</p></section>';
  }

  const hasDecks = decks.length > 0;
  const notice = hasDecks
    ? ''
    : '<section class="panel"><p class="kicker">Plantillas</p><p class="empty">Crea un mazo en «Crear» para poder añadir tarjetas desde esta galería.</p></section>';

  const cards = templates
    .map((tpl) => {
      const tplId = idValue(tpl.id);
      const category = TEMPLATE_CATEGORY_LABELS[tpl.category] || tpl.category || 'Plantilla';
      const kind = KIND_LABELS[tpl.kind] || tpl.kind || '';
      const followUps =
        Array.isArray(tpl.follow_up_questions) && tpl.follow_up_questions.length
          ? `<ul>${tpl.follow_up_questions.map((q) => `<li>${safe(q)}</li>`).join('')}</ul>`
          : '';
      const explanation = tpl.explanation ? `<p><small>${lines(tpl.explanation)}</small></p>` : '';
      const actionForm = hasDecks
        ? `<form data-action="template-card">
            <input type="hidden" name="template_id" value="${safe(tplId)}">
            ${deckSelect(decks)}
            <button type="submit" class="primary">Añadir al mazo</button>
          </form>`
        : '';

      return `
        <article class="panel template">
          <p class="kicker">${safe(category)}${kind ? ` · ${safe(kind)}` : ''}</p>
          <h3>${safe(tpl.title)}</h3>
          <p>${lines(tpl.front)}</p>
          <details>
            <summary>Ver guía de respuesta</summary>
            <p>${lines(tpl.back)}</p>
            ${followUps}
            ${explanation}
          </details>
          ${actionForm}
        </article>
      `;
    })
    .join('');

  return `${notice}<div class="grid">${cards}</div>`;
}

async function renderFuentes(decks) {
  const sources = (await all('/sources')) || [];
  const drafts = sources.filter((src) => src.status === 'draft');
  const history = sources.filter((src) => src.status !== 'draft');
  const hasDecks = decks.length > 0;

  const createPanel = `
    <section class="panel">
      <p class="kicker">Curación de fuentes</p>
      <h2>Guardar un fragmento</h2>
      <form data-action="create-source">
        <label>Etiqueta o título
          <input type="text" name="label" required maxlength="255" placeholder="Ej. RFC 9110 — Métodos HTTP">
        </label>
        <label>URL (opcional)
          <input type="url" name="url" maxlength="2048" placeholder="https://...">
        </label>
        <label>Extracto (opcional)
          <textarea name="excerpt" rows="3" maxlength="20000" placeholder="Fragmento clave para convertir en tarjeta"></textarea>
        </label>
        <button type="submit" class="primary">Guardar borrador</button>
      </form>
    </section>
  `;

  const draftsSection = drafts.length
    ? `<div class="grid">${drafts
        .map((src) => {
          const srcId = idValue(src.id);
          const urlHtml =
            src.url && isHttpUrl(src.url)
              ? `<p><a href="${safe(src.url)}" target="_blank" rel="noopener noreferrer">${safe(src.url)}</a></p>`
              : '';
          const excerptHtml = src.excerpt ? `<p>${lines(src.excerpt)}</p>` : '';
          const approveForm = hasDecks
            ? `<form data-action="approve-source">
                <input type="hidden" name="source_id" value="${safe(srcId)}">
                ${deckSelect(decks)}
                ${kindSelect('vocabulary')}
                <label>Anverso (pregunta)
                  <textarea name="front" rows="2" required maxlength="5000" placeholder="Pregunta derivada de esta fuente"></textarea>
                </label>
                <label>Reverso (respuesta)
                  <textarea name="back" rows="2" required maxlength="5000" placeholder="Respuesta esperada"></textarea>
                </label>
                <details>
                  <summary>Opciones avanzadas</summary>
                  <label>Respuestas aceptadas (una por línea)
                    <textarea name="accepted_answers" rows="2"></textarea>
                  </label>
                  <label>Explicación (opcional)
                    <textarea name="explanation" rows="2" maxlength="5000"></textarea>
                  </label>
                </details>
                <button type="submit" class="primary">Aprobar y crear tarjeta</button>
              </form>`
            : '<p class="empty">Crea un mazo en «Crear» para aprobar esta fuente como tarjeta.</p>';

          return `
            <article class="panel">
              <p class="kicker">Fuente #${safe(srcId)} · ${safe(SOURCE_STATUS_LABELS.draft)}</p>
              <h3>${safe(src.label)}</h3>
              ${urlHtml}
              ${excerptHtml}
              ${approveForm}
              <form data-action="discard-source">
                <input type="hidden" name="source_id" value="${safe(srcId)}">
                <button type="submit">Descartar fuente</button>
              </form>
            </article>
          `;
        })
        .join('')}</div>`
    : '<section class="panel"><p class="kicker">Borradores</p><p class="empty">No hay fuentes en borrador pendientes de revisión.</p></section>';

  const historySection = history.length
    ? `<section class="panel">
        <p class="kicker">Historial (${history.length})</p>
        <ul>${history
          .map((src) => {
            const srcId = idValue(src.id);
            const statusLabel = SOURCE_STATUS_LABELS[src.status] || src.status;
            const urlPart =
              src.url && isHttpUrl(src.url)
                ? ` — <a href="${safe(src.url)}" target="_blank" rel="noopener noreferrer">${safe(src.url)}</a>`
                : '';
            return `<li><strong>#${safe(srcId)} · ${safe(statusLabel)}:</strong> ${safe(src.label)}${urlPart}</li>`;
          })
          .join('')}</ul>
      </section>`
    : '';

  return `<details class="composer"><summary>＋ Nueva fuente</summary>${createPanel}</details>${draftsSection}${historySection}`;
}

async function renderErrores(decks) {
  const errors = (await all('/errors')) || [];
  const drafts = errors.filter((err) => err.status === 'draft');
  const history = errors.filter((err) => err.status !== 'draft');
  const hasDecks = decks.length > 0;

  const suggestPanel = `
    <section class="panel">
      <p class="kicker">Remediación de entrevista</p>
      <h2>Sugerir corrección desde tu respuesta</h2>
      <form data-action="suggest-error">
        <label>Categoría
          <select name="category">
            <option value="technical">Técnico</option>
            <option value="star">STAR (conductual)</option>
          </select>
        </label>
        <label>Pregunta de entrevista (opcional)
          <textarea name="prompt" rows="2" maxlength="5000" placeholder="Ej. Explain how DNS resolves a domain"></textarea>
        </label>
        <label>Tu respuesta
          <textarea name="answer" rows="4" required maxlength="4991" placeholder="Escribe la respuesta que diste o ensayaste..."></textarea>
        </label>
        <details>
          <summary>Corrección y motivo manuales (opcional)</summary>
          <label>Corrección propuesta
            <textarea name="corrected" rows="2" maxlength="5000" placeholder="Déjalo vacío para generar una sugerencia local"></textarea>
          </label>
          <label>Motivo o notas
            <textarea name="rationale" rows="2" maxlength="5000" placeholder="Déjalo vacío para notas automáticas"></textarea>
          </label>
        </details>
        <label>
          <input type="checkbox" name="consent" value="true" required>
          Consiento explícitamente guardar este texto de entrevista como borrador local para revisarlo antes de crear una tarjeta.
        </label>
        <button type="submit" class="primary">Sugerir borrador</button>
      </form>
    </section>
  `;

  const draftsSection = drafts.length
    ? `<div class="grid">${drafts
        .map((err) => {
          const errId = idValue(err.id);
          const defaultKind = String(err.rationale ?? '').startsWith(STAR_PREFIX)
            ? 'behavioral'
            : 'interview_phrase';
          const defaultFront = `Correct: ${String(err.attempted ?? '')}`;

          const approveForm = hasDecks
            ? `<form data-action="approve-error">
                <input type="hidden" name="error_id" value="${safe(errId)}">
                ${deckSelect(decks)}
                ${kindSelect(defaultKind)}
                <details>
                  <summary>Editar tarjeta antes de aprobar</summary>
                  <label>Anverso
                    <textarea name="front" rows="2" maxlength="5000">${safe(defaultFront)}</textarea>
                  </label>
                  <label>Reverso
                    <textarea name="back" rows="2" maxlength="5000">${safe(err.corrected)}</textarea>
                  </label>
                  <label>Respuestas aceptadas (una por línea)
                    <textarea name="accepted_answers" rows="2"></textarea>
                  </label>
                  <label>Explicación
                    <textarea name="explanation" rows="2" maxlength="5000">${safe(err.rationale)}</textarea>
                  </label>
                </details>
                <button type="submit" class="primary">Aprobar y crear tarjeta</button>
              </form>`
            : '<p class="empty">Crea un mazo en «Crear» para aprobar este error como tarjeta.</p>';

          return `
            <article class="panel">
              <p class="kicker">Error #${safe(errId)} · ${safe(ERROR_STATUS_LABELS.draft)}</p>
              <p><strong>Intento:</strong> ${lines(err.attempted)}</p>
              <p><strong>Corrección sugerida:</strong> ${lines(err.corrected)}</p>
              <p><small>${lines(err.rationale)}</small></p>
              ${approveForm}
              <form data-action="discard-error">
                <input type="hidden" name="error_id" value="${safe(errId)}">
                <button type="submit">Descartar borrador</button>
              </form>
            </article>
          `;
        })
        .join('')}</div>`
    : '<section class="panel"><p class="kicker">Borradores</p><p class="empty">No hay errores en borrador pendientes de revisión.</p></section>';

  const historySection = history.length
    ? `<section class="panel">
        <p class="kicker">Historial (${history.length})</p>
        <ul>${history
          .map((err) => {
            const errId = idValue(err.id);
            const statusLabel = ERROR_STATUS_LABELS[err.status] || err.status;
            const cardInfo =
              err.card_id != null && idValue(err.card_id)
                ? ` (tarjeta #${safe(idValue(err.card_id))})`
                : '';
            return `<li><strong>#${safe(errId)} · ${safe(statusLabel)}${cardInfo}:</strong> ${safe(err.corrected)}</li>`;
          })
          .join('')}</ul>
      </section>`
    : '';

  return `<details class="composer"><summary>＋ Registrar un error</summary>${suggestPanel}</details>${draftsSection}${historySection}`;
}

export async function workshop(view, decks) {
  const deckList = Array.isArray(decks) ? decks : [];
  switch (view) {
    case 'crear':
      return renderCrear(deckList);
    case 'plantillas':
      return renderPlantillas(deckList);
    case 'fuentes':
      return renderFuentes(deckList);
    case 'errores':
      return renderErrores(deckList);
    default:
      return '<section class="panel"><p class="empty">Vista del taller no disponible.</p></section>';
  }
}

export async function submitWorkshop(form) {
  const action = form?.dataset?.action || '';
  const fd = new FormData(form);

  switch (action) {
    case 'create-deck': {
      const name = requireText(fd.get('name'), 'Nombre del mazo');
      const description = String(fd.get('description') ?? '').trim();
      const deck = await api('/decks', { name, description });
      const deckId = idValue(deck?.id);
      return deckId
        ? `Mazo «${deck?.name || name}» (#${deckId}) creado.`
        : `Mazo «${deck?.name || name}» creado.`;
    }

    case 'generate-cards': {
      const deckId = requirePositiveId(fd.get('deck_id'), 'mazo');
      const text = requireText(fd.get('text'), 'Texto fuente');
      if (text.length < 10) {
        throw new Error('El texto fuente debe tener al menos 10 caracteres.');
      }
      const maxCardsRaw = String(fd.get('max_cards') ?? '6').trim();
      const maxCards = /^\d+$/.test(maxCardsRaw) ? Number(maxCardsRaw) : NaN;
      if (!Number.isInteger(maxCards) || maxCards < 1 || maxCards > 20) {
        throw new Error('El máximo de tarjetas debe ser un número entre 1 y 20.');
      }
      const cards = await api('/cards/generate', {
        deck_id: deckId,
        text,
        max_cards: maxCards,
      });
      const count = Array.isArray(cards) ? cards.length : 0;
      return count === 1
        ? 'Se generó 1 tarjeta nueva en el mazo.'
        : `Se generaron ${count} tarjetas nuevas en el mazo.`;
    }

    case 'template-card': {
      const templateId = idValue(fd.get('template_id'));
      if (!templateId) {
        throw new Error('Falta el identificador de la plantilla.');
      }
      const deckId = requirePositiveId(fd.get('deck_id'), 'mazo');
      const card = await api(`/templates/${encodeURIComponent(templateId)}/cards`, {
        deck_id: deckId,
      });
      const cardId = idValue(card?.id);
      return cardId
        ? `Plantilla añadida como tarjeta #${cardId}.`
        : 'Plantilla añadida al mazo.';
    }

    case 'create-source': {
      const label = requireText(fd.get('label'), 'Etiqueta o título');
      const url = optionalText(fd.get('url'));
      const excerpt = optionalText(fd.get('excerpt'));
      const payload = { label };
      if (url) payload.url = url;
      if (excerpt) payload.excerpt = excerpt;
      const source = await api('/sources', payload);
      const sourceId = idValue(source?.id);
      return sourceId
        ? `Fuente #${sourceId} guardada como borrador.`
        : 'Fuente guardada como borrador.';
    }

    case 'approve-source': {
      const sourceId = requirePositiveId(fd.get('source_id'), 'fuente');
      const deckId = requirePositiveId(fd.get('deck_id'), 'mazo');
      const kind = String(fd.get('kind') ?? 'vocabulary').trim() || 'vocabulary';
      const front = requireText(fd.get('front'), 'Anverso');
      const back = requireText(fd.get('back'), 'Reverso');
      validateCardFormat(kind, front, back);
      const explanation = optionalText(fd.get('explanation'));
      const acceptedAnswers = parseAcceptedAnswers(fd.get('accepted_answers'));
      const payload = { deck_id: deckId, front, back, kind };
      if (acceptedAnswers.length) payload.accepted_answers = acceptedAnswers;
      if (explanation) payload.explanation = explanation;
      const result = await api(`/sources/${encodeURIComponent(sourceId)}/approve`, payload);
      const cardId = idValue(result?.card?.id);
      return cardId
        ? `Fuente #${sourceId} aprobada y convertida en la tarjeta #${cardId}.`
        : `Fuente #${sourceId} aprobada.`;
    }

    case 'discard-source': {
      const sourceId = requirePositiveId(fd.get('source_id'), 'fuente');
      await api(`/sources/${encodeURIComponent(sourceId)}/discard`, {});
      return `Fuente #${sourceId} descartada.`;
    }

    case 'suggest-error': {
      const answer = requireText(fd.get('answer'), 'Tu respuesta');
      const category = String(fd.get('category') ?? 'technical').trim() || 'technical';
      const consentInput = form.querySelector?.('input[name="consent"]');
      const hasConsent = consentInput ? consentInput.checked : fd.get('consent') === 'true';
      if (!hasConsent) {
        throw new Error(
          'Debes marcar el consentimiento explícito para guardar este borrador de entrevista.',
        );
      }
      const prompt = optionalText(fd.get('prompt'));
      const corrected = optionalText(fd.get('corrected'));
      const rationale = optionalText(fd.get('rationale'));
      const payload = { answer, category, consent: true };
      if (prompt) payload.prompt = prompt;
      if (corrected) payload.corrected = corrected;
      if (rationale) payload.rationale = rationale;
      const result = await api('/errors/suggest', payload);
      const errorId = idValue(result?.error?.id);
      return errorId
        ? `Borrador de error #${errorId} generado con sugerencia de remediación.`
        : 'Borrador de error generado con sugerencia de remediación.';
    }

    case 'approve-error': {
      const errorId = requirePositiveId(fd.get('error_id'), 'error');
      const deckId = requirePositiveId(fd.get('deck_id'), 'mazo');
      const kind = String(fd.get('kind') ?? 'interview_phrase').trim() || 'interview_phrase';
      const front = optionalText(fd.get('front'));
      const back = optionalText(fd.get('back'));
      validateCardFormat(kind, front, back);
      const explanation = optionalText(fd.get('explanation'));
      const acceptedAnswers = parseAcceptedAnswers(fd.get('accepted_answers'));
      const payload = { deck_id: deckId, kind };
      if (front) payload.front = front;
      if (back) payload.back = back;
      if (acceptedAnswers.length) payload.accepted_answers = acceptedAnswers;
      if (explanation) payload.explanation = explanation;
      const result = await api(`/errors/${encodeURIComponent(errorId)}/approve`, payload);
      const cardId = idValue(result?.card?.id);
      return cardId
        ? `Error #${errorId} aprobado y convertido en la tarjeta #${cardId}.`
        : `Error #${errorId} aprobado.`;
    }

    case 'discard-error': {
      const errorId = requirePositiveId(fd.get('error_id'), 'error');
      await api(`/errors/${encodeURIComponent(errorId)}/discard`, {});
      return `Borrador de error #${errorId} descartado.`;
    }

    default:
      throw new Error('Acción de taller no reconocida.');
  }
}
