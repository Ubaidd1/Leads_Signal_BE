from enum import StrEnum

from sqlalchemy import Enum


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class HiringIntent(StrEnum):
    STRONG = "strong"
    MEDIUM = "medium"
    LOW = "low"


class VerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    HIGH_CONFIDENCE = "high_confidence"


class LeadStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


def str_enum(enum_cls: type[StrEnum], name: str) -> Enum:
    """Store enum values as VARCHAR + CHECK constraint (easier to evolve than native PG enums)."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda cls: [member.value for member in cls],
    )
