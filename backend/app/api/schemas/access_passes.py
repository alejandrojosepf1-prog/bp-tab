import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AccessPassStatus


class AccessPassOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tournament_id: int
    email: str
    phone: str
    full_name: str
    status: AccessPassStatus
    match_hint: dict | None
    user_id: int | None
    reviewed_at: datetime.datetime | None
    created_at: datetime.datetime


class AccessPassRequestIn(BaseModel):
    email: str
    phone: str
    full_name: str = Field(min_length=2, max_length=200)


class ActivateAccessPassIn(BaseModel):
    token: str
    password: str = Field(min_length=8)


class ActivateAccessPassOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
