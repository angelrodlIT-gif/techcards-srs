// Tokenize complete JSON strings so quoted user content is never rewritten.
export function decode(source) {
  const safe = source.replace(/"(?:\\.|[^"\\])*"(?:\s*:\s*-?\d+(?=\s*[,}]))?/g, token => {
    const field = /^"(id|[a-z_]+_id)"(\s*:\s*)(-?\d+)$/.exec(token);
    return field ? `"${field[1]}"${field[2]}"${field[3]}"` : token;
  });
  return JSON.parse(safe);
}

export function encode(payload) {
  return '{' + Object.entries(payload).filter(([, value]) => value !== undefined).map(([key, value]) => {
    if (key.endsWith('_id') || key === 'id') {
      if (typeof value !== 'string' || !/^[1-9]\d*$/.test(value)) throw Error('Elige un identificador válido.');
      return JSON.stringify(key) + ':' + value;
    }
    return JSON.stringify(key) + ':' + JSON.stringify(value);
  }).join(',') + '}';
}

export async function api(path, payload) {
  const options = payload === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: encode(payload)
  };
  let response, source;
  try {
    response = await fetch(path, options);
    source = await response.text();
  } catch {
    throw Error('Se interrumpió la conexión. Actualiza la vista para comprobar el estado antes de volver a enviar.');
  }
  if (!response.ok) {
    const messages = {404:'El recurso ya no está disponible.', 409:'El registro ya cambió de estado o la URL ya existe.', 422:'Revisa los campos y sus límites.'};
    let fields = [];
    try {
      const detail = decode(source).detail;
      if (Array.isArray(detail)) fields = detail.map(item => item.loc.at(-1));
    } catch { /* A server error may have an empty response. */ }
    throw Error(`Error ${response.status}. ${messages[response.status] || 'El servidor no pudo completar la operación.'} ${fields.join(', ')}`.trim());
  }
  return source ? decode(source) : null;
}

export async function all(path, project = item => item) {
  const rows = [];
  for (let offset = 0; ; offset += 100) {
    const page = await api(path + (path.includes('?') ? '&' : '?') + 'limit=100&offset=' + offset);
    rows.push(...page.map(project));
    if (page.length < 100) return rows;
  }
}

export const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({
  '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
})[c]);
