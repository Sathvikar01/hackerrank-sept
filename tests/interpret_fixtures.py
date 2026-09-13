from __future__ import annotations

import base64
import json
import re
from datetime import date
from typing import Mapping, Sequence

from interpret.extractor import EvidenceExtractor
from interpret.providers import ChatResponse, ProviderError

from tests import finance_fixtures as ff

TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


class FakeChatClient:
    def __init__(self, responses: Mapping[str, str], *, fail: bool = False,
                 fail_times: int = 0,
                 error: str = "provider returned empty content; increase max_tokens",
                 sequence: Sequence[str] | None = None):
        self.responses = dict(responses)
        self.fail = fail
        self.fail_times = fail_times
        self.error = error
        self.sequence = list(sequence) if sequence is not None else None
        self.calls: list[dict] = []

    def complete(self, *, model: str, system: str, user: str, images: Sequence[str] = (),
                 max_tokens: int = 4096) -> ChatResponse:
        self.calls.append({"model": model, "user": user, "images": tuple(images),
                           "max_tokens": max_tokens})
        if self.fail:
            raise ProviderError("scripted provider failure")
        if self.fail_times > 0:
            self.fail_times -= 1
            raise ProviderError(self.error)
        if self.sequence:
            text = self.sequence.pop(0)
            return ChatResponse(
                text=text, model=model, prompt_tokens=100, completion_tokens=50,
                latency_s=0.05)
        marker = re.search(r"SOURCE_ID:\s*(\S+)", user)
        key = marker.group(1) if marker else None
        text = self.responses.get(key)
        if text is None:
            raise AssertionError(f"no scripted response for source {key!r}")
        return ChatResponse(
            text=text, model=model, prompt_tokens=100, completion_tokens=50, latency_s=0.05)


def claims_json(claims: Sequence[Mapping]) -> str:
    return json.dumps({"claims": list(claims)})


def claim_payload(
    *,
    field: str = "amount",
    value=50000,
    lifecycle: str = "amend",
    event_ref: str | None = "event_01",
    evidence: str = "amended amount",
    confidence: float | None = 0.9,
) -> dict:
    payload = {
        "field": field,
        "value": value,
        "lifecycle": lifecycle,
        "event_ref": event_ref,
        "evidence_span": evidence,
    }
    if confidence is not None:
        payload["confidence"] = confidence
    return payload


def make_extraction(source_kind: str, source_id: str, claims, *,
                    model: str = "fake/primary", error: str | None = None):
    from interpret.schemas import Extraction, ModelCallRecord

    call = ModelCallRecord(
        model=model, purpose="extraction", prompt_tokens=1, completion_tokens=1,
        latency_s=0.0, source_id=source_id)
    return Extraction(
        model=model, source_kind=source_kind, source_id=source_id,
        claims=tuple(claims), call=call, error=error)


def extractor(responses: Mapping[str, str], *, model: str = "fake/primary") -> EvidenceExtractor:
    return EvidenceExtractor(FakeChatClient(responses), model=model)


def claims_from(payloads, *, source_id: str = "message_01",
                observed_at=date(2026, 1, 2), source_kind: str = "message"):
    from interpret.schemas import parse_claims

    return parse_claims(
        claims_json(payloads), source_kind=source_kind, source_id=source_id,
        user_id="user_01", request_id="request_01", observed_at=observed_at)


def make_engine(root, *, variable_spending: bool = False):
    from finance.engine import FinancialEngine
    from finance.forecast import ForecastPolicy
    from finance.ingest import Dataset

    dataset = Dataset.load(root)
    engine = FinancialEngine(
        dataset, ForecastPolicy(variable_spending_enabled=variable_spending))
    return dataset, engine


def simple_dataset(root, *, balance="100000", minimum="10000", requested="45000",
                   events=(), messages=(), images=(), options=(), methods=("full_payment",),
                   allows_partial=True, desired=date(2026, 2, 1),
                   stop_categories=(), reduce_categories=()):
    root = ff.write_dataset(
        root,
        profiles=[ff.profile(
            user_id="user_01", current_available_balance=ff.D(balance),
            minimum_balance_to_keep=ff.D(minimum), payment_methods=methods,
            stop_categories=stop_categories, reduce_categories=reduce_categories)],
        requests=[ff.request(
            request_id="request_01", user_id="user_01", request_date=date(2026, 1, 1),
            requested_amount=ff.D(requested), desired_completion_date=desired,
            allows_partial_payment=allows_partial)],
        events=list(events),
        messages=list(messages),
        images=list(images),
        options=list(options),
    )
    for link in images:
        target = root / "media" / "images" / f"{link.image_id}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(TINY_PNG)
    return root
