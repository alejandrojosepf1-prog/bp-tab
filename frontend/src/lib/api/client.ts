import type {
  Adjudicator,
  BetMarket,
  BetType,
  BreakAssessment,
  BreakCategory,
  BreakEntry,
  Debate,
  DebateSummary,
  DashboardData,
  GlobalLeaderboardEntry,
  GameEconomy,
  Institution,
  LeaderboardEntry,
  LoginResponse,
  MarketBoard,
  MotionCategory,
  OddsHistory,
  RoundMotionCategory,
  Transaction,
  UserSummary,
  MyPrediction,
  OddsQuote,
  PendingEliminationDebate,
  Prediction,
  PrizeEvent,
  PrizeEventDetail,
  PrizeEventType,
  Round,
  ScrapeLog,
  Speaker,
  Team,
  TeamStanding,
  Tournament,
  TournamentStatus,
  User,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const TOKEN_KEY = "bp_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const token = getToken();
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1${path}`, {
      ...options,
      headers,
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "No se pudo conectar con el servidor.");
  }

  if (!res.ok) {
    let detail = `Error ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body?.detail) detail = body.detail;
    } catch {
      // ignore parse errors, fall back to generic detail
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) return undefined as T;

  const text = await res.text();
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}

const get = <T>(path: string) => request<T>(path, { method: "GET" });
const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });
const patch = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "PATCH", body: body ? JSON.stringify(body) : undefined });

function qs(params: Record<string, string | number | undefined | null>) {
  const usp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") usp.set(k, String(v));
  }
  const s = usp.toString();
  return s ? `?${s}` : "";
}

export const api = {
  auth: {
    register: (data: { email: string; password: string; display_name: string }) =>
      post<User>("/auth/register", data),
    login: (data: { email: string; password: string }) =>
      post<LoginResponse>("/auth/login", data),
    me: () => get<User>("/auth/me"),
    myPredictions: () => get<MyPrediction[]>("/auth/me/predictions"),
    users: () => get<UserSummary[]>("/auth/users"),
  },

  transfers: {
    create: (data: { recipient_id: number; amount: number; note?: string }) =>
      post<{ sent: Transaction }>("/transfers", data),
    myTransfers: () => get<Transaction[]>("/transfers/me"),
  },

  tournaments: {
    list: () => get<Tournament[]>("/tournaments"),
    get: (id: number | string) => get<Tournament>(`/tournaments/${id}`),
    create: (data: { name: string; tab_url: string; timezone: string }) =>
      post<Tournament>("/tournaments", data),
    update: (
      id: number | string,
      data: Partial<{ name: string; tab_url: string; is_active: boolean }>
    ) => patch<Tournament>(`/tournaments/${id}`, data),
    scrape: (id: number | string) =>
      post<{ status: "queued" }>(`/tournaments/${id}/scrape`),
  },

  institutions: {
    list: (tournamentId: number | string) =>
      get<Institution[]>(`/tournaments/${tournamentId}/institutions`),
  },

  teams: {
    list: (tournamentId: number | string) =>
      get<Team[]>(`/tournaments/${tournamentId}/teams`),
    get: (tournamentId: number | string, teamId: number | string) =>
      get<Team>(`/tournaments/${tournamentId}/teams/${teamId}`),
  },

  speakers: {
    list: (tournamentId: number | string) =>
      get<Speaker[]>(`/tournaments/${tournamentId}/speakers`),
  },

  adjudicators: {
    list: (tournamentId: number | string) =>
      get<Adjudicator[]>(`/tournaments/${tournamentId}/adjudicators`),
  },

  rounds: {
    list: (tournamentId: number | string) =>
      get<Round[]>(`/tournaments/${tournamentId}/rounds`),
    debates: (tournamentId: number | string, roundId: number | string) =>
      get<DebateSummary[]>(`/tournaments/${tournamentId}/rounds/${roundId}/debates`),
  },

  debates: {
    get: (tournamentId: number | string, debateId: number | string) =>
      get<Debate>(`/tournaments/${tournamentId}/debates/${debateId}`),
  },

  standings: {
    list: (
      tournamentId: number | string,
      params?: { break_category_id?: number; as_of_round_seq?: number }
    ) =>
      get<TeamStanding[]>(
        `/tournaments/${tournamentId}/standings${qs({
          break_category_id: params?.break_category_id,
          as_of_round_seq: params?.as_of_round_seq,
        })}`
      ),
  },

  breakCategories: {
    list: (tournamentId: number | string) =>
      get<BreakCategory[]>(`/tournaments/${tournamentId}/break-categories`),
    predictions: (tournamentId: number | string, categoryId: number | string) =>
      get<BreakAssessment[]>(
        `/tournaments/${tournamentId}/break-categories/${categoryId}/predictions`
      ),
    officialBreak: (tournamentId: number | string, categoryId: number | string) =>
      get<BreakEntry[]>(
        `/tournaments/${tournamentId}/break-categories/${categoryId}/break`
      ),
    setBreakSize: (
      tournamentId: number | string,
      categoryId: number | string,
      breakSize: number
    ) =>
      patch<BreakCategory>(
        `/tournaments/${tournamentId}/break-categories/${categoryId}`,
        { break_size: breakSize }
      ),
  },

  betMarkets: {
    list: (tournamentId: number | string) =>
      get<BetMarket[]>(`/tournaments/${tournamentId}/bet-markets`),
    create: (
      tournamentId: number | string,
      data: {
        bet_type: BetType;
        label: string;
        description?: string;
        opens_at: string;
        closes_at: string;
        points_rule?: object;
        target_round_id?: number;
        target_break_category_id?: number;
      }
    ) => post<BetMarket>(`/tournaments/${tournamentId}/bet-markets`, data),
    update: (
      marketId: number | string,
      data: { status?: "open" | "closed"; closes_at?: string }
    ) => patch<BetMarket>(`/bet-markets/${marketId}`, data),
    settle: (marketId: number | string, data?: { manual_outcome?: object }) =>
      post<{ settled: boolean }>(`/bet-markets/${marketId}/settle`, data ?? {}),
    board: (marketId: number | string) =>
      get<MarketBoard>(`/bet-markets/${marketId}/board`),
    oddsHistory: (marketId: number | string) =>
      get<OddsHistory>(`/bet-markets/${marketId}/odds-history`),
    // A user can hold one OPEN prediction PER entity within a market (one per debate/slot/team),
    // not one per market -- see backend app.services.betting_service._entity_key.
    myPredictions: (marketId: number | string) =>
      get<Prediction[]>(`/bet-markets/${marketId}/predictions/me`),
    createPrediction: (marketId: number | string, payload: object, stakeAmount: number) =>
      post<Prediction>(`/bet-markets/${marketId}/predictions`, {
        payload,
        stake_amount: stakeAmount,
      }),
    quoteOdds: (marketId: number | string, payload: object) =>
      post<OddsQuote>(`/bet-markets/${marketId}/quote`, { payload }),
  },

  prizeEvents: {
    list: (tournamentId: number | string) =>
      get<PrizeEvent[]>(`/tournaments/${tournamentId}/prize-events`),
    get: (eventId: number | string) => get<PrizeEventDetail>(`/prize-events/${eventId}`),
    create: (
      tournamentId: number | string,
      data: {
        type: PrizeEventType;
        title: string;
        description?: string;
        config?: object;
        closes_at?: string;
      }
    ) => post<PrizeEvent>(`/tournaments/${tournamentId}/prize-events`, data),
    queueManualAward: (eventId: number | string, data: { user_id: number; amount: number }) =>
      post<PrizeEvent>(`/prize-events/${eventId}/manual-awards`, data),
    enter: (eventId: number | string, tickets: number) =>
      post<PrizeEvent>(`/prize-events/${eventId}/enter`, { tickets }),
    resolve: (eventId: number | string) =>
      post<PrizeEventDetail>(`/prize-events/${eventId}/resolve`),
  },

  leaderboard: {
    list: (tournamentId: number | string) =>
      get<LeaderboardEntry[]>(`/tournaments/${tournamentId}/leaderboard`),
    global: () => get<GlobalLeaderboardEntry[]>("/leaderboard/global"),
  },

  dashboard: {
    get: (tournamentId: number | string) =>
      get<DashboardData>(`/tournaments/${tournamentId}/dashboard`),
  },

  admin: {
    scrapeLogs: (tournamentId?: number | string) =>
      get<ScrapeLog[]>(`/admin/scrape-logs${qs({ tournament_id: tournamentId })}`),
    users: () => get<User[]>("/admin/users"),
    updateUser: (
      id: number | string,
      data: Partial<{ role: "admin" | "user"; is_active: boolean }>
    ) => patch<User>(`/admin/users/${id}`, data),
    pendingEliminationResults: (tournamentId?: number | string) =>
      get<PendingEliminationDebate[]>(
        `/admin/pending-elimination-results${qs({ tournament_id: tournamentId })}`
      ),
    submitManualResult: (
      debateId: number | string,
      data: { champion_team_id: number } | { advancing_team_ids: number[] }
    ) => post<{ status: string }>(`/admin/debates/${debateId}/manual-result`, data),
    gameEconomy: (tournamentId?: number | string) =>
      get<GameEconomy>(`/admin/game-economy${qs({ tournament_id: tournamentId })}`),
    // Ground truth for the motion_type market -- deliberately admin-only, never on the public
    // round schema (it would leak the answer before the motion is revealed).
    setRoundMotionCategory: (roundId: number | string, motionCategory: MotionCategory | null) =>
      patch<RoundMotionCategory>(`/admin/rounds/${roundId}/motion-category`, {
        motion_category: motionCategory,
      }),
  },
};

export type { TournamentStatus };
