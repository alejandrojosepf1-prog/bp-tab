/**
 * TypeScript types mirroring docs/api_contract.md exactly (field names must match the
 * FastAPI backend, which is being built in parallel against the same contract).
 */

// ---------- Auth ----------

export type Role = "admin" | "user";

export interface User {
  id: number;
  email: string;
  display_name: string;
  role: Role;
  is_active: boolean;
  // Play-token balance -- goes up and down as bets are placed/won/lost. Never real money;
  // every account starts with a fixed grant (see backend app.models.betting.STARTING_BALANCE).
  balance: number;
  created_at: string;
}

// ---------- Premios ----------

export type PrizeEventType = "manual_award" | "raffle" | "activity_bonus";
export type PrizeEventStatus = "open" | "resolved";

export interface PrizeEntry {
  id: number;
  user: User;
  tickets: number;
  awarded_amount: number | null;
}

export interface PrizeEvent {
  id: number;
  tournament_id: number;
  type: PrizeEventType;
  title: string;
  description: string | null;
  status: PrizeEventStatus;
  /** raffle: {num_winners, prize_per_winner, ticket_cost?} · activity_bonus: {bonus_amount} ·
   * manual_award: {} (cada entry trae su propio monto). */
  config: Record<string, number | undefined>;
  closes_at: string | null;
  resolved_at: string | null;
  rng_seed: string | null;
  entry_count: number;
  total_tickets: number;
}

export interface PrizeEventDetail extends PrizeEvent {
  entries: PrizeEntry[];
}

export interface LoginResponse {
  access_token: string;
  token_type: "bearer";
}

// ---------- Tournaments ----------

export type TournamentStatus =
  | "upcoming"
  | "in_progress"
  | "eliminations"
  | "completed";

export interface Tournament {
  id: number;
  name: string;
  slug: string;
  source_base_url: string;
  source_slug: string;
  status: TournamentStatus;
  api_available: boolean;
  champion_team_id: number | null;
  timezone: string;
  is_active: boolean;
  created_at: string;
  // Resumen para las tarjetas del dashboard (calculado por el backend, no columnas).
  current_round: Round | null;
  teams_count: number;
  open_markets_count: number;
}

// ---------- Participants ----------

export interface Institution {
  id: number;
  code: string;
  name: string;
  region: string | null;
}

export interface Speaker {
  id: number;
  name: string;
  team_id: number | null;
  categories: string[];
}

export interface Team {
  id: number;
  external_id: string;
  name: string;
  emoji: string | null;
  institution: Institution | null;
  speakers: Speaker[];
}

export interface Adjudicator {
  id: number;
  external_id: string;
  name: string;
  institution: Institution | null;
  is_independent: boolean;
  broke: boolean;
}

// ---------- Rounds / Debates ----------

export type RoundStage = "preliminary" | "elimination";
export type RoundStatus = "upcoming" | "in_progress" | "completed" | "draft";

export interface Round {
  id: number;
  seq: number;
  name: string;
  stage: RoundStage;
  status: string;
  /** Espejo de la página pública de mociones del tab. `null` hasta que se libera la moción
   * de esa ronda — no confundir con `Debate.motion_text`, que sale del ballot y por lo tanto
   * recién existe DESPUÉS del debate. */
  motion_text: string | null;
  info_slide: string | null;
}

export type BpPosition = "OG" | "OO" | "CG" | "CO";

export interface DebateTeamSummary {
  team: Team;
  position: BpPosition;
  rank_in_debate: number | null;
  team_points: number | null;
}

/** Summary shape returned by GET /tournaments/{id}/rounds/{round_id}/debates */
export interface DebateSummary {
  id: number;
  room: { name: string } | null;
  status: string;
  teams: DebateTeamSummary[];
}

export interface Debate {
  id: number;
  round: Round;
  room: { name: string } | null;
  status: string;
  motion_text: string | null;
  ballot_source_url: string | null;
  teams: DebateTeamDetail[];
  adjudicators: DebateAdjudicator[];
}

export interface DebateSpeakerScore {
  speaker: Speaker;
  role: string;
  score: number | null;
  is_iron: boolean;
}

export interface DebateTeamDetail extends DebateTeamSummary {
  speaker_points_total: number | null;
  speakers: DebateSpeakerScore[];
}

export interface DebateAdjudicator {
  adjudicator_id: number;
  name: string;
  role: string;
}

// ---------- Standings ----------

export interface TeamStanding {
  team: Team;
  rank: number;
  team_points: number;
  total_speaker_points: number;
  firsts: number;
  seconds: number;
  thirds: number;
  fourths: number;
  debates_played: number;
}

// ---------- Break ----------

export interface BreakCategory {
  id: number;
  name: string;
  slug: string;
  is_general: boolean;
  // Tabbycat doesn't reliably publish "how many teams break" before the break itself happens,
  // so this stays null until an admin sets it by hand (PATCH .../break-categories/{id}) --
  // required before a team_break market can be priced.
  break_size: number | null;
}

export type BreakStatus = "safe" | "alive" | "eliminated";

export interface BreakAssessment {
  team: Team;
  status: BreakStatus;
  probability: number;
  projected_rank: number | null;
  points_needed_for_safety: number | null;
}

export interface BreakEntry {
  team: Team;
  rank: number;
}

// ---------- Betting ----------

export type BetType =
  | "champion"
  | "round_winner"
  | "round_full_call"
  | "top_speaker_position"
  | "team_break"
  | "round_head_to_head"
  | "motion_type"
  // Retired from the admin "create market" UI (see backend app.models.enums.BetType) but kept
  // here since a market created before the redesign could still be open/settled.
  | "top_n_break"
  | "top_n_speakers"
  | "head_to_head"
  | "breakout_team"
  | "best_institution"
  // "Exact pair that advances" folded into round_winner itself (a `team_ids` payload on an
  // elimination debate, alongside the single-team `team_id` shape) -- never created as its own
  // bet_type, kept only for type-safety against the Postgres enum value that still exists.
  | "round_advancing_pair";

export type BetMarketStatus = "open" | "closed" | "settled";

export interface BetMarket {
  id: number;
  bet_type: BetType;
  label: string;
  description: string | null;
  opens_at: string;
  closes_at: string;
  status: BetMarketStatus;
  target_round_id: number | null;
  target_break_category_id: number | null;
  // Suma de todo lo apostado en este mercado ($ ficticios) y cuántos usuarios apostaron.
  // Con pricing pari-mutuel sembrado, el pool SÍ mueve las cuotas en vivo.
  pool_total: number;
  bettors_count: number;
}

export interface MarketBoardOption {
  key: string;
  label: string;
  emoji: string | null;
  stake: number;
  backers: number;
  odds: number;
}

export interface MarketBoard {
  market: BetMarket;
  pool_total: number;
  bettors: number;
  options: MarketBoardOption[];
}

export interface OddsQuote {
  odds: number;
  // Priced only when the quoted payload has a "sub_bet" key and the bet_type supports one --
  // see backend app.services.odds_service.quote_sub_bet_odds. null otherwise.
  sub_bet_odds: number | null;
}

export interface UserSummary {
  id: number;
  display_name: string;
}

export type TransactionType = "transfer_out" | "transfer_in";

export interface Transaction {
  id: number;
  type: TransactionType;
  amount: number;
  balance_after: number;
  note: string | null;
  counterparty_user_id: number | null;
  counterparty_display_name: string | null;
  created_at: string;
}

export type MotionCategory =
  | "policy"
  | "policy_should"
  | "value_judgment"
  | "support_oppose"
  | "regret"
  | "preference"
  | "prediction"
  | "hope"
  | "actor";

export interface RoundMotionCategory {
  round_id: number;
  motion_category: MotionCategory | null;
}

export interface OddsHistoryPoint {
  option_key: string;
  odds: number;
  captured_at: string;
}

export interface OddsHistory {
  points: OddsHistoryPoint[];
}

export type PredictionStatus = "open" | "locked" | "settled";

export interface ChampionPayload {
  team_id: number;
}
export interface TopNBreakPayload {
  team_ids: number[];
}
export interface TopNSpeakersPayload {
  speaker_ids: number[];
}
export interface RoundWinnerPayload {
  debate_id: number;
  team_id: number;
}
export interface HeadToHeadPayload {
  team_a_id: number;
  team_b_id: number;
  predicted_winner_id: number;
}
export interface RoundHeadToHeadSubBet {
  rank_gap: number;
}
export interface RoundHeadToHeadPayload {
  debate_id: number;
  team_a_id: number;
  team_b_id: number;
  predicted_higher_id: number;
  sub_bet?: RoundHeadToHeadSubBet;
}
export interface BreakoutTeamPayload {
  team_id: number;
}
export interface BestInstitutionPayload {
  institution_code: string;
}

export type PredictionPayload =
  | ChampionPayload
  | TopNBreakPayload
  | TopNSpeakersPayload
  | RoundWinnerPayload
  | HeadToHeadPayload
  | RoundHeadToHeadPayload
  | BreakoutTeamPayload
  | BestInstitutionPayload;

export interface Prediction {
  id: number;
  bet_market_id: number;
  user_id: number;
  payload: Record<string, unknown>;
  status: PredictionStatus;
  // Fictional USD staked on this pick, and the decimal odds ("pays 1.85x") locked in at the
  // moment it was placed -- see app.domain.odds. potential_payout = stake_amount * odds.
  stake_amount: number;
  odds: number;
  potential_payout: number;
  // The amount actually credited back once settled (stake_amount * odds if won, 0 if lost),
  // null while still open.
  points_awarded: number | null;
  // Optional modular sub-bet layered on this same prediction (e.g. an exact rank gap) -- see
  // backend app.models.betting.Prediction's sub_bet_* column docstring. sub_bet_status is null
  // when no sub-bet was placed at all.
  sub_bet_odds: number | null;
  sub_bet_status: PredictionStatus | null;
  sub_bet_points_awarded: number | null;
  locked_at: string | null;
  created_at: string;
}

/** Historial de apuestas del usuario (GET /auth/me/predictions). */
export interface MyPrediction {
  id: number;
  bet_market_id: number;
  market_label: string;
  bet_type: string;
  market_status: string;
  tournament_id: number;
  tournament_name: string;
  // Human-readable description of the pick, e.g. "Marce Gómez — 2º" or team/champion name --
  // replaces rendering raw payload fields.
  selection_label: string;
  status: string;
  stake_amount: number;
  odds: number;
  potential_payout: number;
  points_awarded: number | null;
  sub_bet_odds: number | null;
  sub_bet_status: string | null;
  sub_bet_points_awarded: number | null;
  created_at: string;
}

// ---------- Admin: Economía del juego ----------
// No hay casa (ni operador, ni banca, ni comisión) -- todo esto es una vista derivada sobre
// Prediction/User, no un fondo real. Ver backend app.services.game_economy_service.

export interface MarketPayoutSpread {
  market_id: number;
  market_label: string;
  pool_total: number;
  worst_case: number;
  best_case: number;
}

export interface GameEconomy {
  total_staked_open: number;
  total_staked_settled: number;
  total_paid_out: number;
  // total_paid_out - total_staked_settled: positivo = el juego emitió tokens netos (favoritos
  // ganaron más de lo que sus cuotas implicaban); negativo = se destruyeron tokens netos.
  net_token_inflation: number;
  tokens_in_circulation: number;
  open_predictions_count: number;
  settled_predictions_count: number;
  active_bettors_count: number;
  payout_spread: MarketPayoutSpread[];
  payout_spread_worst_case_total: number;
  payout_spread_best_case_total: number;
}

// ---------- Leaderboard ----------

export interface LeaderboardEntry {
  user: { id: number; display_name: string };
  total_points: number;
  rank: number;
  computed_at: string;
}

/** Ranking de apostadores across every tournament (GET /leaderboard/global). */
export interface GlobalLeaderboardEntry {
  user: { id: number; display_name: string };
  total_points: number;
  tournaments_played: number;
  balance: number;
  rank: number;
}

// ---------- Dashboard ----------

export interface ChangeEvent {
  id: number;
  entity_type: string;
  entity_id: number;
  change_type: string;
  field_diff: Record<string, unknown>;
  round_id: number | null;
  detected_at: string;
}

export interface DashboardData {
  current_round: Round | null;
  latest_round: Round | null;
  rounds: Round[];
  recent_changes: ChangeEvent[];
  leaderboard_top: LeaderboardEntry[];
  my_predictions: Prediction[];
  open_bet_markets: BetMarket[];
}

// ---------- Admin ----------

export type ScrapeStatus = "success" | "partial" | "failed" | "running";

export interface ScrapeLog {
  id: number;
  started_at: string;
  finished_at: string | null;
  status: ScrapeStatus;
  strategy_used: string | null;
  pages_fetched: number | null;
  entities_created: number | null;
  entities_updated: number | null;
  error_message: string | null;
}

// Elimination-round debate whose outcome Tabbycat hasn't published yet (e.g. a Grand Final
// never confirmed because it doesn't affect the tab) -- needs a manual result from an admin.
export interface PendingEliminationTeam {
  team_id: number;
  team_name: string;
}

export interface PendingEliminationDebate {
  debate_id: number;
  tournament_id: number;
  round_id: number;
  round_name: string;
  is_final: boolean;
  teams: PendingEliminationTeam[];
}

// ---------- Errors ----------

export interface ApiErrorBody {
  detail: string;
}
