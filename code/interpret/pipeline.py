from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from itertools import product
from typing import Sequence

from finance.contracts import ContractError, Decision, PaymentPlan
from finance.forecast import detect_recurrence, project, series_key
from finance.overlay import OVERRIDABLE_FIELDS, apply_overrides

from .attachment import (
    ATTACHMENT_FIELDS,
    AttachmentAxis,
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


STATUS_SAFETY_RANK = {
    "not_affordable": 0,
    "affordable_later": 1,
    "affordable_with_plan": 2,
    "affordable_now": 3,
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset({
    "the", "and", "for", "with", "from", "your", "this", "that", "not",
    "are", "was", "will", "has", "have", "been", "when", "next", "new",
    "about", "into", "after", "before", "still", "until", "you", "yours",
    "ada", "dari", "yang", "dengan", "untuk", "akan", "adalah", "belum",
    "sudah", "tidak", "dalam", "oleh", "pada", "dan", "atau", "ini",
    "itu", "ke", "di",
    # Generic finance vocabulary never identifies a series on its own; only
    # distinctive merchant/category tokens may bind evidence to a series.
    "payment", "payments", "payout", "payouts", "salary", "gaji", "income",
    "refund", "refunds", "bonus", "commission", "transfer", "transfers",
    "account", "balance", "update", "pending", "approved", "amount",
    "date", "scheduled", "deposit", "credit", "debit", "earning",
    "earnings", "weekly", "monthly", "invoice", "invoices", "client",
    "service", "app", "bank", "pay", "paid", "cash", "money", "fund",
    "funds", "process", "processing", "final", "home", "currency",
})


def _tokens(text: str) -> set[str]:
    return {
        token for token in _TOKEN_RE.findall(str(text).lower())
        if len(token) >= 3 and token not in _STOPWORDS
    }


def _decision_safety_key(decision: Decision) -> tuple:
    """Total, order-independent safety order over decisions: smaller is the
    financially safer (less committing) recommendation."""
    plan = decision.plan
    start = plan.entries[0].payment_date if plan.entries else date.max
    return (
        STATUS_SAFETY_RANK.get(plan.status, 0),
        decision.amount_safe_to_pay,
        start,
        len(plan.entries),
        plan.option_id or "",
    )


def _recurring_credit_series(engine, scope):
    """Projected recurring income series of the scope (before exclusions)."""
    return [
        item for item in detect_recurrence(
            scope, engine.policy, as_of=scope.request.request_date)
        if item.direction == "credit"
    ]


def _income_suppression_exclusions(engine, scope, sources) -> frozenset:
    """Conservative reading of unresolved income evidence: income series the
    source text refers to are not counted until the evidence resolves."""
    if not sources:
        return frozenset()
    series = _recurring_credit_series(engine, scope)
    if not series:
        return frozenset()
    exclusions: set[tuple[str, str, str]] = set()
    for text in sources:
        text_tokens = _tokens(text)
        if not text_tokens:
            continue
        for item in series:
            member_events = [
                scope.event_by_id(event_id) for event_id in item.event_ids
            ]
            series_text = " ".join(
                [item.key[0]]
                + [event.description or "" for event in member_events if event]
            )
            if _tokens(series_text) & text_tokens:
                exclusions.add(item.key)
    return frozenset(exclusions)


def _unquantified_debit_evidence(outcomes) -> bool:
    """Unresolved evidence announcing a debit that cannot be quantified or
    attached: an unbounded obligation cannot be certified against."""
    for outcome in outcomes:
        if outcome.state not in {"ambiguous", "unresolved"}:
            continue
        if outcome.state == "ambiguous" and outcome.candidates:
            # Enumerable interpretations exist; handled by variant enumeration.
            continue
        claim = outcome.claim
        if claim.field == "direction" and claim.value == "debit":
            return True
        if claim.field == "amount" and claim.lifecycle == "new_obligation":
            return True
    return False


def _unresolved_source_texts(scope, outcomes, errored_sources) -> tuple[str, ...]:
    texts: list[str] = []
    for outcome in outcomes:
        if outcome.state not in {"ambiguous", "unresolved"}:
            continue
        if outcome.state == "ambiguous" and outcome.candidates:
            continue
        message = next(
            (item for item in scope.messages
             if item.message_id == outcome.claim.source_id), None)
        if message is not None:
            texts.append(message.text)
    for source_kind, source_id in errored_sources:
        if source_kind != "message":
            continue
        message = next(
            (item for item in scope.messages if item.message_id == source_id), None)
        if message is not None and message.text not in texts:
            texts.append(message.text)
    return tuple(texts)


def _one_time_exclusions(scope, sets) -> frozenset:
    """Series keys suppressed by accepted one_time recurrence evidence."""
    exclusions: set[tuple[str, str, str]] = set()
    for item in sets:
        if item.field != "recurrence" or item.event_ref is None:
            continue
        if item.accepted == "one_time":
            event = scope.event_by_id(item.event_ref)
            if event is None:
                continue
            if event.direction == "credit":
                exclusions.add((event.category, "*", event.currency))
            else:
                exclusions.add(series_key(event))
    return frozenset(exclusions)


def _variant_scopes(base, axes, exclusions, cap):
    """Enumerate interpretation variants jointly across ambiguous axes.

    Returns (scopes, truncated). Single-option axes are deterministic
    attachments applied to every variant; multi-option axes contribute one
    dimension each; unresolved evidence contributes the conservative income
    suppression in every variant.
    """
    amended = base
    for axis in axes:
        if len(axis.options) == 1:
            amended = apply_attachment_option(amended, axis, axis.options[0])
    multi = [axis for axis in axes if len(axis.options) > 1]
    total = 1
    for axis in multi:
        total *= len(axis.options)
    if total > cap:
        return None, True
    amended = replace(amended, recurrence_exclusions=exclusions) \
        if exclusions else amended
    if not multi:
        return (amended,), False
    combos = product(*(axis.options for axis in multi))
    scopes = []
    for combo in combos:
        variant = amended
        for axis, option in zip(multi, combo):
            variant = apply_attachment_option(variant, axis, option)
        scopes.append(variant)
    return tuple(scopes), False


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
        errored_sources = tuple(
            (item.source_kind, item.source_id)
            for item in primary_extractions if item.error
        )
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
                errored_sources = (*errored_sources, (source_kind, source_id))
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
        evidence_unknown = bool(errored_sources) or any(
            item.state in {"ambiguous", "unresolved"} for item in outcomes)
        combined_status = _combine_materiality(
            materiality.status, attachment_materiality)
        if evidence_unknown and combined_status == "immaterial":
            combined_status = "unknown"

        used_verification = False
        outcome: VerificationOutcome | None = None
        verification_checks: tuple = ()
        if combined_status != "immaterial" and self.controller is not None:
            used_verification = True
            tools = default_tools(
                scope, tuple(all_claims), extractor=self.primary,
                verification_extractor=self.second,
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
                if evidence_unknown and combined_status == "immaterial":
                    combined_status = "unknown"

        # Verification rereads can recover an unreadable source.
        reread_sources = {
            str(check.get("source_id"))
            for check in verification_checks
            if check.get("status") == "executed"
            and check.get("action") in {"reread_message", "reinspect_image"}
            and check.get("claims")
        }
        unresolved_errors = tuple(
            (kind, source_id) for kind, source_id in errored_sources
            if source_id not in reread_sources
        )

        # Accepted one_time recurrence evidence suppresses its series.
        exclusions = _one_time_exclusions(scope, sets)

        amended = _default_attachment_scope(base_amended, axes)
        if exclusions:
            amended = replace(
                amended, recurrence_exclusions=amended.recurrence_exclusions | exclusions)
        decision = self.engine.decide(request_id, scope=amended)

        sensitivity_notes: list[str] = []
        if decision.plan.method != "not_recommended":
            # A positive recommendation must be safe across all supported
            # interpretations of unresolved or ambiguous evidence.
            sensitivity_exclusions = exclusions | _income_suppression_exclusions(
                self.engine, base_amended,
                _unresolved_source_texts(scope, outcomes, unresolved_errors))
            variants, truncated = _variant_scopes(
                base_amended, axes, sensitivity_exclusions,
                self.policy.max_materiality_combinations)
            blocked = bool(unresolved_errors) or truncated \
                or _unquantified_debit_evidence(outcomes)
            if variants is None:
                blocked = True
                sensitivity_notes.append(
                    "interpretation sensitivity: combination cap exceeded; "
                    "coverage incomplete")
            else:
                decisions = [
                    self.engine.decide(request_id, scope=variant)
                    for variant in variants
                ]
                chosen_index = min(
                    range(len(decisions)),
                    key=lambda index: (
                        _decision_safety_key(decisions[index]), index))
                chosen = decisions[chosen_index]
                chosen_scope = variants[chosen_index]
                if truncated:
                    blocked = True
                elif not blocked:
                    for variant in variants:
                        forecast = project(
                            variant, self.engine.policy,
                            plan=chosen.plan.entries,
                            changes=chosen.plan.changes,
                            variable_model=self.engine.variable_model,
                        )
                        if chosen.plan.entries and not forecast.safe:
                            blocked = True
                            break
                if chosen is not decision and not blocked:
                    decision = chosen
                    amended = chosen_scope
                    sensitivity_notes.append(
                        "interpretation sensitivity: adopted the financially safer "
                        "interpretation across "
                        f"{len(variants)} supported variant(s)")
                if sensitivity_exclusions != exclusions:
                    sensitivity_notes.append(
                        "interpretation sensitivity: unresolved income evidence "
                        "suppresses recurring series "
                        + ", ".join(sorted(
                            {"/".join(key) for key in sensitivity_exclusions
                             if key not in exclusions})))
            if blocked:
                sensitivity_notes.append(
                    "positive recommendation blocked: consequential evidence "
                    "remained unresolved after verification")
                decision = _conservative_decision(scope)
                amended = scope
        elif unresolved_errors:
            sensitivity_notes.append(
                "unresolved extraction errors remain; no positive recommendation "
                "was certified")

        unresolved: list[str] = list(sensitivity_notes)
        unresolved.extend(
            f"primary extraction failed for {kind}:{source_id}: no claims"
            for kind, source_id in unresolved_errors)
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
