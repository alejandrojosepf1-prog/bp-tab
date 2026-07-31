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

- `GET /tournaments/{id}/rounds` -> `Round[]`
  `{id, seq, name, stage, status, motion_text, info_slide}` (`stage`:
  `preliminary|elimination`; `status`: `draft|released|completed` -- `draft` means not yet
  drawn, `released` means drawn/in progress with no judged debate yet, `completed` means at
  least one debate in the round has a judged outcome). `motion_text`/`info_slide` mirror the
  tournament's public `/motions/` page and are `null` until that round's motion is released --
  distinct from the per-debate `motion_text` on debate detail below, which comes off the ballot
  and therefore only exists once the debate has already been judged.
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

**Bet types offered by the admin panel (`CREATABLE_BET_TYPES` in `app.services.betting_service`):**
`champion | round_winner | round_full_call | top_speaker_position | team_break |
round_head_to_head`. The older
`top_n_break | top_n_speakers | head_to_head | breakout_team | best_institution |
round_advancing_pair` remain valid `BetType` enum members (a market/prediction of one of these
created before this list existed still prices and settles exactly as before) but are no longer
offered for NEW markets. `round_advancing_pair`'s proposition ("the exact pair that advances")
was folded into `round_winner` itself -- see below -- rather than staying a separate bet_type.

- `champion`: `{team_id}`. **Only creatable while `Tournament.status == "upcoming"`** (400
  otherwise) -- `validate_market_creation` enforces this at creation, and
  `auto_close_pretournament_markets` (called every scrape cycle, right after
  `refresh_tournament_status`) force-closes any still-OPEN champion market the moment the
  tournament leaves `upcoming`.
- `round_winner`: `{debate_id, team_id}` (who wins one specific debate). Requires
  `target_round_id` at creation (400 otherwise); the debate named in a payload must belong to
  that round (422 otherwise).
  On an ELIMINATION round this means "does this team ADVANCE", and is priced as a top-N market
  accordingly: BP out-rounds send 2 of the 4 teams through (1 in a single-room grand final), so
  the prior is `app.domain.odds.top_n_probabilities` and the four quoted odds imply a total
  probability of ~2.0, not 1.0. Pricing it as a one-winner market -- which is what happened
  before -- made backing all four teams in a room a risk-free double-up. Elimination rounds also
  blend against a much thinner `ELIMINATION_SEED`, so the crowd's money overrides the model far
  faster than in a preliminary round (fewer rooms, more concentrated action).
  A single-team pick is capped at **2 independent picks per debate** per user (each team gets
  its own `entity_key`, `debate:{id}:team:{team_id}` -- a 3rd distinct team in the same debate
  gets a 400 `TooManyPicksError`; re-picking one of the 2 already held is still just an edit).
  This lets a bettor hedge two teams in the same room independently -- if one doesn't advance
  the other still pays.
  On an ELIMINATION round with exactly 2 advancing slots (i.e. not the single-room grand final),
  `round_winner` ALSO accepts an exact-pair payload: `{debate_id, team_ids: [2 team ids, order
  doesn't matter]}`, betting that BOTH named teams advance together -- harder than either
  single-team pick, so it pays more. Priced via `app.domain.odds.pair_top_two_probability` (sum
  of both Plackett-Luce orderings of the pair occupying the top 2), blended against its own
  compartment of the debate's pool with `ELIMINATION_SEED`. A pair payload gets one `entity_key`
  for the whole room (`debate:{id}:pair:{a}:{b}`), not the 2-per-debate cap above. Settles
  against the same `advancing_team_ids` outcome the single-team elimination case uses -- exact
  set match, 2 of 2. Quoting a pair on a debate with only 1 advancing slot, or on a preliminary
  round, 400s.
  The optional speaker-points sub-bet (below) is **rejected on an elimination-round debate**
  (400) -- CalicoTab never publishes per-speaker scores for an out-round, so the sub-bet could
  never resolve there.
- `round_full_call`: `{debate_id, team_ids: [4 team ids, predicted 1st->4th order]}` -- the
  FULL finishing order of one debate (BP debates always have exactly 4 teams), not just the
  winner. Same `target_round_id` requirement/validation as `round_winner`. Priced via
  Plackett-Luce `sequence_probability` restricted to the debate's 4 teams.
  **Cannot be created against an elimination round** (400): Tabbycat only records
  advanced/not-advanced for an out-round, so `rank_in_debate` stays NULL forever and such a
  market could take bets it would never be able to settle. Same restriction applies to
  `round_head_to_head`.
- `top_speaker_position`: `{speaker_id, position}` (`position`: `1|2|3`) -- does this speaker
  finish in EXACTLY this slot of the final top-3 speaker ranking (not "top 3 overall"). Priced
  via `app.domain.odds.positional_probabilities`, a marginal Plackett-Luce probability; each
  position is its own independent pari-mutuel compartment (position 1/2/3 don't share a pool).
- `team_break`: `{team_id}`. Requires `target_break_category_id` at creation (400 otherwise).
  An INDEPENDENT, non-mutually-exclusive proposition (several teams break simultaneously) --
  unlike every other bet type, priced directly from that team's own break probability
  (`app.services.break_service.team_break_probability`, reusing the Break Predictor simulation
  once a round is judged, else a naive `break_size/num_teams` base rate) with **no pari-mutuel
  pool blending**: pool-blending assumes competing candidates' priors sum to 1 across a shared
  compartment, which holds for "exactly one winner" markets but would be wrong here.

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
  (`bet_type`: see the creatable set above; a legacy market can also carry
  `top_n_break|top_n_speakers|head_to_head|breakout_team|best_institution|round_advancing_pair`)
  (`status`: `open|closed|settled`)
- `POST /tournaments/{id}/bet-markets` **(admin)** `{bet_type, label, description?, opens_at, closes_at, points_rule?, target_round_id?, target_break_category_id?}` -> `BetMarket`
  (validated by `validate_market_creation` per bet_type -- see the creatable set above for what
  each one requires; `points_rule` is now only used by the legacy `breakout_team`, e.g.
  `{"odds": 4.0}` -- every creatable bet_type is priced automatically)
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
- `round_winner`: `{debate_id, team_id}` (single-team pick), or on an elimination round with 2
  advancing slots, `{debate_id, team_ids: [2 team ids]}` (exact-pair pick -- see above)
- `round_full_call`: `{debate_id, team_ids: number[]}` (exactly the debate's 4 teams, 1st->4th)
- `top_speaker_position`: `{speaker_id, position}` (`position`: `1|2|3`)
- `team_break`: `{team_id}`
- Legacy (still valid on an existing market/prediction, not creatable anymore): `top_n_break`
  `{team_ids: number[]}`, `top_n_speakers` `{speaker_ids: number[]}`, `head_to_head`
  `{team_a_id, team_b_id, predicted_winner_id}`, `breakout_team` `{team_id}`, `best_institution`
  `{institution_code}`, `round_advancing_pair` `{debate_id, team_ids: number[]}` (same shape a
  `round_winner` exact-pair pick now uses)

## Prizes

Admin-run token giveaways independent of betting outcomes -- see `app.services.prize_service`
for the mechanics behind each `type`. Lifecycle is one-way: `open` -> `resolved`, never back.

- `GET /tournaments/{id}/prize-events` -> `PrizeEvent[]` (public)
- `POST /tournaments/{id}/prize-events` **(admin)**
  `{type: manual_award|raffle|activity_bonus, title, description?, config?, closes_at?}` ->
  `PrizeEvent`. `config` shape by type: `raffle` `{num_winners, prize_per_winner, ticket_cost?}`
  (`ticket_cost` omitted/0 = free entry); `activity_bonus` `{bonus_amount}`; `manual_award` `{}`
  (each entry carries its own amount instead of a shared config).
- `GET /prize-events/{id}` -> `PrizeEvent & {entries: PrizeEntry[]}` (public)
- `POST /prize-events/{id}/manual-awards` **(admin)** `{user_id, amount}` -> `PrizeEntry`.
  `manual_award` events only (400 otherwise). Queues an award without crediting anything yet --
  re-calling for the same user REPLACES the queued amount rather than stacking. Nothing is
  credited until `/resolve`.
- `POST /prize-events/{id}/enter` `{tickets}` -> `PrizeEntry`. `raffle` events only (400
  otherwise), requires auth. Re-entering tops up to the new ticket total and only charges the
  DIFFERENCE against balance (400 `InsufficientBalanceError` if it can't cover that). Free if
  the event's `ticket_cost` is unset.
- `POST /prize-events/{id}/resolve` **(admin)** -> `PrizeEvent & {entries: PrizeEntry[]}`. 400 if
  already resolved. Per type:
  - `manual_award`: credits every queued entry's amount.
  - `raffle`: draws `num_winners` winners weighted by ticket count (no replacement at the user
    level -- one user can win at most once even with many tickets), using a seed persisted on
    `rng_seed` so the draw is independently reproducible. Every entry gets `awarded_amount` set
    (the prize for winners, `0` for everyone else), so "did I win" never needs a separate query.
  - `activity_bonus`: computes qualifying users itself at resolve time (nobody "enters" this
    type) -- anyone who placed a prediction on this tournament between the event's `created_at`
    and `closes_at` gets a `PrizeEntry` created with the flat `bonus_amount`.

`PrizeEvent` shape: `{id, tournament_id, type, title, description, status, config, closes_at,
resolved_at, rng_seed, entry_count, total_tickets}` (`entry_count`/`total_tickets` computed by
the router, like `BetMarket.pool_total`). `PrizeEntry` shape: `{id, user, tickets,
awarded_amount}` (`awarded_amount` is `null` until resolved).

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
