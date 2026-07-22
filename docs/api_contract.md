# Claim REST API Contract (v1)

Base path: `/api/v1`. All responses JSON. Auth via `Authorization: Bearer <JWT>`.
Roles: `admin`, `user`. Endpoints marked **(admin)** require `role=admin`; everything else
just requires a valid logged-in user unless marked **(public)**.

This is the single source of truth both the backend (FastAPI implementation) and the frontend
(Next.js consumer) build against, so they stay in sync despite being built in parallel.

## Auth

- `POST /auth/register` `{email, password, display_name}` -> `User` (the very first account ever
  registered on a fresh database becomes `admin` automatically -- there is no other way to mint
  the first admin without hand-editing the database; every registration after that gets `user`)
- `POST /auth/login` `{email, password}` -> `{access_token, token_type: "bearer"}`
- `GET /auth/me` -> `User`
- `GET /auth/me/predictions` -> `MyPredictionOut[]` (this user's full bet history across every
  tournament, newest first)

`User` shape: `{id, email, display_name, role, is_active, balance, created_at}`
(`balance`: fictional USD wallet, global across every tournament -- see Betting section below)

`MyPredictionOut` shape: `{id, bet_market_id, market_label, bet_type, market_status,
tournament_id, tournament_name, status, stake_amount, odds, potential_payout, points_awarded,
created_at}` -- a `Prediction` joined with just enough market/tournament context to render a
history list without extra round-trips.

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

`Tournament` shape: `{id, name, slug, source_base_url, source_slug, status, api_available,
champion_team_id, timezone, is_active, created_at, current_round: Round|null, teams_count,
open_markets_count}`
`status` enum: `upcoming | in_progress | break_pending | eliminations | completed`

`current_round`/`teams_count`/`open_markets_count` are computed by the router on every
list/get call (not columns) so the dashboard's tournament cards can show "ronda actual", team
count, and open-market count without a round-trip per tournament. `current_round` is the
highest-seq `released` round (a published draw still being debated) if one exists, else the
highest-seq `completed` round, else the tournament's first round -- see
`app.services.tournament_service.get_current_round`. This is deliberately NOT just "the
highest-seq round": the results navigation on the source tab only ever lists a round once its
results page exists, so the round currently being debated (drawn, not yet judged) would
otherwise be invisible everywhere in the app.

## Participants (all scoped under a tournament, all public/read-only)

- `GET /tournaments/{id}/institutions` -> `Institution[]` `{id, code, name, region}`
- `GET /tournaments/{id}/teams` -> `Team[]` `{id, external_id, name, emoji, institution: Institution|null, speakers: Speaker[]}`
- `GET /tournaments/{id}/teams/{team_id}` -> `Team` (same shape, single)
- `GET /tournaments/{id}/speakers` -> `Speaker[]` `{id, name, team_id, categories: string[]}`
- `GET /tournaments/{id}/adjudicators` -> `Adjudicator[]` `{id, external_id, name, institution: Institution|null, is_independent, broke}`

## Rounds / Debates / Results (public/read-only)

- `GET /tournaments/{id}/rounds` -> `Round[]` `{id, seq, name, stage, status}` (`stage`:
  `preliminary|elimination`; `status`: `draft|released|completed` -- `draft` means not yet
  drawn, `released` means drawn/in progress with no judged debate yet, `completed` means at
  least one debate in the round has a judged outcome)
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

**Unit convention:** every dollar amount below (`User.balance`, `Prediction.stake_amount`,
`potential_payout`, `points_awarded`, `LeaderboardEntry.total_points`, `BetMarket.pool_total`)
is denominated in **fictional USD** ("dólares apostados"), not abstract points -- there is no
real money anywhere in this platform, but the friend group's score is expressed and displayed
as dollars (e.g. render `points_awarded` as `"$100"`, not `"100 pts"`). The frontend should
format all of these with a `$` prefix.

**Odds model:** pari-mutuel-with-seed, NOT fixed/bookmaker odds. `POST .../quote` prices a
candidate pick by blending a prior probability (from that team's/speaker's/institution's
current strength -- see `app.domain.odds` and `app.services.odds_service`) with whatever's
already staked on OPEN predictions in that market/compartment; with an empty pool the price is
exactly the prior, and as real stakes accumulate the crowd's money takes over. A 7% house
margin is applied and prices are clamped to `[1.05, 20.0]`. `POST .../predictions` re-prices
the same way and locks the resulting `odds` onto the `Prediction` row at that moment; a later
swing in the market's pool or in team strength never changes an already-placed bet's payout.
`pool_total`/`bettors_count` DO feed back into everyone's live-quoted odds (unlike a flavor-only
stat) -- they're just not retroactive for bets already placed.

- `GET /tournaments/{id}/bet-markets` -> `BetMarket[]`
  `{id, bet_type, label, description, opens_at, closes_at, status, target_round_id, target_break_category_id, pool_total, bettors_count}`
  (`bet_type`: `champion|top_n_break|top_n_speakers|round_winner|head_to_head|breakout_team|best_institution`)
  (`status`: `open|closed|settled`)
- `POST /tournaments/{id}/bet-markets` **(admin)** `{bet_type, label, description?, opens_at, closes_at, points_rule?, target_round_id?, target_break_category_id?}` -> `BetMarket`
  (`points_rule` is now only used by `breakout_team`, e.g. `{"odds": 4.0}` -- every other bet_type is priced automatically)
- `PATCH /bet-markets/{market_id}` **(admin)** `{status?}` (only `open<->closed` transitions; `settled` is set by the system)
- `POST /bet-markets/{market_id}/settle` **(admin)** `{manual_outcome?: object}` -> `{settled: bool}`
- `GET /bet-markets/{market_id}/board` **(public)** -> `MarketBoardOut`
  `{market: BetMarket, pool_total, bettors, options: MarketBoardOption[]}` where
  `MarketBoardOption` is `{key, label, emoji, stake, backers, odds}` -- one row per candidate
  (or per distinct staked payload, for bet types with no enumerable field like `head_to_head`),
  each priced through the same live pari-mutuel math `quote` uses. This is what the "Mercados
  abiertos" board renders: pool, apostadores, cuota y pago por opción, sin round-trips extra.
- `POST /bet-markets/{market_id}/quote` `{payload: object}` -> `{odds: number}` (live preview, no side effects)
- `GET /bet-markets/{market_id}/predictions/me` -> `Prediction | null`
- `POST /bet-markets/{market_id}/predictions` `{payload: object, stake_amount: number}` -> `Prediction`
  (payload shape depends on bet_type -- see below. Rejected with 400 if market isn't `open`,
  `now > closes_at`, the market can't be priced yet (no standings/scores), or the user's balance
  can't cover `stake_amount`; 422 if the payload names a team/speaker/institution outside the
  currently-tracked field. Re-submitting on the same market refunds the prior stake before
  charging the new one, rather than creating a second prediction.)

`Prediction` shape: `{id, bet_market_id, user_id, payload, status, stake_amount, odds, potential_payout, points_awarded, locked_at, created_at}`
(`status`: `open|locked|settled`; `potential_payout = stake_amount * odds`; `points_awarded` is
the amount actually credited back once settled -- `potential_payout` if won, `0` if lost, `null`
while still open)

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
  `{current_round: Round|null, latest_round: Round|null (alias of current_round, kept for older
    consumers), rounds: Round[] (every round, ascending seq), recent_changes: ChangeEvent[] (last 20),
    leaderboard_top: LeaderboardEntry[] (top 5), my_predictions: Prediction[] (only if authenticated),
    open_bet_markets: BetMarket[]}`

`current_round` uses the same "round actually in progress" logic as `Tournament.current_round`
(see `app.services.tournament_service.get_current_round`) -- NOT simply the highest-seq round.

`ChangeEvent` shape: `{id, entity_type, entity_id, change_type, field_diff, round_id, detected_at}`

## Admin

- `GET /admin/scrape-logs?tournament_id=` **(admin)** -> `ScrapeLog[]` `{id, started_at, finished_at, status, strategy_used, pages_fetched, entities_created, entities_updated, error_message}`
- `GET /admin/users` **(admin)** -> `User[]`
- `PATCH /admin/users/{id}` **(admin)** `{role?, is_active?}` -> `User`
- `GET /admin/pending-elimination-results?tournament_id=` **(admin)** -> `PendingEliminationDebateOut[]`
  `{debate_id, tournament_id, round_id, round_name, is_final, teams: {team_id, team_name}[]}` --
  elimination-round debates whose draw is known but whose result the source tab never published
  (common for the Grand Final).
- `POST /admin/debates/{debate_id}/manual-result` **(admin)**
  `{champion_team_id}` (final) or `{advancing_team_ids: number[]}` (non-final) -> `{status: "ok"}`

## Conventions

- Pagination: none in v1 (dataset sizes are small -- hundreds of rows per tournament).
- Errors: `{"detail": "message"}` with standard HTTP status codes (400/401/403/404/409/422).
- All timestamps ISO 8601 UTC.
- Swagger/OpenAPI auto-generated by FastAPI at `/docs` and `/openapi.json`.
