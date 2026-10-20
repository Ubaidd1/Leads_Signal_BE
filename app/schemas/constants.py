"""Allowlisted vocabularies shared by request validation."""

from typing import Literal

# Normalised geography tags. "worldwide" leads match every region filter.
Region = Literal[
    "worldwide",
    "united-states",
    "canada",
    "latam",
    "europe",
    "united-kingdom",
    "pakistan-allowed",
    "international-remote",
]
Currency = Literal["USD", "EUR", "GBP", "CAD", "AUD", "PKR"]
FreshnessDays = Literal[1, 3, 7, 14, 30]
