from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Sequence

from finance.contracts import ContractError, Decision, PaymentPlan
from finance.overlay import OVERRIDABLE_FIELDS, apply_overrides

from .attachment import (
    ATTACHMENT_FIELDS,
    apply_attachment_option,
    attach_claims,
    build_attachment_axes,
    evaluate_attachment_materiality,
)
from .certificate import EvidenceCertificate
from .extractor import EvidenceExtractor
from .independent import compare_extractions, required_reviews
from .interpretations import build_interpretation_sets
from .materiality import MaterialityPolicy, MaterialityResult, evaluate_materiality
from .schemas import CONSEQUENTIAL_FIELDS, ExtractedClaim, ExtractionError
from .verification import (
    VerificationController,
    VerificationOutcome,
    VerificationPolicy,
    default_tools,
    run_verification,
)


@dataclass(frozen=True)
class PipelinePolicy:
    max_materiality_combinations: int = 64
    verification: VerificationPolicy = field(default_factory=VerificationPolicy)


@dataclass(frozen=True)
class PipelineResult:
    request_id: str
    decision: Decision
    materiality: MaterialityResult
    certificate: EvidenceCertificate
    used_verification: bool
    attachments: tuple = ()


class EvidencePipeline:
    def __init__(
        self,
        dataset,
        engine,
        *,
        primary: EvidenceExtractor,
        second: EvidenceExtractor,
        controller: VerificationController | None = None,
        policy: PipelinePolicy | None = None,
    ) -> None:
        self.dataset = dataset
        self.engine = engine
        self.primary = primary
        self.second = second
        self.controller = controller
        self.policy = policy or PipelinePolicy()

    def run(self, request_id: str) -> PipelineResult:
        scope = self.dataset.scope(request_id)
        primary_extractions = self.primary.extract_scope(scope)
        errors = [
            f"{item.source_kind}:{item.source_id}: {item.error}"
            for item in primary_extractions if item.error
        ]
        primary_ok = tuple(item for item in primary_extractions if not item.error)
        extractions: list = list(primary_ok)
        reviews = []
        for source_kind, source_id in required_reviews(primary_ok):
            try:
                second = self.second.extract_source(
                    scope, source_kind=source_kind, source_id=source_id)
            except ExtractionError as error:
                errors.append(f"{source_kind}:{source_id}: {error}")
                continue
            extractions.append(second)
            first = next(
                item for item in primary_ok
                if item.source_kind == source_kind and item.source_id == source_id)
            reviews.append(compare_extractions(first, second))

        all_claims: list[ExtractedClaim] = [
            claim for item in extractions for claim in item.claims
        ]
        directions = {event.event_id: event.direction for event in scope.events}
        required_fields = _required_fields(scope, extractions)
        sets = build_interpretation_sets(
            all_claims, directions=directions, required_fields=required_fields)
        materiality = self._materiality(scope, sets)
        base_amended = _amended_scope(scope, sets)
        outcomes, axes = _attachments(scope, all_claims)
        attachment_materiality = self._attachment_materiality(base_amended, axes)
        combined_status = _combine_materiality(
            materiality.status, attachment_materiality)

        used_verification = False
        outcome: VerificationOutcome | None = None
        verification_checks: tuple = ()
        if combined_status != "immaterial" and self.controller is not None:
            used_verification = True
            tools = default_tools(
                scope, tuple(all_claims), extractor=self.primary,
                attachment_outcomes=outcomes)
            outcome = run_verification(
                scope, sets, controller=self.controller, tools=tools,
                policy=self.policy.verification)
            verification_checks = outcome.checks
            if outcome.new_claims:
                all_claims.extend(outcome.new_claims)
                sets = build_interpretation_sets(
                    all_claims, directions=directions, required_fields=required_fields)
                materiality = self._materiality(scope, sets)
                base_amended = _amended_scope(scope, sets)
                outcomes, axes = _attachments(scope, all_claims)
                attachment_materiality = self._attachment_materiality(
                    base_amended, axes)
                combined_status = _combine_materiality(
                    materiality.status, attachment_materiality)

        amended = _default_attachment_scope(base_amended, axes)
        decision = self.engine.decide(request_id, scope=amended)
        unresolved: list[str] = []
        if materiality.status != "immaterial":
            detail = ", ".join(materiality.differing_fields) \
                or ", ".join(materiality.unresolved_axes)
            unresolved.append(f"materiality {materiality.status}: {detail}")
        for review in reviews:
            for comparison in review.comparisons:
                if comparison.agreement == "disagree":
                    unresolved.append(
                        f"independent extractors disagree on "
                        f"{comparison.event_ref}:{comparison.field}: "
                        f"{comparison.primary_value} vs {comparison.second_value}")
        if outcome is not None:
            unresolved.extend(outcome.unresolved)
        if attachment_materiality is not None \
                and attachment_materiality.status != "immaterial":
            detail = ", ".join(attachment_materiality.differing_fields) \
                or "unbounded attachment values"
            unresolved.append(
                f"attachment materiality {attachment_materiality.status}: {detail}")
        for item in outcomes:
            if item.state in {"ambiguous", "unresolved"}:
                unresolved.append(
                    f"attachment {item.state} for {item.claim.claim_id}: "
                    + "; ".join(item.reasons))

        verified = True
        try:
            self.engine.verify(decision, scope=amended)
        except ContractError as error:
            verified = False
            unresolved.append(f"verification failed closed: {error}")
            decision = _conservative_decision(scope)

        certificate = EvidenceCertificate(
            request_id=request_id,
            facts=_facts(all_claims),
            interpretations=sets,
            disagreements=tuple(reviews),
            verification_checks=verification_checks,
            materiality={
                "status": _combine_materiality(
                    materiality.status, attachment_materiality),
                "base_status": materiality.status,
                "attachment_status": (
                    attachment_materiality.status
                    if attachment_materiality is not None else "none"),
                "combinations_examined": materiality.combinations_examined,
                "differing_fields": list(materiality.differing_fields),
                "attachment_differing_fields": (
                    list(attachment_materiality.differing_fields)
                    if attachment_materiality is not None else []),
                "unresolved_axes": list(materiality.unresolved_axes),
            },
            decision_row=decision.to_row(),
            verified=verified,
            unresolved=tuple(dict.fromkeys(unresolved)),
            model_calls=tuple(item.call for item in extractions),
            extraction_errors=tuple(errors),
            rejected_claims=tuple(
                rejection for item in extractions for rejection in item.rejected),
            attachments=outcomes,
        )
        return PipelineResult(
            request_id=request_id,
            decision=decision,
            materiality=materiality,
            certificate=certificate,
            used_verification=used_verification,
            attachments=outcomes,
        )

    def _materiality(self, scope, sets) -> MaterialityResult:
        return evaluate_materiality(
            scope, self.engine, sets,
            policy=MaterialityPolicy(self.policy.max_materiality_combinations))

    def _attachment_materiality(self, scope, axes):
        if not axes:
            return None
        return evaluate_attachment_materiality(
            scope, self.engine, axes,
            policy=MaterialityPolicy(self.policy.max_materiality_combinations))


def _attachments(scope, claims):
    unattached = [
        claim for claim in claims
        if claim.event_ref is None and claim.field in ATTACHMENT_FIELDS
    ]
    outcomes = attach_claims(scope, unattached)
    axes = build_attachment_axes(scope, outcomes)
    return outcomes, axes


def _combine_materiality(base_status: str,
                         attachment_materiality) -> str:
    if attachment_materiality is None:
        return base_status
    statuses = {base_status, attachment_materiality.status}
    if "unknown" in statuses:
        return "unknown"
    if "material" in statuses:
        return "material"
    return "immaterial"


def _default_attachment_scope(scope, axes):
    amended = scope
    for axis in axes:
        if len(axis.options) == 1:
            amended = apply_attachment_option(amended, axis, axis.options[0])
    return amended


def _blank_amount_targets(scope) -> tuple[tuple[str, str], ...]:
    return tuple(
        (event.event_id, "amount")
        for event in scope.events
        if event.is_cash and event.amount is None
        and event.status in {"pending", "scheduled"}
    )


def _required_fields(scope, extractions) -> tuple[tuple[str, str], ...]:
    known = {event.event_id for event in scope.events}
    targets = list(_blank_amount_targets(scope))
    for item in extractions:
        for rejection in item.rejected:
            field = rejection.get("field")
            event_ref = rejection.get("event_ref")
            if field in CONSEQUENTIAL_FIELDS and isinstance(event_ref, str) \
                    and event_ref in known:
                targets.append((event_ref, field))
    return tuple(dict.fromkeys(targets))


def _amended_scope(scope, sets):
    overrides = {
        (item.event_ref, item.field): item.accepted
        for item in sets
        if item.accepted is not None and item.event_ref is not None
        and item.field in OVERRIDABLE_FIELDS
    }
    return apply_overrides(scope, overrides)


def _facts(claims: Sequence[ExtractedClaim]):
    from finance.contracts import CanonicalFact

    return tuple(
        CanonicalFact(
            fact_id=claim.claim_id,
            fact_ref=claim.event_ref or claim.source_id,
            field_name=claim.field,
            value=claim.value,
            source_kind=claim.source_kind,
            provenance=(claim.provenance,),
        )
        for claim in claims
    )


def _conservative_decision(scope) -> Decision:
    plan = PaymentPlan(method="not_recommended", status="not_affordable")
    return Decision(
        request_id=scope.request.request_id,
        amount_safe_to_pay=Decimal(0),
        plan=plan,
        earliest_date_for_full_payment=None,
        decision_explanation=(
            "Verification failed closed: the recommended plan did not pass the "
            "deterministic safety replay, so no payment is approved."),
    )
