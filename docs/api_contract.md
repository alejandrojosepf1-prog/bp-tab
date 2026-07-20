# BP$ REST API Contract (v1)

Base path: `/api/v1`. All responses JSON. Auth via `Authorization: Bearer <JWT>`.
Roles: `admin`, `user`. Endpoints marked **(admin)** require `role=admin`; everything else
just requires a valid logged-in user unless marked **(public)**.

This is the single source of truth both the backend (FastAPI implementation) and the frontend
(Next.js consumer) build against, so they stay in sync despite being built in parallel.

## Auth

- `POST /auth/register` `{email, password, display_name}` -> `User` (role always starts as `user`)
- `POST /auth/login` `{email, password}` -> `{access_token, token_type: "bearer"}`
- `GET /auth/me` -> `User`

`User` shape: `{id, email, display_name, role, is_active, created_at}`

## Tournaments

- `GET /tournaments` **(public)** -> `Tournament[]`
- `GET /tournaments/{id}` **(public)** -> `Tournament`
- `POST /tournaments` **(admin)** `{name, tab_url, timezone}` -> `Tournament` (`tab_url` is any link
  from the tournament's public CalicoTab tab, e.g.
  `https://cmude2025.calicotab.com/open/participants/list/` -- the backend derives
  `source_base_url`/`source_slug` from it via `app.domain.tab_url.parse_tab_url`; 422 if it can't
  be parsed, 409 if that `(source_base_url, source_slug)` is already registered. Creating a
  tournament immediately schedules its first scrape -- no separate "force scrape" click needed.)
- `PATCH /tournaments/{id}` **(admin)** `{name?, tab_url?, is_active?}` -> `Tournament`
- `POST /tournaments/{id}/scrape` **(admin)** -> `{status: "queued"}` (fires the Celery `scrape_tournament` task)

`Tournament` shape: `{id, name, slug, source_base_url, source_slug, status, api_available, champion_team_id, timezone, is_active, created_at}`
`status` enum: `upcoming | in_progress | eliminations | completed`

## Participants (all scoped under a tournament, all public/read-only)

- `GET /tournaments/{id}/institutions` -> `Institution[]` `{id, code, name, region}`
- `GET /tournaments/{id}/teams` -> `Team[]` `{id, external_id, name, emoji, institution: Institution|null, speakers: Speaker[]}`
- `GET /tournaments/{id}/teams/{team_id}` -> `Team` (same shape, single)
- `GET /tournaments/{id}/speakers` -> `Speaker[]` `{id, name, team_id, categories: string[]}`
- `GET /tournaments/{id}/adjudicators` -> `Adjudicator[]` `{id, external_id, name, institution: Institution|null, is_independent, broke}`

## Rounds / Debates / Results (public/read-only)

- `GET /tournaments/{id}/rounds` -> `Round[]` `{id, seq, name, stage, status}` (`stage`: `preliminary|elimination`)
- `GET /tournaments/{id}/rounds/{round_id}/debates` -> `Debate[]` (summary: id, room name, teams w/ position+rank+points)
- `GET /tournaments/{id}/debates/{debate_id}` -> `Debate` full detail:
  `{id, round: Round, room: {name}|null, status, motion_text, ballot_source_url,
    teams: [{team: Team, position, rank_in_debate, team_points, speaker_points_total,
             speakers: [{speaker: Speaker, role, score, is_iron}]}],
    adjudicators: [{adjudicator_id, name, role}]}`

## Standings / Ranking (public)

- `GET /tournaments/{id}/standings?break_category_id=&as_of_round_seq=` ->
  `TeamStanding[]` `{team: Team, rank, team_points, total_speaker_points, firsts, seconds, thirds, fourths, debates_played}`

## Break (public)

- `GET /tournaments/{id}/break-categories` -> `BreakCategory[]` `{id, name, slug, is_general, break_size}`
- `GET /tournaments/{id}/break-categories/{cat_id}/predictions` ->
  `BreakAssessment[]` `{team: Team, status, probability, projected_rank, points_needed_for_safety}`
  (`status`: `safe|alive|eliminated`)
- `GET /tournaments/{id}/break-categories/{cat_id}/break` -> `Break[]` `{team: Team, rank}[]`
  (official confirmed break; 404/empty until CalicoTab publishes it)

## Betting

**Unit convention:** `points_awarded` (on `Prediction`) and `total_points` (on `LeaderboardEntry`)
are denominated in **fictional USD** ("dólares apostados"), not abstract points -- there is no
real money anywhere in this platform, but the friend group's score is expressed and displayed
as dollars won/lost (e.g. render `points_awarded` as `"$100"`, not `"100 pts"`). Same for every
number inside a `BetMarket.points_rule` (e.g. `{"points": 100}` means "$100 for a correct
guess"). The frontend should format all of these with a `$` prefix.

- `GET /tournaments/{id}/bet-markets` -> `BetMarket[]`
  `{id, bet_type, label, description, opens_at, closes_at, status, target_round_id, target_break_category_id}`
  (`bet_type`: `champion|top_n_break|top_n_speakers|round_winner|head_to_head|breakout_team|best_institution`)
  (`status`: `open|closed|settled`)
- `POST /tournaments/{id}/bet-markets` **(admin)** `{bet_type, label, description?, opens_at, closes_at, points_rule?, target_round_id?, target_break_category_id?}` -> `BetMarket`
- `PATCH /bet-markets/{market_id}` **(admin)** `{status?}` (only `open<->closed` transitions; `settled` is set by the system)
- `POST /bet-markets/{market_id}/settle` **(admin)** `{manual_outcome?: object}` -> `{settled: bool}`
- `GET /bet-markets/{market_id}/predictions/me` -> `Prediction | null`
- `POST /bet-markets/{market_id}/predictions` `{payload: object}` -> `Prediction`
  (payload shape depends on bet_type -- see below. Rejected with 400 if market isn't `open` or `now > closes_at`.)

`Prediction` shape: `{id, bet_market_id, user_id, payload, status, points_awarded, locked_at, created_at}`
(`status`: `open|locked|settled`)

### Payload shape per bet_type (both request body when creating and what's stored)

- `champion`: `{team_id}`
- `top_n_break`: `{team_ids: number[]}` (ordered guess)
- `top_n_speakers`: `{speaker_ids: number[]}` (ordered guess)
- `round_winner`: `{debate_id, team_id}`
- `head_to_head`: `{team_a_id, team_b_id, predicted_winner_id}`
- `breakout_team`: `{team_id}`
- `best_institution`: `{institution_code}`

## Leaderboard

- `GET /tournaments/{id}/leaderboard` -> `LeaderboardEntry[]` `{user: {id, display_name}, total_points, rank, computed_at}`

## Dashboard (convenience aggregate, public)

- `GET /tournaments/{id}/dashboard` ->
  `{latest_round: Round|null, recent_changes: ChangeEvent[] (last 20), leaderboard_top: LeaderboardEntry[] (top 5),
    my_predictions: Prediction[] (only if authenticated), open_bet_markets: BetMarket[]}`

`ChangeEvent` shape: `{id, entity_type, entity_id, change_type, field_diff, round_id, detected_at}`

## Admin

- `GET /admin/scrape-logs?tournament_id=` **(admin)** -> `ScrapeLog[]` `{id, started_at, finished_at, status, strategy_used, pages_fetched, entities_created, entities_updated, error_message}`
- `GET /admin/users` **(admin)** -> `User[]`
- `PATCH /admin/users/{id}` **(admin)** `{role?, is_active?}` -> `User`

## Conventions

- Pagination: none in v1 (dataset sizes are small -- hundreds of rows per tournament).
- Errors: `{"detail": "message"}` with standard HTTP status codes (400/401/403/404/409/422).
- All timestamps ISO 8601 UTC.
- Swagger/OpenAPI auto-generated by FastAPI at `/docs` and `/openapi.json`.
