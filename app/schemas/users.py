from datetime import datetime
from typing import Annotated
from zoneinfo import available_timezones

from pydantic import EmailStr, Field, field_validator

from app.schemas.common import CamelModel, RequestModel
from app.schemas.constants import FreshnessDays, Region

_TIMEZONES = available_timezones()
ShortText = Annotated[str, Field(min_length=1, max_length=64)]


class ProfileUpdate(RequestModel):
    full_name: Annotated[str | None, Field(min_length=1, max_length=200)] = None
    job_title: Annotated[str | None, Field(max_length=200)] = None
    timezone: str | None = None
    email: EmailStr | None = None
    # Required when changing email.
    current_password: Annotated[str | None, Field(max_length=256)] = None

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value):
        if value is not None and value not in _TIMEZONES:
            raise ValueError("Unknown IANA timezone")
        return value


class ChangePasswordRequest(RequestModel):
    current_password: Annotated[str, Field(min_length=1, max_length=256)]
    new_password: Annotated[str, Field(min_length=1, max_length=256)]


class OnboardingPreferences(RequestModel):
    services: Annotated[list[ShortText], Field(max_length=20)] = []
    technologies: Annotated[list[ShortText], Field(max_length=50)] = []
    region: Region = "worldwide"
    freshness_days: FreshnessDays = 7


class OnboardingOut(CamelModel):
    preferences: OnboardingPreferences | None
    completed_at: datetime | None
