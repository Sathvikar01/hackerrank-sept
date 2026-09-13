from __future__ import annotations

import json
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping, Protocol, Sequence, TypedDict

from langgraph.graph import END, StateGraph

from .certificate import json_safe
from .extractor import EvidenceExtractor
from .schemas import (
    ExtractedClaim,
    Extraction,
    ExtractionError,
    InterpretationSet,
    ModelCallRecord,
    parse_model_json,
)

TOOL_NAMES = (
    "reread_message",
    "reinspect_image",
    "contradiction_check",
    "lifecycle_check",
    "missing_field_check",
    "image_message_consistency",
    "inspect_attachment_candidates",
)

CONTROLLER_SYSTEM = (
    "You are a bounded verification controller for a financial evidence pipeline. "
    "Choose exactly one allowlisted verification action that reduces the most important "
    "uncertainty, or stop when no further check is useful. Never perform financial "
    "arithmetic and never approve payments. Return strict JSON only."
)


@dataclass(frozen=True)
class VerificationPolicy:
    max_turns: int = 3
    max_actions: int = 3


@dataclass(frozen=True)
class VerificationOutcome:
    ran: bool
    turns: int
    actions: int
    checks: tuple[Mapping[str, Any], ...]
    new_claims: tuple[ExtractedClaim, ...]
    hard_stop: bool
    unresolved: tuple[str, ...]


class VerificationController(Protocol):
    def choose_action(self, state: Mapping[str, Any]) -> Any:
        ...


class ScriptedController:
    def __init__(self, actions: Sequence[Any]) -> None:
        self.actions = list(actions)
        self.calls = 0

    def choose_action(self, state: Mapping[str, Any]) -> Any:
        self.calls += 1
        if not self.actions:
            return {"action": "stop"}
        item = self.actions.pop(0)
        return item(state) if callable(item) else item


class ModelVerificationController:
    def __init__(self, client, model: str, *, max_tokens: int = 1024) -> None:
        self.client = client
        self.model = model
        self.max_tokens = max_tokens

    def choose_action(self, state: Mapping[str, Any]) -> Any:
        prompt = json.dumps({
            "task": "choose one allowlisted verification action or stop",
            "allowed_actions": list(TOOL_NAMES),
            "state": json_safe(dict(state)),
        })
        response = self.client.complete(
            model=self.model, system=CONTROLLER_SYSTEM, user=prompt,
            max_tokens=self.max_tokens)
        return parse_model_json(response.text)


class VerificationState(TypedDict):
    request_id: str
    turns: int
    actions: int
    checks: list
    new_claims: list
    hard_stop: bool
    done: bool
    pending: dict | None
    ambiguous: list


def run_verification(
    scope,
    sets: Sequence[InterpretationSet],
    *,
    controller: VerificationController,
    tools: Mapping[str, Any],
    policy: VerificationPolicy | None = None,
) -> VerificationOutcome:
    policy = policy or VerificationPolicy()
    ambiguous = [
        {
            "event_ref": item.event_ref,
            "field": item.field,
            "values": [json_safe(value) for value in item.values],
            "unresolved": item.unresolved,
        }
        for item in sets
        if item.ambiguous
    ]
    initial: VerificationState = {
        "request_id": scope.request.request_id,
        "turns": 0,
        "actions": 0,
        "checks": [],
        "new_claims": [],
        "hard_stop": False,
        "done": False,
        "pending": None,
        "ambiguous": ambiguous,
    }
    graph = _build_graph(controller, tools, policy)
    try:
        final = graph.invoke(initial, {"recursion_limit": 2 * policy.max_turns + 4})
    except Exception as error:  # noqa: BLE001
        return VerificationOutcome(
            ran=True, turns=policy.max_turns, actions=0,
            checks=({"status": "graph_error", "error": str(error)[:200]},),
            new_claims=(), hard_stop=True,
            unresolved=(f"verification graph error: {error}",))
    unresolved = _unresolved_notes(final)
    return VerificationOutcome(
        ran=True,
        turns=int(final["turns"]),
        actions=int(final["actions"]),
        checks=tuple(final["checks"]),
        new_claims=tuple(final["new_claims"]),
        hard_stop=bool(final["hard_stop"]),
        unresolved=unresolved,
    )


def _build_graph(controller: VerificationController, tools: Mapping[str, Any],
                 policy: VerificationPolicy):
    def decide(state: VerificationState) -> VerificationState:
        if state["done"] or state["turns"] >= policy.max_turns:
            return {**state, "done": True, "hard_stop": True, "pending": None}
        updated = {**state, "turns": state["turns"] + 1}
        snapshot = {
            "request_id": updated["request_id"],
            "turns": updated["turns"],
            "actions": updated["actions"],
            "ambiguous": updated["ambiguous"],
            "checks": updated["checks"],
        }
        try:
            proposed = controller.choose_action(snapshot)
        except Exception as error:  # noqa: BLE001
            updated["checks"] = [*updated["checks"], {
                "status": "controller_error", "error": str(error)[:200]}]
            return updated
        if not isinstance(proposed, Mapping):
            updated["checks"] = [*updated["checks"], {
                "status": "invalid",
                "reason": "controller response was not an object"}]
            return updated
        action = proposed.get("action")
        if action == "stop":
            return {**updated, "done": True, "pending": None}
        if action not in TOOL_NAMES or action not in tools:
            updated["checks"] = [*updated["checks"], {
                "status": "invalid",
                "reason": f"action {action!r} is not allowlisted"}]
            return updated
        if updated["actions"] >= policy.max_actions:
            return {**updated, "done": True, "hard_stop": True, "pending": None}
        return {**updated, "pending": dict(proposed)}

    def act(state: VerificationState) -> VerificationState:
        pending = state["pending"] or {}
        try:
            result = tools[pending["action"]](pending)
        except Exception as error:  # noqa: BLE001
            result = {"status": "tool_error", "error": str(error)[:200]}
        if not isinstance(result, Mapping):
            result = {"result": result}
        claims = result.get("claims") if isinstance(result, Mapping) else None
        action_count = state["actions"] + 1
        updated: VerificationState = {
            **state,
            "actions": action_count,
            "checks": [*state["checks"], json_safe({
                "status": "executed", "action": pending["action"], **dict(result)})],
            "new_claims": [*state["new_claims"], *list(claims or [])],
            "pending": None,
            "hard_stop": state["hard_stop"] or action_count >= policy.max_actions,
        }
        return updated

    def route(state: VerificationState):
        if state["done"] or state["hard_stop"]:
            return END
        if state["pending"] is None:
            return "decide"
        return "act"

    builder = StateGraph(VerificationState)
    builder.add_node("decide", decide)
    builder.add_node("act", act)
    builder.set_entry_point("decide")
    builder.add_conditional_edges("decide", route, {"decide": "decide", "act": "act", END: END})
    builder.add_edge("act", "decide")
    return builder.compile()


def _unresolved_notes(state: VerificationState) -> tuple[str, ...]:
    notes: list[str] = []
    if state["hard_stop"]:
        notes.append("verification hard stop: uncertainty preserved")
    for check in state["checks"]:
        if check.get("status") == "invalid":
            notes.append(f"invalid controller action: {check.get('reason', '')}")
    for axis in state["ambiguous"]:
        notes.append(
            f"ambiguous {axis['event_ref']}:{axis['field']} values={axis['values']}")
    return tuple(dict.fromkeys(notes))


def default_tools(scope, claims: Sequence[ExtractedClaim], *,
                  extractor: EvidenceExtractor | None = None,
                  verification_extractor: EvidenceExtractor | None = None,
                  attachment_outcomes: Sequence = ()) -> Mapping[str, Any]:
    def find_event(action: Mapping[str, Any]):
        return scope.event_by_id(str(action.get("event_id", "")))

    def _verification_question(action: Mapping[str, Any], default: str) -> str:
        for key in ("question", "uncertainty", "reason"):
            value = action.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:500]
        return default

    def missing_field_check(action: Mapping[str, Any]) -> Mapping[str, Any]:
        event = find_event(action)
        if event is None:
            return {"result": "unknown event", "missing_fields": []}
        missing = ["amount"] if event.amount is None else []
        if event.status in {"settled", "scheduled"} and event.settlement_date is None:
            missing.append("settlement_date")
        return {"event_id": event.event_id, "status": event.status,
                "missing_fields": missing}

    def contradiction_check(action: Mapping[str, Any]) -> Mapping[str, Any]:
        event_id = str(action.get("event_id", ""))
        grouped: dict[str, list[dict[str, Any]]] = {}
        for claim in claims:
            if claim.event_ref != event_id:
                continue
            grouped.setdefault(claim.field, []).append({
                "value": json_safe(claim.value),
                "source": f"{claim.source_kind}:{claim.source_id}",
                "lifecycle": claim.lifecycle,
                "confidence": json_safe(claim.confidence),
            })
        contradictions = {
            field: entries for field, entries in grouped.items()
            if len({entry["value"] for entry in entries}) > 1
        }
        return {"event_id": event_id, "claims_by_field": grouped,
                "contradictions": contradictions}

    def lifecycle_check(action: Mapping[str, Any]) -> Mapping[str, Any]:
        event = find_event(action)
        if event is None:
            return {"result": "unknown event"}
        linked = [
            other.event_id for other in scope.events
            if other.linked_event_id == event.event_id
            or other.event_id == event.linked_event_id
        ]
        return {"event_id": event.event_id, "status": event.status,
                "direction": event.direction, "linked_events": linked}

    def image_message_consistency(action: Mapping[str, Any]) -> Mapping[str, Any]:
        event_id = str(action.get("event_id", ""))
        image_values = sorted({
            json_safe(claim.value) for claim in claims
            if claim.event_ref == event_id and claim.source_kind == "image"})
        message_values = sorted({
            json_safe(claim.value) for claim in claims
            if claim.event_ref == event_id and claim.source_kind == "message"})
        consistent = (
            not image_values or not message_values or image_values == message_values)
        return {"event_id": event_id, "image_values": image_values,
                "message_values": message_values, "consistent": consistent}

    def reread_message(action: Mapping[str, Any]) -> Mapping[str, Any]:
        source_id = str(action.get("source_id", ""))
        message = next(
            (item for item in scope.messages if item.message_id == source_id), None)
        if message is None:
            return {"result": "unknown message"}
        payload: dict[str, Any] = {
            "message_id": message.message_id,
            "text": message.text[:500],
            "sent_at": message.sent_at.isoformat(),
        }
        reader = verification_extractor or extractor
        if reader is not None:
            try:
                # A distinct verification question and prompt: never a cached
                # replay of the original extraction.
                extraction: Extraction = reader.extract_message(
                    scope, message,
                    question=_verification_question(
                        action,
                        "Report exactly which financial facts this message states, "
                        "with amounts, dates, currencies, and the transaction or "
                        "series it refers to."))
                payload["claims"] = list(extraction.claims)
                payload["rejected"] = list(extraction.rejected)
            except ExtractionError as error:
                payload["error"] = str(error)
        return payload

    def reinspect_image(action: Mapping[str, Any]) -> Mapping[str, Any]:
        source_id = str(action.get("source_id", ""))
        link = next(
            (item for item in scope.images if item.image_id == source_id), None)
        if link is None:
            return {"result": "unknown image"}
        reader = verification_extractor or extractor
        if reader is None:
            return {"result": "no extractor configured"}
        try:
            extraction = reader.extract_image(
                scope, link,
                event_ref=action.get("event_ref") or link.related_event_id,
                question=_verification_question(
                    action,
                    "Report exactly which labeled amounts, currencies, dates, and "
                    "document fields this image shows."))
        except ExtractionError as error:
            return {"status": "tool_error", "error": str(error)}
        return {"image_id": link.image_id, "claims": list(extraction.claims),
                "rejected": list(extraction.rejected)}

    def inspect_attachment_candidates(action: Mapping[str, Any]) -> Mapping[str, Any]:
        claim_id = str(action.get("claim_id", ""))
        source_id = str(action.get("source_id", ""))
        found = next(
            (item for item in attachment_outcomes if item.claim.claim_id == claim_id),
            None)
        if found is None and source_id:
            found = next(
                (item for item in attachment_outcomes if item.claim.source_id == source_id),
                None)
        if found is None:
            return {"result": "unknown claim", "candidates": []}
        return {
            "claim_id": found.claim.claim_id,
            "state": found.state,
            "event_id": found.event_id,
            "candidates": list(found.candidates),
            "reasons": list(found.reasons),
            "evidence": found.claim.evidence[:200],
        }

    return {
        "missing_field_check": missing_field_check,
        "contradiction_check": contradiction_check,
        "lifecycle_check": lifecycle_check,
        "image_message_consistency": image_message_consistency,
        "reread_message": reread_message,
        "reinspect_image": reinspect_image,
        "inspect_attachment_candidates": inspect_attachment_candidates,
    }
