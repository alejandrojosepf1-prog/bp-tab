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
  // Fictional USD bankroll -- goes up and down as bets are placed/won/lost. No real money.
  balance: number;
  created_at: string;
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
  break_size: number;
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
  | "top_n_break"
  | "top_n_speakers"
  | "round_winner"
  | "head_to_head"
  | "breakout_team"
  | "best_institution";

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
  status: string;
  stake_amount: number;
  odds: number;
  potential_payout: number;
  points_awarded: number | null;
  created_at: string;
}

// ---------- Leaderboard ----------

export interface LeaderboardEntry {
  user: { id: number; display_name: string };
  total_points: number;
  rank: number;
  computed_at: string;
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
