# Ruta de trabajo para Sonnet — Claim

Estado al momento de escribir esto: **195 tests backend en verde, ruff limpio, frontend `tsc` +
`eslint` + `next build` limpios.** Todo lo de abajo es trabajo *nuevo*, no arreglos de algo roto.

Contexto de producto que hay que tener presente en TODO lo que sigue:

- Claim **no es apuestas reales**. Nunca hay dinero. Cada cuenta arranca con **100 tokens**
  (`app.models.betting.STARTING_BALANCE`).
- **No existe "la casa".** No hay banca, no hay comisión, no hay vig. Ya se quitó del motor de
  cuotas (`app/domain/odds.py`): la cuota ofrecida es el precio justo `1/p` exacto.
- Los tokens de los ganadores salen del juego entre usuarios, no de un fondo. El leaderboard mide
  **habilidad de predicción** (profit neto), no riqueza.

Orden recomendado: **T1 → T2 → T3 → T4 → T5**. T1 y T2 son los que más valor entregan.

---

## T1. Repensar `/admin/finance` — el encuadre "Finanzas de la Casa" ya no aplica

**Por qué:** la página, el servicio y el endpoint se construyeron cuando Claim todavía tenía casa
con comisión del 7%. Ahora no hay casa, así que "ganancia/pérdida de la casa" y "exposición" miden
algo que no existe conceptualmente. Peor: como ya no se cobra margen, `realized_net_profit` de la
casa tiende a cero-ish y solo confunde.

**Qué hacer:** convertirla en **"Actividad y economía del juego"** — las mismas queries, otro
encuadre. Métricas que sí significan algo sin casa:

- Tokens en circulación (suma de `User.balance`) y cuántos están comprometidos en apuestas abiertas.
- Volumen apostado (total, y por torneo).
- Nº de apuestas abiertas / liquidadas, apostadores activos.
- **Inflación de tokens**: `total_paid_out - total_staked_settled`. Con cuotas fijadas al momento
  de apostar y sin pool que las limite, el sistema *crea* tokens netos cuando ganan los favoritos.
  Esta es la métrica realmente útil para un admin: dice si la economía se está inflando.
- Mercado más movido, mayor apuesta individual, etc.

**Archivos:**
- `backend/app/services/house_finance_service.py` → renombrar a `game_economy_service.py`,
  reencuadrar dataclasses (`HouseSummary` → `EconomySummary`). `compute_market_exposure` se puede
  conservar tal cual pero renombrada a algo como `market_payout_spread` y presentada como "cuánto
  se pagaría según cómo resuelva", no como riesgo de la casa.
- `backend/app/api/routers/admin.py` (`GET /admin/house-finance` → `/admin/game-economy`),
  `backend/app/api/schemas/admin.py`, `backend/tests/services/test_house_finance_service.py`.
- `frontend/src/app/admin/finance/page.tsx`, `lib/api/client.ts`, `lib/api/types.ts`,
  `lib/api/query-keys.ts`, `app/admin/layout.tsx` (título), `components/layout/sidebar.tsx`.
- Los comentarios de los tests actuales dicen "house lost 70 on this round" — reescribirlos.

---

## T2. Arreglar el N+1 de `market_board` (el problema de eficiencia más grande que queda)

**Dónde:** `backend/app/services/odds_service.py`, la rama genérica al final de `market_board()`
(desde el comentario `# Remaining bet types have no enumerable candidate field`).

**El problema:** ese camino hace `await quote_odds(session, bet_market, payload)` **una vez por
cada payload distinto apostado**. Y cada `quote_odds`:

1. llama `compute_team_power_ratings()` / `compute_speaker_power_ratings()` — que a su vez hacen
   `get_standings()` + un join sobre todos los debates del torneo, y
2. llama `_open_stakes()` — que relee TODAS las predicciones del mercado.

Con un mercado `round_winner` de 10 salas × 4 equipos = hasta 40 payloads distintos → ~40×
recálculo completo de ratings + 40 lecturas de la tabla de predicciones, **en cada carga de
`/bets`**, que además refetchea cada 30s. Y esto afecta justo a los 3 tipos de mercado nuevos y más
usados: `round_winner`, `round_full_call`, `top_speaker_position`.

**Cómo arreglarlo:** las ramas de `CHAMPION` / `BEST_INSTITUTION` / `TEAM_BREAK` ya lo hacen bien —
calculan power/probabilidades **una vez** y luego arman todas las opciones. Replicar ese patrón:

1. Calcular `power` una sola vez antes del loop (según `bet_type`).
2. Traer `_open_stakes()` una sola vez y agrupar los "compartimentos" en memoria (por `debate_id`,
   por `position`, etc. — la lógica ya existe en `_debate_pool` / `_speaker_position_pool`, solo
   hay que invertirla para que agrupe todo de una pasada en vez de escanear por candidato).
3. Llamar `pari_mutuel_odds(...)` directo por opción, sin volver a pasar por `quote_odds`.

Lo más limpio es extraer un helper por bet_type que reciba `(power, stakes_ya_traídos, payload)` y
que **tanto `quote_odds` como `market_board` usen**, para que no puedan divergir — que es
exactamente el riesgo de duplicar la matemática. Ya hay precedente de este patrón en el repo:
`format_payload_label` se extrajo justo para eso.

**Verificación obligatoria:** antes de tocar nada, escribir un test que fije las cuotas que
`market_board` devuelve hoy para un mercado `round_winner` con varias salas y apuestas. Después del
refactor **los mismos números** tienen que salir. Es un refactor de rendimiento, no de
comportamiento — si las cuotas cambian, hay un bug.

---

## T3. Barrido de moneda: `$` → tokens

Ya se cambiaron los textos ("Dólares ficticios" → "Se juega con tokens", "Bankroll" → "Tokens").
Falta el **símbolo `$`**, que sigue hardcodeado en decenas de plantillas
(`` `$${x.toLocaleString("es")}` ``).

**Qué hacer:** crear un helper único, p. ej. `frontend/src/lib/format.ts`:

```ts
export const formatTokens = (n: number) => `${Math.round(n).toLocaleString("es")} ⛁`;
```

...y reemplazar todas las interpolaciones `${...}` de dinero por él. Elegir UNA representación
(sufijo "tokens", un símbolo, o un ícono de lucide junto al número) y aplicarla en todos lados —
hoy conviven `$100`, "Pool $0", "pagaría $X". Archivos con más ocurrencias:
`components/betting/market-card.tsx`, `app/account/page.tsx`, `app/admin/finance/page.tsx`,
`app/admin/markets/page.tsx`, `components/layout/sidebar.tsx`, `app/dashboard/page.tsx`.

Ojo: **no** cambiar los nombres de campos del backend (`stake_amount`, `balance`, `pool_total`)
— esto es solo capa de presentación.

---

## T4. Pulido visual / UX

Ninguno de estos es un bug; son mejoras de refinamiento. En orden de impacto:

1. **Jerarquía en `/bets`.** El acordeón Abiertos/Cerrados ya está. Falta: que "Mercados cerrados"
   muestre un contador en el header (`Mercados cerrados · 4`) para que no parezca vacío al estar
   colapsado, y que las tarjetas cerradas se vean visiblemente apagadas (opacidad / sin acento de
   color) para que la vista abierta domine.
2. **Estados vacíos por sección.** Si un grupo del acordeón queda sin mercados, hoy no renderiza
   nada y el acordeón abre en vacío. Poner un `EmptyState` chico dentro.
3. **`CountdownBadge` con urgencia.** En `components/ui/countdown-badge.tsx` el número es siempre
   del mismo color. Que pase a ámbar bajo 1h y a rojo bajo 10min — la señal más útil de toda la
   pantalla para alguien que está por perderse una apuesta. El componente ya recalcula cada
   segundo, es solo derivar la clase de `remaining`.
4. **Skeletons en vez de "Cargando…".** `LoadingState` es texto plano; en `/bets` y `/dashboard`
   causa saltos de layout. Poner bloques skeleton con la forma de la tarjeta real.
5. **Feedback al apostar.** Hoy la mutación tiene éxito silenciosamente. Un toast + una animación
   corta en el balance del sidebar cierra el ciclo.
6. **Foco/teclado.** Los pickers de `market-card.tsx` son `<button>`s sin `focus-visible` visible.
   Añadir anillo de foco consistente; hoy no se puede navegar la app con teclado de forma decente.
7. **Mobile.** `/admin/markets` y `/admin/finance` tienen filas que se desbordan bajo 380px.
   Verificar con el viewport móvil del navegador integrado.

---

## T5. Decisión de diseño pendiente (NO implementar sin confirmar con el usuario)

**Cuotas fijadas vs. pari-mutuel verdadero.**

Hoy: la cuota se **congela** cuando apostás, y el pago es `stake × odds` sin importar cuánto haya
en el pool. Es un modelo de casa de apuestas de cuota fija — pero *sin* casa que respalde los
pagos. Consecuencia: cuando los pagos de los ganadores superan el pool, **el sistema crea tokens
de la nada**. No rompe nada (los tokens son de juguete), pero la economía se infla con el tiempo.

La alternativa, que encaja más literal con "las apuestas se llevarán por las apuestas que hagan los
usuarios, nada de intervención de la casa": **pari-mutuel de verdad**, donde el pago se calcula al
liquidar como `stake / total_apostado_al_ganador × pool_total`. Suma cero exacta: se reparte lo que
hay, ni un token más.

Trade-off real: con pari-mutuel puro **no se puede prometer un pago al momento de apostar** (la
cuota mostrada pasa a ser una proyección que se mueve hasta el cierre), lo cual es menos satisfactorio
para el usuario que ve "pagaría 250" y confía en ese número.

**Esto cambia settlement, el significado del campo `odds`, y bastante UI. No arrancar sin que el
usuario elija.** El motor ya está preparado para cualquiera de las dos: la matemática pari-mutuel
vive en `app/domain/odds.py::pari_mutuel_probability` y ya se usa para *precificar*; lo que
cambiaría es el *pago* en `betting_service.settle_market`.

---

## Cosas que ya se arreglaron — no volver a tocarlas

- **Doble pago en liquidación** (`settle_market` re-acreditaba el pago de una predicción ya
  liquidada en cada ciclo de scrape). Regresión cubierta por
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
