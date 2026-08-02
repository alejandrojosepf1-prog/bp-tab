/** Centralized TanStack Query key factory, scoped by tournament id and resource. */

type Id = number | string;

export const queryKeys = {
  tournaments: ["tournaments"] as const,
  tournament: (id: Id) => ["tournaments", id] as const,

  institutions: (tournamentId: Id) => ["tournaments", tournamentId, "institutions"] as const,
  teams: (tournamentId: Id) => ["tournaments", tournamentId, "teams"] as const,
  team: (tournamentId: Id, teamId: Id) => ["tournaments", tournamentId, "teams", teamId] as const,
  speakers: (tournamentId: Id) => ["tournaments", tournamentId, "speakers"] as const,
  adjudicators: (tournamentId: Id) => ["tournaments", tournamentId, "adjudicators"] as const,

  rounds: (tournamentId: Id) => ["tournaments", tournamentId, "rounds"] as const,
  roundDebates: (tournamentId: Id, roundId: Id) =>
    ["tournaments", tournamentId, "rounds", roundId, "debates"] as const,
  debate: (tournamentId: Id, debateId: Id) =>
    ["tournaments", tournamentId, "debates", debateId] as const,

  standings: (tournamentId: Id, params?: Record<string, unknown>) =>
    ["tournaments", tournamentId, "standings", params ?? {}] as const,

  breakCategories: (tournamentId: Id) => ["tournaments", tournamentId, "break-categories"] as const,
  breakPredictions: (tournamentId: Id, categoryId: Id) =>
    ["tournaments", tournamentId, "break-categories", categoryId, "predictions"] as const,
  officialBreak: (tournamentId: Id, categoryId: Id) =>
    ["tournaments", tournamentId, "break-categories", categoryId, "break"] as const,

  betMarkets: (tournamentId: Id) => ["tournaments", tournamentId, "bet-markets"] as const,
  marketBoard: (marketId: Id) => ["bet-markets", marketId, "board"] as const,
  oddsHistory: (marketId: Id) => ["bet-markets", marketId, "odds-history"] as const,
  myPrediction: (marketId: Id) => ["bet-markets", marketId, "predictions", "me"] as const,

  prizeEvents: (tournamentId: Id) => ["tournaments", tournamentId, "prize-events"] as const,
  prizeEvent: (eventId: Id) => ["prize-events", eventId] as const,

  leaderboard: (tournamentId: Id) => ["tournaments", tournamentId, "leaderboard"] as const,
  globalLeaderboard: ["leaderboard", "global"] as const,
  dashboard: (tournamentId: Id) => ["tournaments", tournamentId, "dashboard"] as const,

  me: ["auth", "me"] as const,
  users: ["auth", "users"] as const,
  myTransfers: ["transfers", "me"] as const,
  adminUsers: ["admin", "users"] as const,
  adminScrapeLogs: (tournamentId?: Id) => ["admin", "scrape-logs", tournamentId ?? "all"] as const,
  adminPendingEliminationResults: (tournamentId?: Id) =>
    ["admin", "pending-elimination-results", tournamentId ?? "all"] as const,
  adminGameEconomy: (tournamentId?: Id) =>
    ["admin", "game-economy", tournamentId ?? "all"] as const,
  adminCircuitInstitutions: ["admin", "circuit", "institutions"] as const,
  adminCircuitReviewQueue: ["admin", "circuit", "review-queue"] as const,
  adminUnassignedTeams: ["admin", "circuit", "unassigned-teams"] as const,
};
