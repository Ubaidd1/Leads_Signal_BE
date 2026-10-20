from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

T = TypeVar("T")


class CamelModel(BaseModel):
    """API payloads use camelCase to match the existing frontend objects."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class RequestModel(CamelModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Page(CamelModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    total_pages: int


class Message(CamelModel):
    message: str
