import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import AccessPassStatus
from app.models.mixins import TimestampMixin, TournamentScopedMixin


class AccessPass(Base, TournamentScopedMixin, TimestampMixin):
    """A request for betting access to ONE tournament (CNADE 2026 Roadmap Pieza 4). Public,
    no-login submission -- see app.services.access_pass_service.submit_access_pass_request,
    which upserts by (tournament_id, email) so resubmitting edits the same request instead of
    piling up duplicates.

    Approving is a two-effect action (see access_pass_service.approve_access_pass): it finds or
    creates the persistent `User` account for `email` (a returning user's account is reused,
    per the product decision that the account persists but access is re-approved every
    tournament) AND grants that user access to THIS tournament specifically. There is
    deliberately no separate "tournament access" table -- an APPROVED row for
    (tournament_id, user_id) *is* the grant.

    This does NOT by itself decide whether the user can bet in this tournament's markets --
    that also depends on whether they currently match a scraped participant (debater/judge),
    checked live at bet time against `full_name`, never cached here. See
    access_pass_service.is_participant_of_tournament and betting_service.place_prediction.
    """

    __tablename__ = "access_passes"
    __table_args__ = (
        UniqueConstraint("tournament_id", "email", name="uq_access_passes_tournament_email"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # Collected, never verified -- no SMS infra, same pragmatism as the rest of this platform's
    # "public" surfaces (see Pieza 4 roadmap note).
    phone: Mapped[str] = mapped_column(String(50), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[AccessPassStatus] = mapped_column(
        default=AccessPassStatus.PENDING, nullable=False
    )
    # {"matched": bool, "kind": "speaker"|"adjudicator", "id": int, "name": str} or None --
    # an admin-facing hint computed once at submission time (see
    # access_pass_service.submit_access_pass_request). Purely informational: never auto-approves
    # or auto-rejects, and never used for the live betting-time block (that re-checks fresh).
    match_hint: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Set at approval -- the persistent account this pass grants tournament access to.
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reviewed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user = relationship("User", foreign_keys=[user_id])
    reviewed_by = relationship("User", foreign_keys=[reviewed_by_id])
