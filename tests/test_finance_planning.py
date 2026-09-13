import unittest
from datetime import date
from decimal import Decimal

from finance.contracts import ChangeAction, PlanEntry
from finance.forecast import project
from finance.planning import (
    candidate_change_actions,
    change_combinations,
    compute_capacity,
    enumerate_candidates,
    installment_months,
)

from tests import finance_fixtures as fixtures

D = fixtures.D


def recurring_history(event_prefix: str, category: str, description: str, amount: str,
                      flexibility: str = "stoppable", floor: str | None = None):
    events = []
    for index, day in enumerate(
            [date(2025, 10, 5), date(2025, 11, 5), date(2025, 12, 5)], start=1):
        events.append(fixtures.event(
            event_id=f"{event_prefix}{index}", status="settled", amount=D(amount),
            category=category, description=description, flexibility=flexibility,
            minimum_allowed_amount=None if floor is None else D(floor),
            event_date=day, settlement_date=day))
    return events


def installment_candidates(candidate_set, option_id):
    return [
        candidate for candidate in candidate_set.candidates
        if candidate.method == "installments" and candidate.option_id == option_id
    ]


class PlanningTests(unittest.TestCase):
    def test_amount_safe_to_pay_is_capped_and_minimum_aware(self):
        capped = compute_capacity(
            fixtures.scope(request=fixtures.request(requested_amount=D("30000"))),
            fixtures.no_variable_policy())
        self.assertEqual(capped.amount_safe_to_pay, D("30000"))
        self.assertEqual(capped.earliest_full_payment_date, date(2026, 1, 1))

        limited = compute_capacity(
            fixtures.scope(
                profile=fixtures.profile(current_available_balance=D("100000")),
                request=fixtures.request(requested_amount=D("30000")),
                events=[fixtures.event(
                    event_id="event_01", status="scheduled", amount=D("80000"),
                    event_date=date(2026, 1, 20), settlement_date=date(2026, 1, 20))]),
            fixtures.no_variable_policy())
        self.assertEqual(limited.amount_safe_to_pay, D("10000"))

    def test_earliest_full_payment_scans_forward_until_safe(self):
        capacity = compute_capacity(
            fixtures.scope(
                profile=fixtures.profile(current_available_balance=D("60000")),
                request=fixtures.request(requested_amount=D("60000")),
                events=[fixtures.event(
                    event_id="event_01", status="scheduled", direction="credit",
                    event_type="income", amount=D("45000"),
                    event_date=date(2026, 1, 10), settlement_date=date(2026, 1, 10))]),
            fixtures.no_variable_policy())
        self.assertEqual(capacity.amount_safe_to_pay, D("50000"))
        self.assertEqual(capacity.earliest_full_payment_date, date(2026, 1, 11))

    def test_partial_payment_requires_all_conditions(self):
        base_scope = fixtures.scope(
            profile=fixtures.profile(current_available_balance=D("60000")),
            request=fixtures.request(requested_amount=D("60000")),
            events=[fixtures.event(
                event_id="event_01", status="scheduled", direction="credit",
                event_type="income", amount=D("45000"),
                event_date=date(2026, 1, 10), settlement_date=date(2026, 1, 10))])
        policy = fixtures.no_variable_policy()
        capacity = compute_capacity(base_scope, policy)
        candidate_set = enumerate_candidates(base_scope, policy, capacity)
        partials = [
            candidate for candidate in candidate_set.candidates
            if candidate.method == "partial_payment"]
        self.assertTrue(any(candidate.eligible for candidate in partials))
        chosen = next(candidate for candidate in partials if candidate.eligible)
        self.assertEqual(
            [(entry.payment_date, entry.amount) for entry in chosen.entries],
            [(date(2026, 1, 1), D("50000")), (date(2026, 1, 11), D("10000"))])
        self.assertEqual(sum(entry.amount for entry in chosen.entries), D("60000"))

        not_allowed = fixtures.scope(
            profile=base_scope.profile,
            request=fixtures.request(
                requested_amount=D("60000"), allows_partial_payment=False),
            events=base_scope.events)
        candidate_set = enumerate_candidates(
            not_allowed, policy, compute_capacity(not_allowed, policy))
        partials = [
            candidate for candidate in candidate_set.candidates
            if candidate.method == "partial_payment"]
        self.assertFalse(any(candidate.eligible for candidate in partials))

        no_preference = fixtures.scope(
            profile=fixtures.profile(
                current_available_balance=D("60000"),
                payment_methods=("full_payment", "installments")),
            request=fixtures.request(requested_amount=D("60000")),
            events=base_scope.events)
        candidate_set = enumerate_candidates(
            no_preference, policy, compute_capacity(no_preference, policy))
        partials = [
            candidate for candidate in candidate_set.candidates
            if candidate.method == "partial_payment"]
        self.assertFalse(any(candidate.eligible for candidate in partials))

        full_is_safe = fixtures.scope(
            request=fixtures.request(requested_amount=D("5000")))
        candidate_set = enumerate_candidates(
            full_is_safe, policy, compute_capacity(full_is_safe, policy))
        partials = [
            candidate for candidate in candidate_set.candidates
            if candidate.method == "partial_payment"]
        self.assertFalse(any(candidate.eligible for candidate in partials))

        late_capacity = fixtures.scope(
            profile=fixtures.profile(current_available_balance=D("60000")),
            request=fixtures.request(
                requested_amount=D("60000"), desired_completion_date=date(2026, 1, 5)),
            events=[fixtures.event(
                event_id="event_01", status="scheduled", direction="credit",
                event_type="income", amount=D("45000"),
                event_date=date(2026, 2, 1), settlement_date=date(2026, 2, 1))])
        candidate_set = enumerate_candidates(
            late_capacity, policy, compute_capacity(late_capacity, policy))
        partials = [
            candidate for candidate in candidate_set.candidates
            if candidate.method == "partial_payment"]
        self.assertFalse(any(candidate.eligible for candidate in partials))

    def test_installment_plan_must_be_safe_across_the_whole_trajectory(self):
        scope = fixtures.scope(
            profile=fixtures.profile(
                current_available_balance=D("50000"),
                payment_methods=("installments",), max_installment_months=12),
            request=fixtures.request(
                requested_amount=D("30000"),
                desired_completion_date=date(2026, 3, 31)),
            options=[fixtures.option(
                option_id="payment_option_01", payment_amount=D("12000"),
                number_of_payments=3, payment_frequency_days=30,
                total_payable_amount=D("36000"))],
            events=[fixtures.event(
                event_id="event_01", status="scheduled", amount=D("20000"),
                event_date=date(2026, 2, 20), settlement_date=date(2026, 2, 20))])
        policy = fixtures.no_variable_policy()
        first_only = project(
            scope, policy, plan=(PlanEntry(date(2026, 1, 1), D("12000")),))
        self.assertTrue(first_only.safe)
        candidate_set = enumerate_candidates(scope, policy, compute_capacity(scope, policy))
        candidates = installment_candidates(candidate_set, "payment_option_01")
        self.assertTrue(candidates)
        self.assertFalse(any(candidate.eligible for candidate in candidates))
        self.assertTrue(any(
            "minimum" in reason
            for candidate in candidates for reason in candidate.rejected))

    def test_installment_eligibility_rules(self):
        long_option = fixtures.option(
            option_id="payment_option_01", payment_amount=D("100"),
            number_of_payments=15, first_payment_date=date(2026, 1, 1),
            payment_frequency_days=30, total_payable_amount=D("1500"))
        scope = fixtures.scope(
            profile=fixtures.profile(
                payment_methods=("installments",), max_installment_months=7),
            request=fixtures.request(
                requested_amount=D("1500"),
                desired_completion_date=date(2027, 12, 31)),
            options=[long_option])
        policy = fixtures.no_variable_policy()
        candidate_set = enumerate_candidates(scope, policy, compute_capacity(scope, policy))
        candidates = installment_candidates(candidate_set, "payment_option_01")
        self.assertFalse(any(candidate.eligible for candidate in candidates))
        self.assertTrue(any(
            "max_installment_months" in reason
            for candidate in candidates for reason in candidate.rejected))

        boundary_option = fixtures.option(
            option_id="payment_option_02", payment_amount=D("100"),
            number_of_payments=2, first_payment_date=date(2026, 1, 31),
            payment_frequency_days=1, total_payable_amount=D("200"))
        boundary_scope = fixtures.scope(
            profile=fixtures.profile(
                payment_methods=("installments",), max_installment_months=1),
            request=fixtures.request(
                requested_amount=D("200"),
                desired_completion_date=date(2026, 2, 5)),
            options=[boundary_option])
        days_30 = enumerate_candidates(
            boundary_scope,
            fixtures.no_variable_policy(installment_month_semantics="days_30"),
            compute_capacity(boundary_scope, fixtures.no_variable_policy()))
        self.assertTrue(any(
            candidate.eligible
            for candidate in installment_candidates(days_30, "payment_option_02")))
        calendar = enumerate_candidates(
            boundary_scope,
            fixtures.no_variable_policy(installment_month_semantics="calendar_months"),
            compute_capacity(boundary_scope, fixtures.no_variable_policy()))
        self.assertFalse(any(
            candidate.eligible
            for candidate in installment_candidates(calendar, "payment_option_02")))

        backdated = fixtures.option(
            option_id="payment_option_03", payment_amount=D("100"),
            number_of_payments=2, first_payment_date=date(2025, 12, 31),
            payment_frequency_days=30, total_payable_amount=D("200"))
        backdated_scope = fixtures.scope(
            profile=fixtures.profile(
                payment_methods=("installments",), max_installment_months=12),
            request=fixtures.request(requested_amount=D("200")),
            options=[backdated])
        candidate_set = enumerate_candidates(
            backdated_scope, policy, compute_capacity(backdated_scope, policy))
        candidates = installment_candidates(candidate_set, "payment_option_03")
        self.assertFalse(any(candidate.eligible for candidate in candidates))
        self.assertTrue(any(
            "before request_date" in reason
            for candidate in candidates for reason in candidate.rejected))

        not_considered = fixtures.scope(
            profile=fixtures.profile(
                payment_methods=("full_payment",), max_installment_months=12),
            request=fixtures.request(requested_amount=D("200")),
            options=[fixtures.option(
                option_id="payment_option_04", payment_amount=D("100"),
                number_of_payments=2, first_payment_date=date(2026, 1, 1),
                payment_frequency_days=30, total_payable_amount=D("200"))])
        candidate_set = enumerate_candidates(
            not_considered, policy, compute_capacity(not_considered, policy))
        candidates = installment_candidates(candidate_set, "payment_option_04")
        self.assertFalse(any(candidate.eligible for candidate in candidates))

    def test_spending_change_candidates_respect_permissions_and_floors(self):
        history = recurring_history(
            "event_0", "dining", "Dining out", "500",
            flexibility="reducible_or_stoppable", floor="100")
        permitted = fixtures.scope(
            profile=fixtures.profile(
                reduce_categories=("dining",), stop_categories=("dining",)),
            events=history)
        actions = candidate_change_actions(permitted, fixtures.no_variable_policy())
        self.assertIn(ChangeAction.stop("event_03"), actions)
        self.assertIn(ChangeAction.reduce_to("event_03", D("100")), actions)

        protected = fixtures.scope(
            profile=fixtures.profile(
                protected_categories=("dining",),
                reduce_categories=("dining",), stop_categories=("dining",)),
            events=history)
        self.assertEqual(
            candidate_change_actions(protected, fixtures.no_variable_policy()), ())

        wrong_category = fixtures.scope(
            profile=fixtures.profile(
                reduce_categories=("travel",), stop_categories=("travel",)),
            events=history)
        self.assertEqual(
            candidate_change_actions(wrong_category, fixtures.no_variable_policy()), ())

        fixed = fixtures.scope(
            profile=fixtures.profile(
                reduce_categories=("dining",), stop_categories=("dining",)),
            events=recurring_history("event_0", "dining", "Dining out", "500",
                                     flexibility="fixed", floor="100"))
        self.assertEqual(candidate_change_actions(fixed, fixtures.no_variable_policy()), ())

        one_off = fixtures.scope(
            profile=fixtures.profile(
                reduce_categories=("dining",), stop_categories=("dining",)),
            events=[fixtures.event(
                event_id="event_09", status="settled", amount=D("500"),
                category="dining", description="Dining out", flexibility="stoppable",
                event_date=date(2025, 12, 5), settlement_date=date(2025, 12, 5))])
        self.assertEqual(candidate_change_actions(one_off, fixtures.no_variable_policy()), ())

    def test_spending_change_combinations_are_bounded_and_disjoint(self):
        history = []
        for index, category in enumerate(["dining", "travel", "entertainment", "other"], start=1):
            history.extend(recurring_history(
                f"event_1{index}", category, f"{category} spend", "500"))
        scope = fixtures.scope(
            profile=fixtures.profile(
                stop_categories=("dining", "travel", "entertainment", "other")),
            events=history)
        combos, truncated = change_combinations(scope, fixtures.no_variable_policy())
        self.assertFalse(truncated)
        self.assertEqual(combos[0], ())
        self.assertEqual(len(combos), 1 + 4 + 6 + 4)
        for combo in combos:
            self.assertLessEqual(len(combo), 3)
            stopped = {action.event_id for action in combo if action.kind == "stop"}
            reduced = {action.event_id for action in combo if action.kind == "reduce_to"}
            self.assertFalse(stopped & reduced)

        limited, truncated = change_combinations(
            scope, fixtures.no_variable_policy(max_change_combinations=3))
        self.assertEqual(len(limited), 3)
        self.assertTrue(truncated)

    def test_spending_change_can_rescue_an_installment_plan(self):
        scope = fixtures.scope(
            profile=fixtures.profile(
                current_available_balance=D("20000"),
                payment_methods=("installments",), max_installment_months=12,
                stop_categories=("dining",)),
            request=fixtures.request(
                requested_amount=D("30000"), allows_partial_payment=False,
                desired_completion_date=date(2026, 3, 31)),
            options=[fixtures.option(
                option_id="payment_option_01", payment_amount=D("10000"),
                number_of_payments=3, payment_frequency_days=30,
                total_payable_amount=D("30000"))],
            events=[
                fixtures.event(
                    event_id="event_01", status="scheduled", direction="credit",
                    event_type="income", amount=D("40000"),
                    event_date=date(2026, 1, 10), settlement_date=date(2026, 1, 10)),
            ] + recurring_history(
                "event_1", "dining", "Dining out", "4000", flexibility="stoppable"))
        policy = fixtures.no_variable_policy()
        capacity = compute_capacity(scope, policy)
        self.assertEqual(capacity.amount_safe_to_pay, D("6000"))
        candidate_set = enumerate_candidates(scope, policy, capacity)
        candidates = installment_candidates(candidate_set, "payment_option_01")
        no_change = [candidate for candidate in candidates if not candidate.changes]
        with_change = [candidate for candidate in candidates if candidate.changes]
        self.assertTrue(no_change)
        self.assertFalse(any(candidate.eligible for candidate in no_change))
        self.assertTrue(any(candidate.eligible for candidate in with_change))
        chosen = next(candidate for candidate in with_change if candidate.eligible)
        self.assertEqual(chosen.changes, (ChangeAction.stop("event_13"),))
        self.assertEqual(chosen.status, "affordable_with_plan")
        self.assertTrue(all(
            not candidate.eligible
            for candidate in candidate_set.candidates
            if candidate.method in {"full_payment", "partial_payment", "wait"}))

    def test_installment_months_semantics(self):
        entries = (
            PlanEntry(date(2026, 1, 31), D("100")),
            PlanEntry(date(2026, 2, 1), D("100")),
        )
        self.assertEqual(
            installment_months(entries, fixtures.no_variable_policy(
                installment_month_semantics="days_30")), 1)
        self.assertEqual(
            installment_months(entries, fixtures.no_variable_policy(
                installment_month_semantics="calendar_months")), 2)


if __name__ == "__main__":
    unittest.main()
