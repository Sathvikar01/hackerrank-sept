import unittest
from datetime import date, timedelta
from decimal import Decimal

from finance.contracts import ChangeAction, PlanEntry
from finance.planning import PlanCandidate
from finance.ranking import rank_candidates

D = Decimal


def make_candidate(
    method: str,
    start: date,
    amount: str,
    payments: int = 1,
    *,
    changes=(),
    option_id=None,
    safe: bool = True,
    completes: bool = True,
) -> PlanCandidate:
    entries = tuple(
        PlanEntry(start + timedelta(days=30 * index), D(amount))
        for index in range(payments)
    )
    return PlanCandidate(
        method=method,
        status="affordable_with_plan",
        entries=entries,
        changes=changes,
        option_id=option_id,
        safe=safe,
        rejected=(),
        forecast=None,
        completes_by_deadline=completes,
    )


class RankingTests(unittest.TestCase):
    def test_no_spending_changes_wins_first(self):
        change_free = make_candidate("full_payment", date(2026, 1, 1), "5000")
        with_change = make_candidate(
            "full_payment", date(2026, 1, 1), "4000",
            changes=(ChangeAction.stop("event_01"),))
        ranked = rank_candidates([with_change, change_free])
        self.assertEqual(ranked[0], change_free)

    def test_lowest_total_paid_wins_before_start_date(self):
        cheaper = make_candidate("installments", date(2026, 1, 10), "4000")
        costlier = make_candidate("installments", date(2026, 1, 1), "4500")
        ranked = rank_candidates([costlier, cheaper])
        self.assertEqual(ranked[0], cheaper)

    def test_earlier_start_wins_when_total_is_equal(self):
        later = make_candidate("full_payment", date(2026, 1, 10), "5000")
        earlier = make_candidate("full_payment", date(2026, 1, 1), "5000")
        ranked = rank_candidates([later, earlier])
        self.assertEqual(ranked[0], earlier)

    def test_fewer_payments_wins_when_earlier_criteria_tie(self):
        many = make_candidate("installments", date(2026, 1, 1), "1000", payments=3)
        few = make_candidate("installments", date(2026, 1, 1), "3000", payments=1)
        ranked = rank_candidates([many, few])
        self.assertEqual(ranked[0], few)

    def test_lowest_option_id_breaks_remaining_ties(self):
        second = make_candidate(
            "installments", date(2026, 1, 1), "1000", payments=3,
            option_id="payment_option_02")
        first = make_candidate(
            "installments", date(2026, 1, 1), "1000", payments=3,
            option_id="payment_option_01")
        ranked = rank_candidates([second, first])
        self.assertEqual(ranked[0].option_id, "payment_option_01")

    def test_ineligible_candidates_are_excluded(self):
        unsafe = make_candidate("full_payment", date(2026, 1, 1), "5000", safe=False)
        late = make_candidate("full_payment", date(2026, 1, 1), "5000", completes=False)
        good = make_candidate("full_payment", date(2026, 1, 1), "5000")
        ranked = rank_candidates([unsafe, late, good])
        self.assertEqual(ranked, [good])

    def test_wait_loses_to_an_immediate_full_payment(self):
        wait = make_candidate("wait", date(2026, 1, 20), "5000")
        full = make_candidate("full_payment", date(2026, 1, 1), "5000")
        ranked = rank_candidates([wait, full])
        self.assertEqual(ranked[0].method, "full_payment")

    def test_ranking_is_deterministic_for_identical_candidates(self):
        candidates = [
            make_candidate("full_payment", date(2026, 1, 1), "5000"),
            make_candidate("full_payment", date(2026, 1, 1), "5000"),
        ]
        self.assertEqual(
            [candidate.method for candidate in rank_candidates(candidates)],
            ["full_payment", "full_payment"])


if __name__ == "__main__":
    unittest.main()
