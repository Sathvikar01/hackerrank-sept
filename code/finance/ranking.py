from __future__ import annotations

from datetime import date
from typing import Iterable, Sequence

from .planning import PlanCandidate

FAR_FUTURE = date.max


def plan_rank_key(candidate: PlanCandidate) -> tuple:
    changes_preference = 0 if not candidate.changes else 1
    start = candidate.start_date or FAR_FUTURE
    payments = len(candidate.entries)
    option_id = candidate.option_id or ""
    return (
        changes_preference,
        candidate.total_paid,
        start,
        payments,
        option_id,
    )


def rank_candidates(candidates: Iterable[PlanCandidate]) -> list[PlanCandidate]:
    eligible = [candidate for candidate in candidates if candidate.eligible]
    return sorted(eligible, key=plan_rank_key)
