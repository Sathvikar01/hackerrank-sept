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
    PlanEntry,
    Provenance,
    UnresolvedFactError,
    VerificationInput,
    money_to_string,
)
from .forecast import ForecastPolicy, VariableSpendingModel, project
from .ingest import Dataset, RequestScope
from .planning import (
    Capacity,
    PlanCandidate,
    candidate_change_actions,
    compute_capacity,
    enumerate_candidates,
    installment_entries,
    installment_months,
)
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
        explanation = (
            f"No safe accepted payment completes the request for "
            f"{money_to_string(scope.request.requested_amount)} by the desired completion "
            f"date or within the {self.policy.horizon_days}-day forecast. At most "
            f"{money_to_string(capacity.amount_safe_to_pay)} is safe today while keeping the "
            f"protected minimum balance of "
            f"{money_to_string(scope.profile.minimum_balance_to_keep)}.")
        if capacity.earliest_full_payment_date is not None:
            explanation += (
                f" A single safe full payment first becomes possible on "
                f"{capacity.earliest_full_payment_date.isoformat()}, but no plan meets "
                f"all payment preferences, schedule constraints, and the desired "
                f"completion date {scope.request.desired_completion_date.isoformat()}.")
        return Decision(
            request_id=scope.request.request_id,
            amount_safe_to_pay=capacity.amount_safe_to_pay,
            plan=plan,
            earliest_date_for_full_payment=capacity.earliest_full_payment_date,
            decision_explanation=explanation,
        )

    def decide_all(self) -> list[Decision]:
        return [
            self.decide(request_id)
            for request_id in self.dataset.requests
        ]

    def verify(self, decision: Decision,
               *, scope: RequestScope | None = None) -> VerificationInput:
        """Independently validate every constraint the certification claims.

        Raises ContractError when any payment or constraint was not actually
        evaluated: a plan must never be certified on partial validation.
        """
        scope = scope or self.dataset.scope(decision.request_id)
        request = scope.request
        profile = scope.profile
        policy = self.policy
        plan = decision.plan
        horizon_end = policy.end_date(request.request_date)

        # --- horizon and bounds -------------------------------------------
        for entry in plan.entries:
            if not (request.request_date <= entry.payment_date <= horizon_end):
                raise ContractError(
                    f"plan payment on {entry.payment_date.isoformat()} lies outside "
                    f"the evaluated forecast horizon")
        if not (Decimal(0) <= decision.amount_safe_to_pay <= request.requested_amount):
            raise ContractError("amount_safe_to_pay is outside the request bounds")

        checks = ["plan_payments_within_evaluated_horizon"]

        if plan.method == "not_recommended":
            if plan.entries:
                raise ContractError("not_recommended must not carry plan payments")
            if plan.status != "not_affordable":
                raise ContractError("not_recommended requires not_affordable status")
            if plan.changes:
                raise ContractError("not_recommended must not require spending changes")
            try:
                capacity = compute_capacity(
                    scope, policy, variable_model=self.variable_model)
            except UnresolvedFactError:
                if decision.amount_safe_to_pay != Decimal(0):
                    raise ContractError(
                        "unresolved facts permit no safe amount other than zero")
            else:
                if decision.amount_safe_to_pay not in (
                        Decimal(0), capacity.amount_safe_to_pay):
                    raise ContractError(
                        "reported safe amount does not match the recomputed capacity")
            checks.extend([
                "no_payment_certified",
                "capacity_recomputed_from_structured_facts",
            ])
            return self._verification_input(
                scope, decision, (), scope.profile.current_available_balance,
                tuple(checks) + ("minimum_balance_respected",))

        # --- eligibility ---------------------------------------------------
        accepted = set(profile.payment_methods)
        if plan.method == "full_payment" and "full_payment" not in accepted:
            raise ContractError("user does not consider full_payment")
        if plan.method == "partial_payment":
            if "partial_payment" not in accepted:
                raise ContractError("user does not consider partial_payment")
            if not request.allows_partial_payment:
                raise ContractError("request does not allow partial payment")
        if plan.method == "installments":
            if "installments" not in accepted:
                raise ContractError("user does not consider installments")
            if profile.max_installment_months is None:
                raise ContractError("max_installment_months is blank")
        if plan.method == "wait" and "full_payment" not in accepted:
            raise ContractError("waiting requires an accepted full payment")
        checks.append("payment_option_eligibility")

        # --- exact amounts and schedules -----------------------------------
        if plan.method == "full_payment":
            expected = (PlanEntry(request.request_date, request.requested_amount),)
            if plan.entries != expected:
                raise ContractError(
                    "full payment must be exactly request_date:requested_amount")
            expected_status = (
                "affordable_now" if not plan.changes else "affordable_with_plan")
            if plan.status != expected_status:
                raise ContractError(
                    f"full payment requires status {expected_status}")
        elif plan.method == "partial_payment":
            if not (Decimal(0) < decision.amount_safe_to_pay < request.requested_amount):
                raise ContractError(
                    "partial payment requires 0 < amount_safe_to_pay < requested_amount")
            if len(plan.entries) != 2:
                raise ContractError("partial payment requires exactly two payments")
            if plan.entries[0].payment_date != request.request_date \
                    or plan.entries[0].amount != decision.amount_safe_to_pay:
                raise ContractError(
                    "the first partial payment must be the safe amount on request_date")
            if decision.earliest_date_for_full_payment is None \
                    or plan.entries[1].payment_date != decision.earliest_date_for_full_payment \
                    or plan.entries[1].amount != request.requested_amount - decision.amount_safe_to_pay:
                raise ContractError(
                    "the second partial payment must complete the request on "
                    "earliest_date_for_full_payment")
            if sum(entry.amount for entry in plan.entries) != request.requested_amount:
                raise ContractError(
                    "partial plan does not sum to requested_amount")
        elif plan.method == "installments":
            if plan.option_id is None:
                raise ContractError("installment plan must name a supplied option")
            matches = [
                option for option in scope.options
                if option.payment_option_id == plan.option_id]
            if not matches:
                raise ContractError(
                    "installment plan does not match a supplied option")
            option = matches[0]
            if option.payment_method != "installments":
                raise ContractError(
                    "the named supplied option is not an installment option")
            if plan.entries != installment_entries(option, policy):
                raise ContractError(
                    "installment schedule must match the supplied option exactly")
            months = installment_months(plan.entries, policy)
            if months > profile.max_installment_months:
                raise ContractError(
                    f"installment plan spans {months} months, beyond "
                    f"max_installment_months={profile.max_installment_months}")
        elif plan.method == "wait":
            if decision.earliest_date_for_full_payment is None \
                    or len(plan.entries) != 1 \
                    or plan.entries[0].payment_date != decision.earliest_date_for_full_payment \
                    or plan.entries[0].amount != request.requested_amount:
                raise ContractError(
                    "wait plan must be earliest_date_for_full_payment:requested_amount")
            if plan.entries[0].payment_date <= request.request_date:
                raise ContractError(
                    "waiting requires the first safe date to lie after request_date")
        else:
            raise ContractError(f"unsupported payment method {plan.method!r}")
        checks.append("exact_payment_schedule")

        # --- deadlines -------------------------------------------------------
        if plan.entries and plan.entries[-1].payment_date > request.desired_completion_date:
            raise ContractError(
                "the recommended plan completes after desired_completion_date")
        checks.append("completion_within_deadline")

        # --- spending-change permissions -------------------------------------
        allowed_changes = {
            (change.kind, change.event_id, change.new_amount)
            for change in candidate_change_actions(scope, policy)
        }
        if len(plan.changes) > 3:
            raise ContractError("at most three spending changes are allowed")
        targeted: set[str] = set()
        for change in plan.changes:
            if change.event_id in targeted:
                raise ContractError("an event must not be changed more than once")
            targeted.add(change.event_id)
            if (change.kind, change.event_id, change.new_amount) not in allowed_changes:
                raise ContractError(
                    f"spending change {change.to_string()} is not permitted for "
                    "this profile and event")
        checks.append("spending_change_limits_respected")

        # --- capacity and earliest-date minimality ---------------------------
        capacity = compute_capacity(
            scope, policy, variable_model=self.variable_model)
        if decision.amount_safe_to_pay != capacity.amount_safe_to_pay:
            raise ContractError(
                "reported safe amount does not match the recomputed capacity")
        if plan.method in {"partial_payment", "wait"} \
                and decision.earliest_date_for_full_payment != capacity.earliest_full_payment_date:
            raise ContractError(
                "earliest_date_for_full_payment is not the first safe full-payment date")
        checks.append("capacity_recomputed_from_structured_facts")

        # --- ranking correctness --------------------------------------------
        candidate_set = enumerate_candidates(
            scope, policy, capacity, variable_model=self.variable_model)
        ranked = rank_candidates(candidate_set.candidates)
        if not ranked:
            raise ContractError(
                "no eligible candidate exists for the recommended plan")
        chosen = ranked[0]
        if (chosen.method != plan.method or chosen.entries != plan.entries
                or chosen.option_id != plan.option_id
                or chosen.changes != plan.changes):
            raise ContractError(
                "the recommended plan is not the top-ranked eligible candidate")
        checks.append("ranking_recomputed")

        # --- fresh full-trajectory replay ------------------------------------
        forecast = project(
            scope,
            policy,
            plan=decision.plan.entries,
            changes=decision.plan.changes,
            variable_model=self.variable_model,
        )
        if not forecast.safe:
            raise ContractError(
                "recommended plan is not safe under a fresh replay")
        checks.extend([
            "plan_trajectory_replayed",
            "minimum_balance_respected",
            "partial_payments_sum_to_requested_amount",
        ])
        return self._verification_input(
            scope, decision, forecast.points, forecast.minimum, tuple(checks))

    def _verification_input(self, scope: RequestScope, decision: Decision,
                            points, minimum, checks,
                            *, minimum_required=None) -> VerificationInput:
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
            balance_points=points,
            minimum_projected_balance=minimum,
            minimum_required=(
                minimum_required
                if minimum_required is not None
                else scope.profile.minimum_balance_to_keep),
            checks=checks,
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
