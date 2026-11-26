import { api, getDataMode, isReadOnlyMode } from "../api.js";
import {
  clear,
  closeModal,
  createHoldDeleteButton,
  el,
  formatCompact,
  formatInt,
  formatIsoDate,
  openModal,
  plural,
  renderEmptyState,
  renderErrorBanner,
  renderKindBadge,
  renderSkeleton,
  showToast,
} from "../ui.js";

const CARDS_PAGE_SIZE = 25;

export function mountDashboard(container, ctx) {
  let seq = 0;
  let disposed = false;

  async function load() {
    const mySeq = ++seq;
    clear(container);
    container.append(renderSkeleton("dashboard"));

    const [decksRes, draftErrorsRes] = await Promise.all([api.listDecks(), api.listErrors("draft")]);
    if (disposed || mySeq !== seq) return;

    if (!decksRes.ok) {
      clear(container);
      container.append(
        renderPageHeader(),
        renderErrorBanner(decksRes.error, () => load())
      );
      return;
    }

    const decks = decksRes.data || [];
    const draftErrorsCount = draftErrorsRes.ok ? (draftErrorsRes.data || []).length : 0;

    // Fetch due and total card counts per deck in parallel
    const enriched = await Promise.all(
      decks.map(async (deck) => {
        const [dueRes, cardsRes] = await Promise.all([
          api.listDueCards(deck.id),
          api.listAllCardsForDeck(deck.id),
        ]);
        const dueCount =
          typeof dueRes.syntheticCount === "number"
            ? dueRes.syntheticCount
            : dueRes.ok
              ? (dueRes.data || []).length
              : 0;
        const totalCount =
          typeof cardsRes.syntheticCount === "number"
            ? cardsRes.syntheticCount
            : cardsRes.ok
              ? (cardsRes.data || []).length
              : 0;
        return {
          deck,
          dueCount,
          totalCount,
          dueTruncated: Boolean(dueRes.truncated),
          totalTruncated: Boolean(cardsRes.truncated),
          statsError: !dueRes.ok || !cardsRes.ok,
        };
      })
    );

    if (disposed || mySeq !== seq) return;

    const totalDue = enriched.reduce((acc, item) => acc + item.dueCount, 0);
    const totalCards = enriched.reduce((acc, item) => acc + item.totalCount, 0);
    const anyDueTruncated = enriched.some((item) => item.dueTruncated);
    const anyTotalTruncated = enriched.some((item) => item.totalTruncated);

    ctx.updateBadges({ due: totalDue, draftErrors: draftErrorsCount });

    clear(container);
    container.append(renderPageHeader());

    // Stats strip (honest real numbers only)
    const statsStrip = el(
      "section",
      { className: "stats-strip", "aria-label": "Resumen del día" },
      el(
        "div",
        { className: "stat-tile" },
        el("span", { className: "stat-label" }, "Pendientes hoy"),
        el(
          "strong",
          { className: `stat-value ${totalDue > 0 ? "stat-value--accent" : "stat-value--success"}` },
          `${formatCompact(totalDue)}${anyDueTruncated ? "+" : ""}`
        ),
        el("span", { className: "stat-sub" }, totalDue > 0 ? "Listas para repaso activo" : "Sin deuda pendiente")
      ),
      el(
        "div",
        { className: "stat-tile" },
        el("span", { className: "stat-label" }, "Mazos activos"),
        el("strong", { className: "stat-value" }, formatInt(decks.length)),
        el("span", { className: "stat-sub" }, plural(decks.length, "colección", "colecciones"))
      ),
      el(
        "div",
        { className: "stat-tile" },
        el("span", { className: "stat-label" }, "Tarjetas totales"),
        el("strong", { className: "stat-value" }, `${formatCompact(totalCards)}${anyTotalTruncated ? "+" : ""}`),
        el("span", { className: "stat-sub" }, plural(totalCards, "ficha registrada", "fichas registradas"))
      ),
      el(
        "div",
        { className: "stat-tile" },
        el("span", { className: "stat-label" }, "Errores en borrador"),
        el("strong", { className: "stat-value" }, formatInt(draftErrorsCount)),
        el(
          "span",
          { className: "stat-sub" },
          draftErrorsCount > 0 ? "Esperando aprobación" : "Bandeja limpia"
        )
      )
    );
    container.append(statsStrip);

    // Empty workspace state
    if (decks.length === 0) {
      container.append(
        renderEmptyState({
          variant: "cards",
          title: "Tu escritorio de estudio está listo",
          description:
            "Crea tu primer mazo para estudiar vocabulario técnico, frases de entrevista o plantillas STAR con repetición espaciada SM-2.",
          action: el(
            "div",
            { className: "page-actions" },
            el(
              "button",
              { type: "button", className: "btn btn--primary", onClick: () => openDeckModal(null) },
              "Crear primer mazo"
            ),
            getDataMode() === "live"
              ? el(
                  "button",
                  {
                    type: "button",
                    className: "btn btn--secondary",
                    onClick: () => ctx.setDataMode("demo"),
                  },
                  "Ver con Datos demo"
                )
              : null
          ),
        })
      );
      return;
    }

    // Focus Hero: highest-priority due deck or calm completion card
    const priority = [...enriched]
      .filter((item) => item.dueCount > 0)
      .sort((a, b) => b.dueCount - a.dueCount)[0];

    if (priority) {
      container.append(
        el(
          "section",
          { className: "focus-hero", "aria-label": "Siguiente sesión recomendada" },
          el(
            "div",
            { className: "focus-hero-body" },
            el("span", { className: "eyebrow" }, "Siguiente repaso prioritario"),
            el("h2", { className: "focus-hero-title", dir: "auto" }, priority.deck.name),
            el(
              "p",
              { className: "focus-hero-desc" },
              `Tienes ${plural(priority.dueCount, "tarjeta pendiente", "tarjetas pendientes")} hoy en este mazo. Recuerda primero en voz alta y revela después.`
            )
          ),
          el(
            "div",
            { className: "focus-hero-actions" },
            el(
              "button",
              {
                type: "button",
                className: "btn btn--primary btn--lg",
                onClick: () => ctx.navigate("estudiar", { deck: priority.deck.id }),
              },
              `Estudiar ahora (${formatCompact(priority.dueCount)})`
            ),
            el(
              "button",
              {
                type: "button",
                className: "btn btn--secondary",
                onClick: () => ctx.navigate("crear", { tab: "generar", deck: priority.deck.id }),
              },
              "Añadir tarjetas"
            )
          )
        )
      );
    } else {
      container.append(
        el(
          "section",
          { className: "focus-hero focus-hero--calm", "aria-label": "Estado de estudio" },
          el(
            "div",
            { className: "focus-hero-body" },
            el("span", { className: "eyebrow" }, "Repasos al día"),
            el(
              "h2",
              { className: "focus-hero-title" },
              totalCards > 0 ? "No tienes tarjetas vencidas hoy" : "Tus mazos aún no tienen tarjetas"
            ),
            el(
              "p",
              { className: "focus-hero-desc" },
              totalCards > 0
                ? "Buen ritmo. Puedes generar tarjetas desde tus notas, añadir una plantilla de entrevista o convertir errores en nuevas fichas."
                : "Empieza añadiendo tarjetas desde texto, plantillas STAR/Networking o creando fichas manuales."
            )
          ),
          el(
            "div",
            { className: "focus-hero-actions" },
            el(
              "button",
              {
                type: "button",
                className: "btn btn--primary",
                onClick: () => ctx.navigate("crear", { tab: "plantillas" }),
              },
              "Explorar plantillas"
            ),
            draftErrorsCount > 0
              ? el(
                  "button",
                  {
                    type: "button",
                    className: "btn btn--secondary",
                    onClick: () => ctx.navigate("errores"),
                  },
                  `Revisar ${plural(draftErrorsCount, "borrador", "borradores")}`
                )
              : null
          )
        )
      );
    }

    // Decks Section
    container.append(
      el(
        "div",
        { className: "section-heading" },
        el("h2", { className: "section-title" }, "Tus mazos"),
        el("span", { className: "section-meta" }, plural(decks.length, "mazo", "mazos"))
      )
    );

    const grid = el("div", { className: "deck-grid" });
    for (const item of enriched) {
      grid.append(renderDeckCard(item));
    }
    container.append(grid);
  }

  function renderPageHeader() {
    return el(
      "header",
      { className: "page-header" },
      el(
        "div",
        { className: "page-header-copy" },
        el("p", { className: "eyebrow" }, "TechCards · Repetición espaciada SM-2"),
        el("h1", { className: "page-title" }, "Escritorio de estudio"),
        el(
          "p",
          { className: "page-lead" },
          "Repasa primero por recuerdo activo, captura fallos reales de entrevista y convierte tus notas en tarjetas concretas."
        )
      ),
      el(
        "div",
        { className: "page-actions" },
        el(
          "button",
          {
            type: "button",
            className: "btn btn--secondary",
            onClick: () => ctx.navigate("crear", { tab: "generar" }),
          },
          "Generar tarjetas"
        ),
        el(
          "button",
          {
            type: "button",
            className: "btn btn--primary",
            onClick: () => openDeckModal(null),
          },
          "Nuevo mazo"
        )
      )
    );
  }

  function renderDeckCard({ deck, dueCount, totalCount, dueTruncated, totalTruncated }) {
    const masteredToday = totalCount > 0 ? Math.max(0, totalCount - dueCount) : 0;
    const progressPct = totalCount > 0 ? Math.min(100, Math.max(0, Math.round((masteredToday / totalCount) * 100))) : 0;

    let statusBadge;
    if (totalCount === 0) {
      statusBadge = el("span", { className: "badge" }, "Sin tarjetas");
    } else if (dueCount > 0) {
      statusBadge = el(
        "span",
        { className: "badge badge--accent" },
        `${formatCompact(dueCount)}${dueTruncated ? "+" : ""} hoy`
      );
    } else {
      statusBadge = el("span", { className: "badge badge--success" }, "Al día");
    }

    const progressMetaText =
      totalCount === 0
        ? "0 tarjetas"
        : `${plural(totalCount, "tarjeta", "tarjetas")}${totalTruncated ? "+" : ""} · ${progressPct} % al día`;

    return el(
      "article",
      { className: "deck-card" },
      el(
        "div",
        { className: "deck-card-head" },
        el(
          "div",
          { className: "deck-card-title-wrap" },
          el("h3", { className: "deck-card-title", dir: "auto", title: deck.name }, deck.name),
          deck.description
            ? el("p", { className: "deck-card-desc", dir: "auto", title: deck.description }, deck.description)
            : null
        ),
        statusBadge
      ),
      el(
        "div",
        { className: "deck-progress-block" },
        el(
          "div",
          { className: "deck-progress-meta" },
          el("span", { className: "num" }, progressMetaText),
          dueCount > 0
            ? el("span", { className: "num" }, `${plural(dueCount, "pendiente", "pendientes")}`)
            : null
        ),
        el(
          "div",
          {
            className: "progress-track",
            role: "progressbar",
            "aria-label": `Avance de ${deck.name}`,
            "aria-valuemin": "0",
            "aria-valuemax": "100",
            "aria-valuenow": String(progressPct),
          },
          el("div", {
            className: `progress-fill ${dueCount > 0 && progressPct === 0 ? "progress-fill--accent" : ""}`,
            style: `width: ${progressPct}%;`,
          })
        )
      ),
      el(
        "div",
        { className: "deck-card-actions" },
        el(
          "button",
          {
            type: "button",
            className: `btn ${dueCount > 0 ? "btn--primary" : "btn--secondary"} btn--sm`,
            onClick: () => ctx.navigate("estudiar", { deck: deck.id }),
          },
          dueCount > 0 ? "Estudiar" : "Abrir sesión"
        ),
        el(
          "div",
          { className: "deck-card-secondary" },
          el(
            "button",
            {
              type: "button",
              className: "btn btn--ghost btn--sm",
              onClick: () => openDeckInspectorModal(deck, totalCount),
            },
            "Fichas"
          ),
          el(
            "button",
            {
              type: "button",
              className: "btn btn--ghost btn--sm",
              onClick: () => openDeckModal(deck),
            },
            "Editar"
          )
        )
      )
    );
  }

  function openDeckModal(existingDeck) {
    const isEdit = Boolean(existingDeck);
    const nameInput = el("input", {
      type: "text",
      className: "input",
      id: "modal-deck-name",
      required: true,
      maxlength: "120",
      placeholder: "Ej. Cloud interviews · AWS & Networking",
      value: existingDeck ? existingDeck.name : "",
      enterkeyhint: "next",
    });
    const descInput = el("textarea", {
      className: "textarea",
      id: "modal-deck-desc",
      maxlength: "5000",
      placeholder: "Objetivo del mazo o temas que cubre (opcional)",
      value: existingDeck ? existingDeck.description : "",
    });
    const errorNode = el("div", { className: "field-error", role: "alert", hidden: true });
    const submitBtn = el(
      "button",
      { type: "submit", className: "btn btn--primary" },
      isEdit ? "Guardar cambios" : "Crear mazo"
    );

    const form = el(
      "form",
      {
        className: "form-grid",
        onSubmit: async (e) => {
          e.preventDefault();
          const name = nameInput.value.trim();
          const description = descInput.value.trim();
          if (!name) {
            errorNode.textContent = "Escribe un nombre para el mazo.";
            errorNode.hidden = false;
            nameInput.focus();
            return;
          }
          errorNode.hidden = true;
          submitBtn.disabled = true;

          const res = isEdit
            ? await api.updateDeck(existingDeck.id, { name, description })
            : await api.createDeck({ name, description });

          submitBtn.disabled = false;
          if (!res.ok) {
            errorNode.textContent = res.error;
            errorNode.hidden = false;
            return;
          }
          closeModal();
          showToast(isEdit ? "Mazo actualizado." : `Mazo «${res.data.name}» creado.`, { tone: "success" });
          load();
        },
      },
      el(
        "div",
        { className: "field" },
        el(
          "div",
          { className: "field-label-row" },
          el("label", { className: "field-label", for: "modal-deck-name" }, "Nombre del mazo"),
          el("span", { className: "field-hint" }, "Máx. 120 caracteres")
        ),
        nameInput
      ),
      el(
        "div",
        { className: "field" },
        el("label", { className: "field-label", for: "modal-deck-desc" }, "Descripción"),
        descInput
      ),
      errorNode,
      el(
        "div",
        { className: "form-actions" },
        isEdit
          ? createHoldDeleteButton({
              label: "Mantener para eliminar mazo",
              disabled: isReadOnlyMode(),
              onConfirm: async () => {
                const delRes = await api.deleteDeck(existingDeck.id);
                if (!delRes.ok) {
                  errorNode.textContent = delRes.error;
                  errorNode.hidden = false;
                  return;
                }
                closeModal();
                showToast("Mazo eliminado.", { tone: "warning" });
                load();
              },
            })
          : null,
        el("button", { type: "button", className: "btn btn--secondary", onClick: closeModal }, "Cancelar"),
        submitBtn
      )
    );

    openModal({
      title: isEdit ? "Editar mazo" : "Nuevo mazo",
      content: form,
    });
    setTimeout(() => nameInput.focus(), 30);
  }

  function openDeckInspectorModal(deck, approxTotal) {
    let page = 0;
    const host = el("div", { className: "stack" });

    async function renderPage() {
      clear(host);
      host.append(el("p", { className: "field-hint" }, "Cargando tarjetas…"));

      const offset = page * CARDS_PAGE_SIZE;
      const res = await api.listCards(deck.id, { offset, limit: CARDS_PAGE_SIZE });
      clear(host);

      if (!res.ok) {
        host.append(renderErrorBanner(res.error, renderPage));
        return;
      }

      const cards = res.data || [];
      if (cards.length === 0 && page === 0) {
        host.append(
          renderEmptyState({
            variant: "cards",
            title: "Mazo sin tarjetas",
            description: "Genera tarjetas desde texto, añade una plantilla o crea una ficha manual.",
            action: el(
              "button",
              {
                type: "button",
                className: "btn btn--primary btn--sm",
                onClick: () => {
                  closeModal();
                  ctx.navigate("crear", { tab: "manual", deck: deck.id });
                },
              },
              "Crear tarjeta"
            ),
          })
        );
        return;
      }

      const list = el("div", { className: "stack" });
      for (const card of cards) {
        list.append(
          el(
            "div",
            { className: "card-row" },
            el(
              "div",
              { className: "card-row-body" },
              el("p", { className: "card-row-front", dir: "auto" }, card.front),
              el("p", { className: "card-row-back", dir: "auto" }, card.back),
              el(
                "div",
                { className: "card-row-meta" },
                renderKindBadge(card.kind),
                el("span", {}, `Vence: ${formatIsoDate(card.due_date)}`),
                el("span", {}, `Rep ${card.repetitions} · ${card.interval_days} d`),
                card.source_label ? el("span", { title: card.source_label }, card.source_label) : null
              )
            ),
            createHoldDeleteButton({
              label: "Eliminar",
              disabled: isReadOnlyMode(),
              onConfirm: async () => {
                const del = await api.deleteCard(card.id);
                if (!del.ok) {
                  showToast(del.error, { tone: "error" });
                  return;
                }
                showToast("Tarjeta eliminada.", { tone: "warning" });
                renderPage();
                load();
              },
            })
          )
        );
      }

      host.append(list);

      const hasPrev = page > 0;
      const hasNext = cards.length === CARDS_PAGE_SIZE;
      host.append(
        el(
          "div",
          { className: "pagination-bar" },
          el(
            "span",
            { className: "num" },
            `Mostrando ${formatInt(offset + 1)}–${formatInt(offset + cards.length)}${
              approxTotal ? ` de ${formatInt(approxTotal)}` : ""
            }`
          ),
          el(
            "div",
            { className: "page-actions" },
            el(
              "button",
              {
                type: "button",
                className: "btn btn--secondary btn--sm",
                disabled: !hasPrev,
                onClick: () => {
                  page -= 1;
                  renderPage();
                },
              },
              "Anterior"
            ),
            el(
              "button",
              {
                type: "button",
                className: "btn btn--secondary btn--sm",
                disabled: !hasNext,
                onClick: () => {
                  page += 1;
                  renderPage();
                },
              },
              "Siguiente"
            )
          )
        )
      );
    }

    openModal({
      title: `Tarjetas · ${deck.name}`,
      content: host,
    });
    renderPage();
  }

  load();

  return () => {
    disposed = true;
    seq += 1;
  };
}
