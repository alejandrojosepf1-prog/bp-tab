# Ruta de trabajo — Claim

Estado al momento de escribir esto: **206 tests backend en verde, ruff limpio, frontend `tsc` +
`eslint` + `next build` limpios.**

Contexto de producto que hay que tener presente en TODO lo que sigue:

- Claim **no es apuestas reales**. Nunca hay dinero. Cada cuenta arranca con **100 tokens**
  (`app.models.betting.STARTING_BALANCE`).
- **No existe "la casa".** No hay banca, no hay comisión, no hay vig. La cuota ofrecida es el
  precio justo `1/p` exacto (`app/domain/odds.py`).
- Los tokens de los ganadores salen del juego entre usuarios, no de un fondo. El leaderboard mide
  **habilidad de predicción** (profit neto), no riqueza.

---

## Ya hecho en esta pasada (T1–T4 de la ruta original + 3 pedidos extra)

- **T1 — `/admin/finance` reencuadrada.** `house_finance_service.py` → `game_economy_service.py`
  (`HouseSummary` → `EconomySummary`, `MarketExposure` → `MarketPayoutSpread`). Nuevo endpoint
  `GET /admin/game-economy` con tokens en circulación, apostadores activos, apuestas
  abiertas/liquidadas, e **inflación neta de tokens** (`total_paid_out - total_staked_settled`).
- **T2 — N+1 de `market_board` arreglado.** El fallback genérico (round_winner/round_full_call/
  top_speaker_position/head_to_head/top_n_*) ya no llama `quote_odds` una vez por payload distinto
  (cada llamada recalculaba power ratings + releía todas las apuestas). Ahora
  `_generic_fallback_options` calcula power ratings y stakes abiertos UNA vez por carga de mercado.
  Test de caracterización (`test_market_board_round_winner_multi_debate_characterization`) pinea
  las cuotas exactas de antes del refactor — si alguien las cambia sin querer, ese test falla.
- **T3 — barrido `$` → tokens.** Nuevo `frontend/src/lib/format.ts`
  (`formatTokens`/`formatSignedTokens`), usado en todos lados donde antes había un `$` hardcodeado.
- **T4 (parcial) — pulido.** `CountdownBadge` ahora cambia a ámbar bajo 1h y a rojo bajo 10min.
  El acordeón de `/bets` muestra un contador por sección (`Mercados cerrados · 4`) y un
  `EmptyState` por sección si queda vacía — el conteo se actualiza en vivo incluso con la sección
  colapsada (los `TournamentMarketsGroup` siguen montados, solo se ocultan con `hidden`).
- **Bug reportado: reabrir un mercado cerrado lo volvía a cerrar solo.** `closes_at` seguía en el
  pasado tras reabrir, así que `POST .../predictions` seguía rechazando apuestas (`now >=
  closes_at`). Ahora `PATCH /bet-markets/{id}` exige una `closes_at` nueva en el futuro al
  reabrir un mercado vencido (`set_bet_market_status`), y el admin panel pide esa fecha con un
  diálogo antes de reabrir.
- **Pestaña de Ranking.** Nueva `GET /leaderboard/global` (suma `LeaderboardEntry.total_points`
  por usuario a través de todos los torneos) + página `/ranking` en el nav principal.

---

## Pendiente: T4 restante (pulido menor, sin bugs)

Nada bloqueante — hacer si hay tiempo, en orden de impacto:

1. **Skeletons en vez de "Cargando…".** `LoadingState` es texto plano; en `/bets` y `/dashboard`
   causa saltos de layout. Bloques skeleton con la forma de la tarjeta real.
2. **Feedback al apostar.** La mutación de apostar tiene éxito silenciosamente más allá del toast
   genérico existente — una animación corta en el balance del sidebar cerraría el ciclo visual.
3. **Foco/teclado.** Los pickers de `market-card.tsx` son `<button>`s sin `focus-visible`
   consistente. Hoy no se puede navegar la app con teclado de forma decente.
4. **Mobile.** `/admin/markets` y `/admin/finance` tienen filas que pueden desbordar bajo 380px —
   verificar con el viewport móvil del navegador integrado.
5. **Tarjetas cerradas visualmente apagadas.** Ahora que "Mercados cerrados" tiene contador y
   empty-state, todavía podrían llevar menos opacidad/acento de color para que la vista abierta
   domine visualmente.

---

## T5. Decisión de diseño pendiente (NO implementar sin confirmar con el usuario)

**Cuotas fijadas vs. pari-mutuel verdadero.**

Hoy: la cuota se **congela** cuando apostás, y el pago es `stake × odds` sin importar cuánto haya
en el pool. Es un modelo de casa de apuestas de cuota fija — pero *sin* casa que respalde los
pagos. Consecuencia: cuando los pagos de los ganadores superan el pool, **el sistema crea tokens
de la nada** (esto es justo lo que `net_token_inflation` en `/admin/finance` ahora hace visible).
No rompe nada (los tokens son de juguete), pero la economía se infla con el tiempo.

La alternativa, que encaja más literal con "las apuestas se llevarán por las apuestas que hagan los
usuarios, nada de intervención de la casa": **pari-mutuel de verdad**, donde el pago se calcula al
liquidar como `stake / total_apostado_al_ganador × pool_total`. Suma cero exacta: se reparte lo que
hay, ni un token más.

Trade-off real: con pari-mutuel puro **no se puede prometer un pago al momento de apostar** (la
cuota mostrada pasa a ser una proyección que se mueve hasta el cierre), lo cual es menos
satisfactorio para el usuario que ve "pagaría 250" y confía en ese número.

**Esto cambia settlement, el significado del campo `odds`, y bastante UI. No arrancar sin que el
usuario elija.** El motor ya está preparado para cualquiera de las dos: la matemática pari-mutuel
vive en `app/domain/odds.py::pari_mutuel_probability` y ya se usa para *precificar*; lo que
cambiaría es el *pago* en `betting_service.settle_market`.

---

## Cosas ya arregladas en la pasada anterior — no volver a tocarlas

- **Doble pago en liquidación** (`settle_market` re-acreditaba el pago de una predicción ya
  liquidada en cada ciclo de scrape). Cubierto por
  `test_settle_market_never_re_credits_an_already_settled_prediction`.
- **Mercados vacíos auto-liquidados** (`all([])` es `True`, así que un mercado de ronda recién
  creado sin apuestas se marcaba liquidado en el siguiente scrape). Cubierto por
  `test_settle_market_leaves_an_open_market_with_no_bets_alone`.
- **Margen de la casa del 7%** — eliminado de `app/domain/odds.py`. Banda de cuotas reencuadrada a
  1.01x–50x como guarda de legibilidad, no de responsabilidad de la casa.
- **Auto-scrape en producción** — `app/tasks/autoscrape.py` corre dentro del proceso de FastAPI
  (el deploy no tiene Celery ni Redis, así que el beat schedule nunca se ejecutaba). Configurable
  vía `AUTOSCRAPE_ENABLED` y `SCRAPE_INTERVAL_SECONDS`.
- **Balance inicial de 100 tokens** — migración `640d59ae9d26`.
