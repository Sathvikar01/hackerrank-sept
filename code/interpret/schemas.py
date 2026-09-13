from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from finance.contracts import (
    DIRECTIONS,
    EVENT_STATUSES,
    EVENT_TYPES,
    SUPPORTED_CURRENCIES,
    Provenance,
    parse_date,
)


class ExtractionError(ValueError):
    pass


CLAIM_FIELDS = frozenset({
    "amount", "currency", "event_date", "settlement_date", "status", "category",
    "direction", "event_type", "description", "linked_event_id", "recurrence",
})
LIFECYCLES = frozenset({
    "inform", "confirm", "amend", "cancel", "delay", "new_obligation",
})
SOURCE_KINDS = frozenset({"message", "image"})
RECURRENCE_VALUES = frozenset({"recurring", "one_time", "unknown"})
CONSEQUENTIAL_FIELDS = frozenset({
    "amount", "currency", "event_date", "settlement_date", "status", "direction",
    "event_type", "linked_event_id",
})
CONSEQUENTIAL_LIFECYCLES = frozenset({"confirm", "amend", "cancel", "delay", "new_obligation"})

_EVENT_ID_RE = re.compile(r"^event_\d+$")

ALLOWED_CLAIM_KEYS = frozenset({
    "event_ref", "field", "value", "lifecycle", "evidence_span", "evidence",
    "confidence",
})

_DATE_SUPPORT_FORMATS = (
    "%b %d, %Y", "%B %d, %Y", "%d %B %Y", "%d %b %Y",
    "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y", "%d-%m-%Y", "%m-%d-%Y",
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class ModelCallRecord:
    model: str
    purpose: str
    prompt_tokens: int
    completion_tokens: int
    latency_s: float
    source_id: str | None = None


@dataclass(frozen=True)
class ExtractedClaim:
    claim_id: str
    source_kind: str
    source_id: str
    user_id: str
    request_id: str | None
    event_ref: str | None
    field: str
    value: Any
    lifecycle: str
    evidence: str
    confidence: Decimal | None
    observed_at: date
    provenance: Provenance

    def __post_init__(self) -> None:
        if not str(self.claim_id or "").strip():
            raise ExtractionError("claim_id is required")
        if self.source_kind not in SOURCE_KINDS:
            raise ExtractionError(f"unsupported source_kind {self.source_kind!r}")
        if not str(self.source_id or "").strip():
            raise ExtractionError("source_id is required")
        if not str(self.user_id or "").strip():
            raise ExtractionError("user_id is required")
        if self.request_id is not None and not str(self.request_id).strip():
            raise ExtractionError("request_id must be non-empty when present")
        if self.event_ref is not None and not _EVENT_ID_RE.match(str(self.event_ref)):
            raise ExtractionError(f"malformed event_ref {self.event_ref!r}")
        if self.field not in CLAIM_FIELDS:
            raise ExtractionError(f"unsupported claim field {self.field!r}")
        if self.lifecycle not in LIFECYCLES:
            raise ExtractionError(f"unsupported lifecycle {self.lifecycle!r}")
        if not str(self.evidence or "").strip():
            raise ExtractionError("evidence span is required")
        if self.confidence is not None:
            if not self.confidence.is_finite() or not (
                    Decimal(0) <= self.confidence <= Decimal(1)):
                raise ExtractionError("confidence must be within [0, 1]")
        if not isinstance(self.observed_at, date):
            raise ExtractionError("observed_at must be a date")
        _validate_value(self.field, self.value)


@dataclass(frozen=True)
class Extraction:
    model: str
    source_kind: str
    source_id: str
    claims: tuple[ExtractedClaim, ...]
    call: ModelCallRecord
    error: str | None = None
    rejected: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class ClaimComparison:
    event_ref: str | None
    field: str
    primary_value: Any | None
    second_value: Any | None
    agreement: str


@dataclass(frozen=True)
class IndependentReview:
    source_kind: str
    source_id: str
    model: str
    comparisons: tuple[ClaimComparison, ...]

    @property
    def has_disagreement(self) -> bool:
        return any(item.agreement == "disagree" for item in self.comparisons)


@dataclass(frozen=True)
class InterpretationSet:
    event_ref: str | None
    field: str
    accepted: Any | None
    values: tuple[Any, ...]
    unresolved: bool
    claims: tuple[ExtractedClaim, ...]

    @property
    def ambiguous(self) -> bool:
        return self.unresolved or len(self.values) > 1


def parse_model_json(text: Any) -> Mapping[str, Any]:
    if not isinstance(text, str):
        raise ExtractionError("model output was not text")
    stripped = text.strip()
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        fenced = _extract_fence(stripped)
        if fenced is None:
            raise ExtractionError(
                f"model output was not valid JSON: {stripped[:120]!r}")
        try:
            data = json.loads(fenced)
        except json.JSONDecodeError as error:
            raise ExtractionError("model output was not valid JSON") from error
    if not isinstance(data, Mapping):
        raise ExtractionError("model output must be a JSON object")
    return data


def _extract_fence(text: str) -> str | None:
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    return match.group(1) if match else None


def parse_claims(
    payload: Any,
    *,
    source_kind: str,
    source_id: str,
    user_id: str,
    request_id: str | None,
    observed_at: date,
    source_text: str | None = None,
) -> tuple[ExtractedClaim, ...]:
    claims, rejected = parse_claims_with_rejections(
        payload, source_kind=source_kind, source_id=source_id, user_id=user_id,
        request_id=request_id, observed_at=observed_at, source_text=source_text)
    if rejected:
        raise ExtractionError(str(rejected[0]["reason"]))
    return claims


def parse_claims_with_rejections(
    payload: Any,
    *,
    source_kind: str,
    source_id: str,
    user_id: str,
    request_id: str | None,
    observed_at: date,
    source_text: str | None = None,
) -> tuple[tuple[ExtractedClaim, ...], tuple[Mapping[str, Any], ...]]:
    data = payload if isinstance(payload, Mapping) else parse_model_json(payload)
    items = data.get("claims")
    if not isinstance(items, list):
        raise ExtractionError("model output must contain a claims list")
    unexpected_top = sorted(set(data) - {"claims"})
    claims: list[ExtractedClaim] = []
    rejected: list[Mapping[str, Any]] = []
    if unexpected_top:
        rejected.append({
            "index": None,
            "field": None,
            "event_ref": None,
            "reason": f"model output contains unsupported properties: {unexpected_top}",
        })
    for index, item in enumerate(items):
        try:
            claim = _build_claim(
                item, index, source_kind=source_kind, source_id=source_id,
                user_id=user_id, request_id=request_id, observed_at=observed_at,
                source_text=source_text)
        except ExtractionError as error:
            rejected.append({
                "index": index,
                "field": item.get("field") if isinstance(item, Mapping) else None,
                "event_ref": item.get("event_ref") if isinstance(item, Mapping) else None,
                "reason": str(error),
            })
            continue
        if claim is not None:
            claims.append(claim)
    return tuple(claims), tuple(rejected)


def _build_claim(
    item: Any,
    index: int,
    *,
    source_kind: str,
    source_id: str,
    user_id: str,
    request_id: str | None,
    observed_at: date,
    source_text: str | None = None,
) -> ExtractedClaim | None:
    if not isinstance(item, Mapping):
        raise ExtractionError(f"claim {index} is not an object")
    unexpected = sorted(set(item) - ALLOWED_CLAIM_KEYS)
    if unexpected:
        raise ExtractionError(
            f"claim {index}: unsupported properties {unexpected}")
    field = item.get("field")
    if field not in CLAIM_FIELDS:
        raise ExtractionError(f"claim {index}: unsupported field {field!r}")
    raw = item.get("value")
    if raw is None:
        return None
    try:
        value = _coerce_value(field, raw)
    except (InvalidOperation, ValueError) as error:
        raise ExtractionError(
            f"claim {index}: invalid {field} value {raw!r}") from error
    lifecycle = item.get("lifecycle", "inform")
    if lifecycle not in LIFECYCLES:
        raise ExtractionError(f"claim {index}: unsupported lifecycle {lifecycle!r}")
    evidence = item.get("evidence_span", item.get("evidence"))
    if not isinstance(evidence, str) or not evidence.strip():
        raise ExtractionError(f"claim {index}: evidence_span is required")
    evidence = evidence.strip()
    if source_text is not None:
        if not _span_in_source(evidence, source_text):
            raise ExtractionError(
                f"claim {index}: evidence span is not present in the source")
        if not _value_supported(field, value, source_text):
            raise ExtractionError(
                f"claim {index}: {field} value is not supported by the source evidence")
    confidence = item.get("confidence")
    if confidence is not None:
        try:
            confidence = Decimal(str(confidence))
        except InvalidOperation as error:
            raise ExtractionError(f"claim {index}: invalid confidence") from error
        if not confidence.is_finite() or not (
                Decimal(0) <= confidence <= Decimal(1)):
            raise ExtractionError(f"claim {index}: invalid confidence")
    event_ref = item.get("event_ref")
    if event_ref is not None and not _EVENT_ID_RE.match(str(event_ref)):
        raise ExtractionError(f"claim {index}: malformed event_ref {event_ref!r}")
    return ExtractedClaim(
        claim_id=f"{source_kind}:{source_id}:{index}",
        source_kind=source_kind,
        source_id=source_id,
        user_id=user_id,
        request_id=request_id,
        event_ref=event_ref,
        field=field,
        value=value,
        lifecycle=lifecycle,
        evidence=evidence,
        confidence=confidence,
        observed_at=observed_at,
        provenance=Provenance(
            source="messages.csv" if source_kind == "message" else "images.csv",
            record_id=source_id,
            locator="message_text" if source_kind == "message" else "image_region",
            excerpt=evidence[:300],
        ),
    )


def _normalize_ws(text: str) -> str:
    return " ".join(text.split())


def _span_in_source(evidence: str, source_text: str) -> bool:
    if evidence in source_text:
        return True
    lowered = source_text.lower()
    if evidence.lower() in lowered:
        return True
    return _normalize_ws(evidence).lower() in _normalize_ws(source_text).lower()


def _stem(token: str) -> str:
    if len(token) > 3 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    if len(token) > 4 and token.endswith("es"):
        return token[:-2]
    return token


def _words_supported(value: str, source_text: str) -> bool:
    value_tokens = {
        _stem(token) for token in _TOKEN_RE.findall(value.lower()) if token
    }
    if not value_tokens:
        return False
    text_tokens = {
        _stem(token) for token in _TOKEN_RE.findall(source_text.lower())
    }
    return value_tokens <= text_tokens


def _value_supported(field: str, value: Any, source_text: str) -> bool:
    """A consequential extracted value must be supported by the source text.

    The check is an anti-fabrication guard, not a parser: the value's textual
    form (or an equivalent date rendering) must occur in the source.
    """
    lowered = source_text.lower()
    if field in {"category", "description"}:
        return _words_supported(str(value), source_text)
    if field == "direction":
        # Direction is a semantic classification of a grounded span (for
        # example "you will be charged" implies debit), not a quoted value;
        # consequential direction claims always receive an independent review.
        return True
    if field in {"status", "event_type", "currency", "recurrence",
                "linked_event_id"}:
        return str(value).lower() in lowered
    if field == "amount":
        compact = source_text.replace(",", "").replace(" ", "")
        plain = format(value, "f")
        if plain in compact:
            return True
        if plain.endswith(".00") and plain[:-3] in compact:
            return True
        return plain.replace(".", "") in compact
    if field in {"event_date", "settlement_date"}:
        if value.isoformat() in source_text:
            return True
        for fmt in _DATE_SUPPORT_FORMATS:
            try:
                rendered = value.strftime(fmt)
            except ValueError:
                continue
            if rendered in source_text:
                return True
        return (str(value.day) in source_text
                and value.strftime("%B")[:3].lower() in lowered)
    return True


def _coerce_value(field: str, raw: Any) -> Any:
    if field == "amount":
        if isinstance(raw, bool):
            raise ValueError("boolean amount")
        value = Decimal(str(raw))
        if not value.is_finite() or value <= 0:
            raise ValueError("amount must be a positive finite decimal")
        return value
    if field == "currency":
        if raw not in SUPPORTED_CURRENCIES:
            raise ValueError("unsupported currency")
        return raw
    if field in {"event_date", "settlement_date"}:
        return parse_date(raw, field)
    if field == "status":
        if raw not in EVENT_STATUSES:
            raise ValueError("unsupported status")
        return raw
    if field == "direction":
        if raw not in DIRECTIONS:
            raise ValueError("unsupported direction")
        return raw
    if field == "event_type":
        if raw not in EVENT_TYPES:
            raise ValueError("unsupported event type")
        return raw
    if field in {"category", "description"}:
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("text value required")
        return raw.strip()
    if field == "linked_event_id":
        if not _EVENT_ID_RE.match(str(raw)):
            raise ValueError("malformed linked_event_id")
        return str(raw)
    if field == "recurrence":
        if raw not in RECURRENCE_VALUES:
            raise ValueError("unsupported recurrence value")
        return raw
    raise ValueError(f"unsupported field {field!r}")


def _validate_value(field: str, value: Any) -> None:
    try:
        coerced = _coerce_value(field, value)
    except (InvalidOperation, ValueError) as error:
        raise ExtractionError(f"invalid {field} value {value!r}") from error
    if coerced != value:
        raise ExtractionError(f"invalid {field} value {value!r}")
