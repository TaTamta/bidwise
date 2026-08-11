# state.py — one case file every desk reads and writes.
# `audit` is R8's trail: each node appends, and it's free because the state
# was designed right.

from typing import TypedDict, Optional


class CarState(TypedDict, total=False):
    # input
    listing: dict

    # rule desks
    filters: dict
    landed: dict
    budget: dict
    flags: dict
    check: dict
    route: str
    route_reason: str

    # judgment desks
    estimate: dict

    # the negotiation
    transcript: list
    rounds: int
    verdict: Optional[str]
    ended_by: Optional[str]
    bid_ceiling_usd: Optional[float]
    is_recommendation: bool

    # outcome
    alive: bool
    kill_tier: Optional[str]      # "silent" | "explain" | None
    kill_reason: Optional[str]
    score: Optional[float]
    score_parts: dict

    audit: list