# Claim

## Qué es esto

Claim es una plataforma privada, entre amigos, para apostar sobre el desarrollo de torneos de
Debate Parlamentario Británico (British Parliamentary, BP). La idea es simple: apuntamos la
plataforma a un torneo que esté publicando su TAB en vivo en
[CalicoTab](https://www.calicotab.com/) (el hosting público de [Tabbycat](https://tabbycat.readthedocs.io/),
el software de gestión de torneos de debate más usado en el circuito), un scraper lo va
consultando periódicamente en segundo plano, y sobre esos datos en vivo (equipos, oradores,
resultados de rondas, break) el grupo de amigos puede crear y responder mercados de predicción:
quién sale campeón, quién rompe, quién encabeza la tabla de oradores, quién gana tal ronda,
etc.

**El puntaje se lleva en dólares ficticios apostados ("$"), no en puntos abstractos** — es la
convención de presentación de toda la plataforma (leaderboard, historial de predicciones, etc.),
pensada para que se sienta como una casa de apuestas real entre amigos. Los "dólares" se
liquidan automáticamente contra los resultados reales apenas CalicoTab los publica (salvo un
par de mercados que son juicios cualitativos y requieren confirmación manual del admin — ver
"Limitaciones conocidas").

**No hay dinero real involucrado en ningún punto del sistema** — ni se procesan pagos, ni se
almacenan medios de pago, ni los "dólares" tienen ningún valor o respaldo fuera de esta
aplicación. Es un juego social para seguir el torneo con más intensidad entre un grupo cerrado
de conocidos; los montos son enteramente ficticios y simbólicos.

## Arquitectura

### Los servicios de Docker Compose

`docker-compose.yml` define seis servicios:

| Servicio        | Rol |
|------------------|-----|
| `postgres`       | Base de datos relacional (Postgres 16). Fuente de verdad única de todo el sistema: torneos, participantes, resultados, usuarios, apuestas. |
| `redis`          | Broker de mensajes para Celery y backend de resultados; también disponible para cache si el backend lo necesita. |
| `backend`        | API FastAPI (`app.main:app`). Al arrancar corre `alembic upgrade head` (aplica migraciones pendientes) y luego levanta `uvicorn`. Expone `/health` y (una vez montados los routers) `/api/v1/...` y `/docs` (Swagger UI autogenerada por FastAPI). |
| `celery-worker`  | Ejecuta las tareas asíncronas (scraping de un torneo, liquidación de mercados, etc.) encoladas por `celery-beat` o disparadas manualmente desde la API. Comparte imagen con `backend` — mismo código, distinto comando (`celery ... worker`). |
| `celery-beat`    | El scheduler de Celery: dispara periódicamente la tarea `scrape_all_active_tournaments` (cada `SCRAPE_INTERVAL_SECONDS`, ver `app/tasks/celery_app.py`). No sirve tráfico HTTP, solo encola trabajo para `celery-worker`. |
| `frontend`       | Next.js (App Router). Consume la API del backend vía `NEXT_PUBLIC_API_URL`. |

`backend`, `celery-worker` y `celery-beat` se construyen desde el mismo contexto (`./backend`)
y comparten esencialmente la misma imagen (`bp-tab-backend:latest`); lo único que cambia es el
comando de arranque. Los tres dependen de que `postgres` y `redis` estén *healthy*
(`condition: service_healthy`) antes de arrancar, para no competir con la base de datos
todavía inicializando. `postgres` se healthchequea con `pg_isready`, `redis` con
`redis-cli ping`, y `backend` con un one-liner de Python
(`urllib.request.urlopen("http://localhost:8000/health")`) en vez de `curl`, porque la imagen
base `python:3.12-slim` no trae `curl` instalado y no vale la pena engordar la imagen solo para
un healthcheck.

### La arquitectura en capas de `backend/app/`

El backend sigue una cadena de dependencias en una sola dirección:

```
domain -> repositories -> services -> api
                                        ^
scraper -----------------------------> (vía services.ingestion)
                                        ^
tasks ---------------------------------+
```

- **`domain/`** — lógica de negocio pura, sin SQLAlchemy ni I/O: cálculo de puntajes de BP
  (`scoring.py`), ranking de equipos (`ranking.py`), predicción de break (`break_predictor.py`).
  Se puede testear sin base de datos ni red, y es reutilizable desde cualquier capa superior.
- **`repositories/`** — el mecanismo genérico de upsert idempotente (`upsert.py`) que usa
  "natural keys" (ej. `(tournament_id, external_id)`) en vez de asumir que los IDs internos
  coinciden entre corridas del scraper.
- **`services/`** — orquestación con estado/DB: `ingestion.py` (vuelca un snapshot del scraper
  en filas upsertadas, y registra qué cambió), `tournament_service.py`, `betting_service.py`
  (liquidación de mercados), `break_service.py`, `ranking_service.py`.
- **`api/`** — routers FastAPI; la única capa que sabe de HTTP, autenticación y serialización.
  No contiene lógica de negocio, solo la traduce a/desde `services`.
- **`scraper/`** — todo lo que sabe leer CalicoTab (ver sección siguiente). Es la única capa
  que sabe de HTML/JSON de un tercero; produce DTOs planos (`scraper/dtos.py`) que no dependen
  de SQLAlchemy, así que en teoría podría alimentar cualquier storage, no solo Postgres.
- **`tasks/`** — integración con Celery: `celery_app.py` define la app y el `beat_schedule`;
  `scrape_tasks.py` es el punto de entrada que un worker ejecuta, y que a su vez llama al
  `scraper` y luego a `services.ingestion`.

Esta separación existe para que cada capa se pueda testear (y razonar) de forma aislada: el
dominio no necesita mockear HTTP ni DB, el scraper no necesita levantar Postgres, y la API no
necesita reimplementar reglas de negocio.

### La estrategia de scraping de CalicoTab

El hallazgo central que hace viable este proyecto sin un navegador headless (Playwright/Selenium,
con todo el costo operativo que eso implica) es que **cada página "tab" de CalicoTab
(tabla de equipos, tabla de oradores, resultados de ronda, lista de participantes, lista de
instituciones, listas de break) ya viene con toda su data estructurada embebida en el HTML
inicial**, en un `<script>` que asigna `window.vueData`:

```js
window.vueData = {
  tablesData: [{"head": [...], "data": [[...], ...]}, ...]
}
```

Tabbycat usa Vue.js solo para *pintar* esa tabla en el cliente — pero el JSON con todos los
datos ya está presente en la respuesta HTML original. Como documenta el docstring de
`backend/app/scraper/vuedata.py`, esto significa que nunca hace falta ejecutar JavaScript ni
levantar un navegador: basta con pedir la página por HTTP y extraer ese bloque.

El detalle no trivial es que el objeto externo usa una key sin comillas (`{tablesData: [...]}`),
lo cual es JS válido pero no JSON válido, así que no se le puede pasar entero a `json.loads`.
La solución (en `extract_tables_data`) es ubicar el literal `tablesData:` y hacer un
bracket-matching balanceado (respetando que los corchetes puede aparecer dentro de strings)
desde el `[` que sigue hasta su `]` correspondiente — el *array* interno sí es JSON estricto, así
que solo esa porción se parsea. El código deliberadamente nunca hace `eval()` de ese script: es
contenido de un tercero, y evaluarlo sería ejecutar JS arbitrario.

Sobre ese array de tablas, `parsers.py` hace lookups por **key de columna** (`row_to_dict` +
`head[i]["key"]`), no por posición — así los parsers tomados de conjunto toleran que Tabbycat
reordene o agregue columnas sin romperse; solo un renombre/eliminación de una key rompe el
parser (y en ese caso, `ParseError` se levanta explícitamente en vez de devolver datos
silenciosamente incorrectos). La única página que no trae `vueData` es el detalle de una
planilla/ballot individual, que es HTML semántico plano y se parsea con BeautifulSoup.

**Diseño API-first-con-fallback:** Tabbycat también expone opcionalmente una API REST propia
(DRF) por torneo, pero el organizador tiene que habilitarla explícitamente, y la mayoría no lo
hace (el torneo de referencia usado para desarrollar este proyecto, CMUDE 2025, la tiene
deshabilitada). `backend/app/scraper/api_source.py` implementa `TabbycatApiSource` y
`probe_api_availability`, que se llama una vez por torneo por ciclo de scraping (barato) para
detectar automáticamente si un organizador la habilita a mitad de torneo, sin necesitar un
redeploy. Cuando la API no está disponible (el caso común), el sistema cae al camino
HTML/`vueData` de `parsers.py`, que es el que sí está completamente verificado contra HTML real
capturado en producción. `api_source.py` deja documentado explícitamente en su propio docstring
que ese camino **no** está verificado contra una instancia real con la API habilitada, y que
ante cualquier duda hay que preferir el camino HTML.

## Resumen del modelo de datos

Entidades principales (`backend/app/models/*.py`), una línea cada una:

- **Tournament** — un torneo rastreado; su identidad externa es `(source_base_url, source_slug)`, no solo el dominio, porque un mismo despliegue de CalicoTab puede alojar varios torneos como sub-rutas hermanas.
- **Institution** — una institución/universidad participante; como CalicoTab no le da página propia ni id numérico, la clave natural es su código corto (ej. `PUCP`).
- **Team** — un equipo, vinculado (best-effort) a una institución vía el prefijo de su nombre.
- **Speaker** — un orador; CalicoTab no expone id numérico para oradores individuales al scrapear vía HTML/`vueData`, así que la clave natural es `(equipo, nombre)`.
- **Adjudicator** — un juez/adjudicador, con su institución y si es independiente.
- **Round** — una ronda del torneo (preliminar o de eliminación), con su secuencia y estado.
- **Room** — una sala/venue; tampoco tiene id público en CalicoTab, así que su nombre es la clave natural.
- **Debate** — un debate específico dentro de una ronda, con su sala, equipos, jueces y resultado.
- **DebateTeam** — la participación de un equipo en un debate: su posición BP (OG/OO/CG/CO), su rank y sus puntos en ese debate.
- **SpeakerScore** — el puntaje de un orador en un debate específico (nullable hasta que el torneo libera puntajes).
- **Break** — el break OFICIAL publicado por CalicoTab para una categoría; nunca se mezcla con nuestras propias proyecciones (ver BreakPrediction).
- **BreakPrediction** — nuestra propia proyección de break, calculada por `domain.break_predictor`, guardada una vez por ronda (nunca sobrescrita) para conservar el historial.
- **User** — un usuario de la plataforma (amigo del grupo), con rol `admin` o `user`.
- **BetMarket** — una pregunta de predicción abierta por el admin (ej. "¿Quién será campeón?"); define tipo, ventana de apertura/cierre y regla de puntos.
- **Prediction** — la respuesta de un usuario a un BetMarket, congelada (`locked_at`) al crearse para que un cambio posterior en el mercado no afecte apuestas ya hechas.
- **LeaderboardEntry** — tabla de posiciones agregada y de solo lectura, recalculada íntegramente por el servicio de liquidación; nunca se edita a mano.
- **ScrapeLog** — un registro por corrida de scraping (qué se buscó, qué cambió, cuánto tardó), usado por la pantalla de logs del admin.
- **ChangeEvent** — un cambio puntual detectado entre un ciclo de scraping y el siguiente; solo se escribe cuando un valor realmente cambió, nunca en un re-fetch sin novedades.

Además de estas, existen tablas de soporte más pequeñas (categorías de break/oradores,
vínculos many-to-many equipo↔categoría y orador↔categoría, metadata de la planilla/ballot en
`Result`, jueces por debate en `DebateAdjudicator`, y el break de jueces en
`AdjudicatorBreak`) — no se detallan una por una aquí porque son extensiones directas de las
entidades de arriba.

## Cómo correr (quickstart)

Requisitos: Docker y Docker Compose (plugin `docker compose`, no el viejo `docker-compose`
standalone).

```bash
cp .env.example .env
docker compose up --build
```

Eso levanta los seis servicios. Una vez arriba:

- Frontend: [http://localhost:3000](http://localhost:3000) (o el puerto que hayas puesto en `FRONTEND_PORT` dentro de tu `.env`).
- API backend: [http://localhost:8000](http://localhost:8000) (`BACKEND_PORT` en `.env`), con la documentación interactiva autogenerada en [http://localhost:8000/docs](http://localhost:8000/docs).

`docker compose up --build` corre migraciones (`alembic upgrade head`) automáticamente cada vez
que arranca `backend`, así que no hace falta correrlas a mano en este flujo.

## Cómo desarrollar

### Backend

```bash
cd backend
python -m venv .venv
./.venv/Scripts/python -m pip install -e ".[dev]"   # Windows; en Linux/Mac: .venv/bin/python
```

Correr la suite de tests:

```bash
cd backend
./.venv/Scripts/python -m pytest
```

Lint / formato / tipos (lo mismo que corre en CI):

```bash
./.venv/Scripts/python -m ruff format --check .
./.venv/Scripts/python -m ruff check .
./.venv/Scripts/python -m mypy app/
```

**Migraciones**: el esquema vive como modelos SQLAlchemy en `app/models/*.py`; Alembic
autogenera el diff contra la base de datos real:

```bash
cd backend
alembic revision --autogenerate -m "descripción del cambio"
alembic upgrade head
```

`alembic/env.py` permite apuntar a una URL distinta vía la variable de entorno
`ALEMBIC_DATABASE_URL` (o `alembic -x db_url=...`), lo cual es útil para redactar una migración
contra un SQLite descartable local sin necesitar una instancia de Postgres corriendo — así es
también como CI valida el import de `alembic/env.py` sin depender de una base real más que como
red de seguridad.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Necesita `NEXT_PUBLIC_API_URL` apuntando al backend (por defecto `http://localhost:8000`; ver
`.env.example`). En desarrollo local fuera de Docker, exportá esa variable o creá un
`frontend/.env.local` (ignorado por git) antes de correr `npm run dev`.

## Cómo desplegar

Esto es honesto: **no hay una configuración de despliegue "cloud-managed" (Kubernetes,
Terraform, un IaC provider, etc.) provista por este proyecto**, ni tiene sentido inventarla para
la escala que tiene (un grupo privado de amigos). El despliegue previsto es literalmente
`docker compose` en un solo host — un VPS barato o una VM en la nube que vos ya tengas —
alcanza y sobra:

1. Cloná el repo en el servidor.
2. `cp .env.example .env` y completá valores reales — en particular:
   - `JWT_SECRET`: un secreto largo y aleatorio, no el placeholder de desarrollo.
   - `POSTGRES_PASSWORD`: una contraseña real, no `bp`.
   - `NEXT_PUBLIC_API_URL`: la URL pública donde el backend va a quedar expuesto (dominio o IP del servidor), no `localhost`.
   - `CORS_ALLOWED_ORIGINS`: el/los dominio(s) reales desde donde el frontend va a servir.
3. `docker compose up -d --build`.
4. Poné un reverse proxy (nginx, Caddy, Traefik) delante si querés TLS/dominio propio — eso
   tampoco está resuelto por este repo hoy.

No hay pipeline de despliegue automático (el CI en `.github/workflows/ci.yml` corre lint, tests
y valida que ambas imágenes construyan, pero no publica nada a ningún registry ni hace deploy);
llevar cambios a producción hoy es un paso manual (`git pull && docker compose up -d --build` en
el servidor).

## Cómo agregar un torneo nuevo

Esto es la razón de ser del diseño multi-tenant del esquema: **agregar un torneo nuevo es
literalmente insertar una fila `Tournament` nueva**, con un `source_base_url` / `source_slug`
distinto (por ejemplo, otro subdominio o sub-ruta de CalicoTab). No hace falta ningún cambio de
código. Se puede hacer:

- Desde el panel de administración del frontend (una vez que exista esa pantalla), o
- Directamente contra la API: `POST /tournaments` (admin) con
  `{name, source_base_url, source_slug, timezone}` (ver `docs/api_contract.md`).

Cada fila `Tournament` scopea de forma independiente todo lo que cuelga de ella (equipos,
rondas, mercados de apuestas, leaderboard...) — la unicidad de cada tabla siempre incluye
`tournament_id`, así que dos torneos nunca pueden pisarse entre sí aunque el sitio origen
reutilice ids externos (ver `TournamentScopedMixin` en `app/models/mixins.py`). Apenas se crea
el torneo, el próximo ciclo de `celery-beat` (`scrape_all_active_tournaments`) lo va a empezar a
rastrear solo.

## Cómo agregar un scraper nuevo (para una plataforma distinta a CalicoTab/Tabbycat)

El punto de extensión es la forma de un `TabDataSource`: cualquier fuente de datos de torneo,
sea CalicoTab/Tabbycat u otra plataforma, solo necesita producir los mismos DTOs definidos en
`backend/app/scraper/dtos.py` (`ScrapedInstitution`, `ScrapedTeam`, `ScrapedSpeaker`,
`ScrapedAdjudicator`, `ScrapedDebate`, `ScrapedBallot`, etc. — dataclasses puras, sin
SQLAlchemy). Para soportar una plataforma nueva hace falta:

1. Un módulo equivalente a `parsers.py` (o a `api_source.py`, si la plataforma nueva expone una
   API) que sepa leer el formato propio de esa plataforma y devuelva esos mismos DTOs.
2. Un nuevo orquestador equivalente a `TournamentScraper` (`scraper/orchestrator.py`), o una
   rama dentro del existente, que sepa qué páginas/endpoints pedir y en qué orden para esa
   plataforma.

El resto del sistema — `services.ingestion` (que solo sabe convertir DTOs en filas upsertadas),
el resto de `services/`, toda la capa `api/`, y el frontend entero — está diseñado para ser
100% agnóstico de CalicoTab específicamente: no necesitan ningún cambio para soportar una
plataforma nueva, siempre que el módulo nuevo entregue los DTOs esperados. Esto es exactamente
lo que documenta el docstring de `scraper/dtos.py`: "tomorrow's CalicoTab v2 or an entirely
different tab system just needs to produce the same DTOs, and every downstream service keeps
working unmodified."

## Filosofía de testing

La suite de tests de scraping/ingestión (`backend/tests/scraper/`) corre contra **HTML real
capturado de un torneo en vivo** (`backend/tests/scraper/fixtures/*.html` — listas de
participantes, tabla de equipos, tabla de oradores, resultados de ronda, una planilla/ballot
real, etc.), no contra mocks sintéticos armados a mano. Esto importa porque el HTML real trae
toda la variabilidad e irregularidad que un mock nunca reproduciría (columnas en orden
inesperado, celdas vacías, casos borde de texto) — si los parsers pasan contra esos fixtures,
hay bastante más confianza de que también van a funcionar contra el sitio real, no solo contra
la forma idealizada que uno *cree* que tiene el HTML.

## Limitaciones conocidas

Documentadas honestamente porque están anotadas como tales directamente en el código:

- **El vínculo equipo → institución es una heurística de mejor esfuerzo.** CalicoTab no publica
  ese vínculo en ningún lado público para el circuito usado como referencia; se infiere
  emparejando el código de institución conocido más largo que sea prefijo del nombre del equipo
  (ej. `"PUCP FM"` → institución `PUCP`). Si no hay match, el equipo simplemente queda sin
  institución asignada. Ver `_match_institution_by_name_prefix` en
  `backend/app/services/ingestion.py`.
- **El parseo de team break no está verificado contra un fixture en vivo.** `parse_team_break`
  en `backend/app/scraper/parsers.py` está escrito contra la plantilla pública documentada de
  Tabbycat para esa página, pero el torneo de referencia usado durante el desarrollo (CMUDE
  2025) no había llegado a su break de equipos todavía, así que a diferencia de todos los demás
  parsers del módulo, este nunca corrió contra HTML real capturado. Cualquier desajuste
  estructural levanta `ParseError` (se loguea, nunca se adivina un valor).
- **La liquidación del mercado `BREAKOUT_TEAM` ("equipo revelación") requiere entrada manual del
  admin.** A diferencia de los demás tipos de apuesta, no tiene un resultado mecánicamente
  derivable de los datos del torneo — es un juicio cualitativo sobre qué equipo superó más las
  expectativas — así que solo puede liquidarse pasando `manual_outcome` explícitamente (típicamente
  desde el panel de admin), ver `backend/app/services/betting_service.py`.
- **El adaptador de la API oficial de Tabbycat (`scraper/api_source.py`) no está verificado
  contra una instancia real con esa API habilitada** (el torneo de referencia la tenía
  deshabilitada). Se construyó estrictamente contra la documentación pública de Tabbycat, pero
  hay que tratarlo como no verificado hasta probarlo contra un torneo real que sí la exponga; el
  camino HTML/`vueData` (`parsers.py`) es el que está completamente verificado y es el que se
  usa por defecto.
