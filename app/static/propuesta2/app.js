import {api, all, esc} from './api.js';
const loadWorkshop = () => import('./workshop.js');

const main = document.querySelector('main');
const notice = document.querySelector('#notice');
const views = {
  inicio:['⌂','Inicio','Centro de estudio'], analitica:['▥','Analítica','Tu aprendizaje'],
  crear:['⊕','Crear contenido','Taller de creación'], plantillas:['▦','Plantillas','Galería de plantillas'],
  fuentes:['▤','Fuentes','Archivo de fuentes'], errores:['◎','Errores','Registro de errores']
};
const menu = document.querySelector('#menu');
const link = key => `<a href="#${key}"><span aria-hidden="true">${views[key][0]}</span>${views[key][1]}</a>`;
menu.innerHTML = '<small>Observatorio</small>' + ['inicio','analitica'].map(link).join('') +
  '<small>Biblioteca</small>' + ['crear','plantillas','fuentes','errores'].map(link).join('');
document.querySelector('#date').textContent = new Intl.DateTimeFormat('es-MX',{weekday:'short',day:'numeric',month:'short'}).format(new Date());
let version = 0, session, busy = false, noticeTimer;
const fmt = n => n.toLocaleString('es-MX');
const path = () => location.hash.slice(1) || 'inicio';
const title = text => `<h1>${esc(text)}</h1>`;
const stat = (label, value, description) => `<article class="metric"><span>${label}</span><strong>${value}</strong><small>${description}</small></article>`;
const studyLink = (deck, label) => `<a class="primary" href="#estudio/${deck.id}">${label} <b aria-hidden="true">↗</b></a>`;
const empty = (heading, copy) => `<div class="empty"><span aria-hidden="true">✧</span><h3>${heading}</h3><p>${copy}</p></div>`;
function flash(message, error = false) {
  clearTimeout(noticeTimer);
  notice.classList.toggle('error', error);
  notice.textContent = message;
  if (message && !error && !message.endsWith('…')) noticeTimer = setTimeout(() => flash(''), 5500);
}

async function dashboard(decks) {
  const metrics = await api('/analytics/learning');
  const rows = [];
  for (const deck of decks) {
    const due = await all('/decks/' + deck.id + '/due', () => 1);
    rows.push({...deck, count:due.length});
  }
  const count = rows.reduce((sum, row) => sum + row.count, 0);
  const next = rows.find(row => row.count);
  const {recall} = metrics.reviews;
  const rate = recall.denominator ? Math.round(100 * recall.numerator / recall.denominator) + '%' : '—';
  return title('Centro de estudio') + `<section class="hero"><img src="./luna.svg" alt=""><div class="hero-copy"><span class="kicker"><i></i> Sesión de hoy</span>
    <h2>${count ? 'En órbita' : 'Cielo despejado'}<em>.</em></h2>
    <p>${count ? `Tienes <strong>${fmt(count)}</strong> ${count === 1 ? 'tarjeta pendiente' : 'tarjetas pendientes'} de repaso.` : decks.length ? 'Estás al día con tus repasos.' : 'Crea tu primer mazo para empezar a estudiar.'}</p>
    ${next ? studyLink(next,'Empezar repaso') : '<a class="primary" href="#crear">'+(decks.length ? 'Añadir tarjetas' : 'Crear un mazo')+' <b>＋</b></a>'}</div></section>
    <section aria-label="Resumen de actividad" class="stats">${stat('Por repasar',fmt(count),'Tarjetas pendientes') + stat('Recuerdo',rate,'Notas de 3 a 5') + stat('Sesiones',fmt(metrics.practice.sessions),'Histórico de práctica')}</section>
    <div class="section-head"><h2>Mis mazos</h2><a href="#crear">＋ Crear mazo</a></div>
    <div class="decks">${rows.map((row,i) => `<article class="deck"><div class="cover tone${i%3}" aria-hidden="true"><span>✧</span></div><div class="deck-name"><h3>${esc(row.name)}</h3><p>${esc(row.description) || 'Mazo de estudio'}</p></div>
    ${row.count ? `<a class="due" href="#estudio/${row.id}" aria-label="Estudiar ${esc(row.name)}, ${row.count} pendientes">${fmt(row.count)} ${row.count === 1 ? 'pendiente' : 'pendientes'} ↗</a>` : '<span class="done">Al día ✓</span>'}</article>`).join('') || empty('Tu biblioteca empieza aquí','Los mazos que crees aparecerán con su próxima cola de repaso.')}</div>`;
}

async function analytics() {
  const {reviews,practice,error_correction:errors} = await api('/analytics/learning');
  const outcome = (name, value, description) => {
    const {numerator:n,denominator:d} = value;
    return `<article class="panel"><span class="kicker">${name}</span><h2>${d ? Math.round(100*n/d)+'%' : 'Sin muestra'}</h2><p>${description}</p>${d ? `<progress aria-label="${name}" max="${d}" value="${n}"></progress><small>${n} de ${d} repasos</small>` : ''}</article>`;
  };
  return title('Tu aprendizaje') + `<div class="stats">${stat('Repasos',fmt(reviews.recall.denominator),'Calificaciones válidas') + stat('Sesiones',fmt(practice.sessions),'Histórico de práctica') + stat('Correcciones',fmt(errors.current_approved),'Errores aprobados')}</div>
    ${practice.sessions ? '' : empty('El primer repaso abre el historial','Revela una tarjeta y califícala para registrar tu primera sesión.')}
    <div class="grid">${outcome('Recuerdo',reviews.recall,'Repasos con calificación de 3 a 5.') + outcome('Olvidos',reviews.lapse,'Fallos tras un repaso anterior satisfactorio.') + outcome('Corrección',errors.first_review_recall,'Primer repaso satisfactorio de una tarjeta de error.')}</div>`;
}
const grades = ['En blanco','Incorrecta','Casi','Con esfuerzo','Bien','Sin dudar'];
function study() {
  const {cards,deck,notes,answer} = session;
  const card = cards[notes.length];
  if (!card) return title(notes.length ? 'Sesión completada' : 'Estás al día') + `<section class="panel finish"><span class="orb">✴</span><h2>${esc(deck.name)}</h2><p>${notes.length ? `Recordaste ${notes.filter(n => n >= 3).length} de ${notes.length} tarjetas.` : 'Este mazo no tiene tarjetas pendientes.'}</p><a class="primary" href="#inicio">Volver al inicio →</a></section>`;
  return title('Sesión de repaso') + `<section class="panel study"><div class="section-head"><span>${esc(deck.name)}</span><small>${notes.length+1} / ${cards.length}</small></div>
  <progress aria-label="Tarjetas completadas" value="${notes.length}" max="${cards.length}"></progress><span class="kicker">Pregunta</span><h2>${esc(card.front)}</h2>
  ${answer ? `<div class="answer"><span class="kicker">Respuesta</span><p>${esc(answer.back)}</p>${(answer.accepted_answers || []).map(a=>`<p>${esc(a)}</p>`).join('')}${answer.explanation ? `<small>${esc(answer.explanation)}</small>` : ''}</div><fieldset><legend>¿Cuánto recordaste?</legend><div class="grades">${grades.map((g,i)=>`<button data-grade="${i}"><strong>${i}</strong>${g}</button>`).join('')}</div></fieldset>` :
  '<p>Piensa en tu respuesta antes de continuar.</p><button class="primary" data-reveal>Revelar respuesta <kbd>Espacio</kbd></button>'}</section>`;
}

async function render() {
  const current = ++version;
  const [view,id] = path().split('/');
  session = null;
  for (const a of menu.querySelectorAll('a')) {
    if (a.hash === '#'+view) a.setAttribute('aria-current','page');
    else a.removeAttribute('aria-current');
  }
  main.innerHTML = '<p role="status">Cargando…</p>';
  try {
    let html;
    if (view === 'analitica') html = await analytics();
    else {
      const decks = await all('/decks');
      if (view === 'inicio') html = await dashboard(decks);
      else if (view === 'estudio' && /^\d+$/.test(id)) {
        const deck = decks.find(d=>d.id === id);
        if (!deck) throw Error('Error 404. El mazo ya no está disponible.');
        const cards = await all('/decks/'+id+'/due', ({id,front})=>({id,front}));
        if (current !== version) return;
        session = {cards,deck,notes:[],answer:null};
        html = study();
      } else if (Object.hasOwn(views,view)) html = title(views[view][2]) + await (await loadWorkshop()).workshop(view,decks);
      else html = title('Vista desconocida') + '<a href="#inicio">Ir al inicio</a>';
    }
    if (current === version) {
      main.innerHTML = html;
      main.focus({preventScroll:true});
      document.title = main.querySelector('h1')?.textContent + ' · TechCards';
    }
  } catch (e) {
    if (current === version) main.innerHTML = title('No se pudo abrir esta vista') + `<p role="alert">${esc(e.message)}</p><button data-refresh>Reintentar</button>`;
  }
}
async function act(button, form) {
  if (busy) return;
  const current = version;
  busy = true;
  flash(form ? 'Guardando…' : 'Consultando…');
  if (button) button.disabled = true;
  try {
    if (form) {
      const message = await (await loadWorkshop()).submitWorkshop(form);
      if (current !== version) return;
      await render();
      flash(message);
    } else {
      const s = session;
      const card = s.cards[s.notes.length];
      if (button.hasAttribute('data-reveal')) s.answer = await api('/study/'+card.id+'/reveal',{});
      else {
        const grade = Number(button.dataset.grade);
        await api('/study/'+card.id+'/grade',{quality:grade});
        s.notes.push(grade);
        s.answer = null;
      }
      if (current !== version) return;
      main.innerHTML = study();
      const target = main.querySelector(s.answer ? '.answer p' : 'h2');
      target?.setAttribute('tabindex','-1');
      target?.focus();
      flash('');
    }
  } catch (e) { if (current === version) {
      if (button?.hasAttribute('data-grade')) {
        main.innerHTML = title('Comprueba tu cola') + '<p>Vuelve a consultar las tarjetas pendientes antes de calificar de nuevo.</p><button data-refresh>Actualizar sesión</button>';
        session = null;
      }
      flash(e.message,true);
    } }
  finally { busy = false; if (button) button.disabled = false; }
}
main.addEventListener('click', e => {
  const button = e.target.closest('button');
  if (button?.matches('[data-refresh]')) { flash(''); render(); }
  if (button?.matches('[data-grade],[data-reveal]')) act(button);
});
main.addEventListener('submit', e => { e.preventDefault(); act(e.submitter,e.target); });
document.addEventListener('keydown', e => {
  if (!session || !(e.target instanceof Element) || e.repeat || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey || e.target.closest('input,textarea,select,a,[contenteditable=true]')) return;
  const selector = e.code === 'Space' && !e.target.closest('button') ? '[data-reveal]' : /^[0-5]$/.test(e.key) ? '[data-grade="'+e.key+'"]' : null;
  const button = selector && main.querySelector(selector);
  if (button) { e.preventDefault(); button.click(); }
});
document.querySelector('.skip').addEventListener('click', event => {
  event.preventDefault();
  main.focus();
});
window.addEventListener('hashchange', () => { flash(''); window.scrollTo(0,0); render(); });
render();
