from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Sequence

from .contracts import (
    CanonicalFact,
    ContractError,
    Decision,
    OUTPUT_COLUMNS,
    PaymentPlan,
    Provenance,
    UnresolvedFactError,
    VerificationInput,
    money_to_string,
)
from .forecast import ForecastPolicy, VariableSpendingModel, project
from .ingest import Dataset, RequestScope
from .planning import Capacity, PlanCandidate, compute_capacity, enumerate_candidates
from .ranking import rank_candidates


class FinancialEngine:
    def __init__(
        self,
        dataset: Dataset,
        policy: ForecastPolicy | None = None,
        variable_model: VariableSpendingModel | None = None,
    ) -> None:
        self.dataset = dataset
        self.policy = policy or ForecastPolicy()
        self.variable_model = variable_model

    def scope(self, request_id: str) -> RequestScope:
        return self.dataset.scope(request_id)

    def decide(self, request_id: str, *, scope: RequestScope | None = None) -> Decision:
        scope = scope or self.dataset.scope(request_id)
        try:
            capacity = compute_capacity(scope, self.policy, variable_model=self.variable_model)
            candidate_set = enumerate_candidates(
                scope, self.policy, capacity, variable_model=self.variable_model)
        except UnresolvedFactError as error:
            return _conservative_decision(scope, str(error))
        ranked = rank_candidates(candidate_set.candidates)
        if ranked:
            chosen = ranked[0]
            plan = PaymentPlan(
                method=chosen.method,
                status=chosen.status,
                entries=chosen.entries,
                changes=chosen.changes,
                option_id=chosen.option_id,
            )
            unresolved = (
                ("spending-change enumeration limit reached",) if candidate_set.truncated else ())
            return Decision(
                request_id=scope.request.request_id,
                amount_safe_to_pay=capacity.amount_safe_to_pay,
                plan=plan,
                earliest_date_for_full_payment=capacity.earliest_full_payment_date,
                decision_explanation=_explain(scope, capacity, chosen),
                unresolved=unresolved,
            )
        plan = PaymentPlan(method="not_recommended", status="not_affordable")
        return Decision(
            request_id=scope.request.request_id,
            amount_safe_to_pay=capacity.amount_safe_to_pay,
            plan=plan,
            earliest_date_for_full_payment=None,
            decision_explanation=(
                f"No safe accepted payment completes the request for "
                f"{money_to_string(scope.request.requested_amount)} by the desired completion "
                f"date or within the {self.policy.horizon_days}-day forecast. At most "
                f"{money_to_string(capacity.amount_safe_to_pay)} is safe today while keeping the "
                f"protected minimum balance of "
                f"{money_to_string(scope.profile.minimum_balance_to_keep)}."),
        )

    def decide_all(self) -> list[Decision]:
        return [
            self.decide(request_id)
            for request_id in self.dataset.requests
        ]

    def verify(self, decision: Decision,
               *, scope: RequestScope | None = None) -> VerificationInput:
        scope = scope or self.dataset.scope(decision.request_id)
        forecast = project(
            scope,
            self.policy,
            plan=decision.plan.entries,
            changes=decision.plan.changes,
            variable_model=self.variable_model,
        )
        checks = [
            "capacity_recomputed_from_structured_facts",
            "plan_trajectory_replayed",
            "minimum_balance_respected",
            "completion_within_deadline",
            "partial_payments_sum_to_requested_amount",
            "spending_change_limits_respected",
        ]
        if decision.plan.method == "partial_payment":
            if sum(entry.amount for entry in decision.plan.entries) \
                    != scope.request.requested_amount:
                raise ContractError("partial plan does not sum to requested_amount")
        if decision.plan.method == "installments" and decision.plan.option_id is not None:
            matches = [
                option for option in scope.options
                if option.payment_option_id == decision.plan.option_id
            ]
            if not matches:
                raise ContractError("installment plan does not match a supplied option")
        if decision.plan.entries and not forecast.safe:
            raise ContractError("recommended plan is not safe under a fresh replay")
        facts = (
            CanonicalFact(
                fact_id=f"{scope.request.request_id}:starting_balance",
                fact_ref=scope.profile.user_id,
                field_name="current_available_balance",
                value=scope.profile.current_available_balance,
                source_kind="structured_profile",
                provenance=(Provenance(
                    "financial_profiles.csv", scope.profile.user_id,
                    "current_available_balance"),),
            ),
            CanonicalFact(
                fact_id=f"{scope.request.request_id}:minimum_balance",
                fact_ref=scope.profile.user_id,
                field_name="minimum_balance_to_keep",
                value=scope.profile.minimum_balance_to_keep,
                source_kind="structured_profile",
                provenance=(Provenance(
                    "financial_profiles.csv", scope.profile.user_id,
                    "minimum_balance_to_keep"),),
            ),
        )
        return VerificationInput(
            request_id=scope.request.request_id,
            decision=decision,
            accepted_facts=facts,
            plan_entries=decision.plan.entries,
            balance_points=forecast.points,
            minimum_projected_balance=forecast.minimum,
            minimum_required=forecast.minimum_required,
            checks=tuple(checks),
        )


def _conservative_decision(scope: RequestScope, reason: str) -> Decision:
    note = (
        f"Unresolved evidence ({reason}); no payment is approved because its safety depends on "
        f"an unknown amount.")
    plan = PaymentPlan(method="not_recommended", status="not_affordable")
    return Decision(
        request_id=scope.request.request_id,
        amount_safe_to_pay=Decimal(0),
        plan=plan,
        earliest_date_for_full_payment=None,
        decision_explanation=note,
        unresolved=(reason,),
    )


def _explain(scope: RequestScope, capacity: Capacity, candidate: PlanCandidate) -> str:
    request = scope.request
    minimum = money_to_string(scope.profile.minimum_balance_to_keep)
    if candidate.method == "full_payment":
        if candidate.changes:
            changes = ", ".join(change.to_string() for change in candidate.changes)
            return (
                f"Paying {money_to_string(request.requested_amount)} in full today is safe after "
                f"{changes}, keeping the balance at or above {minimum} through "
                f"{capacity.baseline.end.isoformat()}. Without spending changes only "
                f"{money_to_string(capacity.amount_safe_to_pay)} is safe today.")
        return (
            f"Paying {money_to_string(request.requested_amount)} in full today keeps the balance "
            f"at or above {minimum} through {capacity.baseline.end.isoformat()}.")
    if candidate.method == "partial_payment":
        first = candidate.entries[0]
        second = candidate.entries[1]
        return (
            f"Pay {money_to_string(first.amount)} today and "
            f"{money_to_string(second.amount)} on {second.payment_date.isoformat()}; the balance "
            f"stays at or above {minimum} throughout, and the request completes by "
            f"{request.desired_completion_date.isoformat()}.")
    if candidate.method == "installments":
        last = candidate.entries[-1]
        return (
            f"Use payment option {candidate.option_id}: {len(candidate.entries)} payments of "
            f"{money_to_string(candidate.entries[0].amount)} starting "
            f"{candidate.entries[0].payment_date.isoformat()}, total "
            f"{money_to_string(candidate.total_paid)}, completing "
            f"{last.payment_date.isoformat()} while keeping at least {minimum}.")
    if candidate.method == "wait":
        return (
            f"Full payment of {money_to_string(request.requested_amount)} becomes safe on "
            f"{candidate.entries[0].payment_date.isoformat()}, before the deadline "
            f"{request.desired_completion_date.isoformat()}, and keeps the balance at or above "
            f"{minimum}.")
    return "No safe eligible payment plan was found."


def write_output_csv(path: Path | str, decisions: Sequence[Decision]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for decision in decisions:
            writer.writerow(decision.to_row())
