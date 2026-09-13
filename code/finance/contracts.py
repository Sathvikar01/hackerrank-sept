from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable, Mapping, Sequence


class ContractError(ValueError):
    pass


class UnresolvedFactError(ContractError):
    pass


class MissingAmountError(UnresolvedFactError):
    pass


class MissingRateError(UnresolvedFactError):
    pass


SUPPORTED_CURRENCIES = frozenset({"INR", "ZAR", "IDR", "USD", "EUR"})

REQUEST_TYPES = frozenset({
    "purchase", "travel", "education", "family_transfer", "debt_repayment",
    "investment", "housing", "emergency_expense", "other",
})
EVENT_TYPES = frozenset({
    "expense", "income", "debt_payment", "subscription", "refund",
    "investment_purchase", "investment_sale", "investment_valuation",
})
DIRECTIONS = frozenset({"credit", "debit", "non_cash"})
EVENT_STATUSES = frozenset({
    "settled", "pending", "scheduled", "failed", "cancelled", "unrealized",
})
FLEXIBILITIES = frozenset({"fixed", "reducible", "stoppable", "reducible_or_stoppable"})
PAYMENT_METHODS = frozenset({"full_payment", "partial_payment", "installments"})
OUTPUT_PAYMENT_METHODS = frozenset({
    "full_payment", "partial_payment", "installments", "wait", "not_recommended",
})
AFFORDABILITY_STATUSES = frozenset({
    "affordable_now", "affordable_with_plan", "affordable_later", "not_affordable",
})
CHANGE_KINDS = frozenset({"stop", "reduce_to"})
CLAIM_KINDS = frozenset({
    "assertion", "estimate", "amendment", "cancellation", "settlement",
    "delay", "confirmation",
})
GROUNDINGS = frozenset({"settled", "structured", "message", "image", "estimate"})

OUTPUT_COLUMNS = [
    "request_id",
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
    "decision_explanation",
]

_ID_RE = re.compile(r"^[a-z][a-z_]*_\d+$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?$")

CENT = Decimal("0.01")


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_text(value: Any, field_name: str, *, required: bool = True) -> str | None:
    text = _clean(value)
    if text is None:
        if required:
            raise ContractError(f"{field_name}: missing required text")
        return None
    return text


def parse_id(value: Any, field_name: str, *, prefix: str | None = None,
             required: bool = True) -> str | None:
    text = parse_text(value, field_name, required=required)
    if text is None:
        return None
    if not _ID_RE.match(text):
        raise ContractError(f"{field_name}: malformed id {text!r}")
    if prefix is not None and not text.startswith(prefix + "_"):
        raise ContractError(f"{field_name}: expected {prefix}_... id, got {text!r}")
    return text


def parse_date(value: Any, field_name: str, *, required: bool = True) -> date | None:
    text = _clean(value)
    if text is None:
        if required:
            raise ContractError(f"{field_name}: missing required date")
        return None
    if not _DATE_RE.match(text):
        raise ContractError(f"{field_name}: malformed date {text!r}")
    try:
        return date.fromisoformat(text)
    except ValueError as error:
        raise ContractError(f"{field_name}: invalid date {text!r}") from error


def parse_datetime(value: Any, field_name: str, *, required: bool = True) -> datetime | None:
    text = _clean(value)
    if text is None:
        if required:
            raise ContractError(f"{field_name}: missing required timestamp")
        return None
    if not _DATETIME_RE.match(text):
        raise ContractError(f"{field_name}: malformed timestamp {text!r}")
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ContractError(f"{field_name}: invalid timestamp {text!r}") from error


def parse_decimal(value: Any, field_name: str, *, required: bool = True) -> Decimal | None:
    text = _clean(value)
    if text is None:
        if required:
            raise MissingAmountError(f"{field_name}: missing required amount")
        return None
    try:
        parsed = Decimal(text)
    except InvalidOperation as error:
        raise ContractError(f"{field_name}: malformed decimal {text!r}") from error
    if not parsed.is_finite():
        raise ContractError(f"{field_name}: non-finite decimal {text!r}")
    return parsed


def parse_int(value: Any, field_name: str, *, required: bool = True) -> int | None:
    text = _clean(value)
    if text is None:
        if required:
            raise ContractError(f"{field_name}: missing required integer")
        return None
    try:
        return int(text)
    except ValueError as error:
        raise ContractError(f"{field_name}: malformed integer {text!r}") from error


def parse_bool(value: Any, field_name: str, *, required: bool = True) -> bool | None:
    text = _clean(value)
    if text is None:
        if required:
            raise ContractError(f"{field_name}: missing required boolean")
        return None
    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    raise ContractError(f"{field_name}: malformed boolean {text!r}")


def parse_choice(value: Any, field_name: str, allowed: Iterable[str],
                 *, required: bool = True) -> str | None:
    text = parse_text(value, field_name, required=required)
    if text is None:
        return None
    if text not in allowed:
        raise ContractError(f"{field_name}: unsupported value {text!r}")
    return text


def parse_currency(value: Any, field_name: str = "currency") -> str:
    text = parse_text(value, field_name)
    if text not in SUPPORTED_CURRENCIES:
        raise ContractError(f"{field_name}: unsupported currency {text!r}")
    return text


def parse_pipe_list(value: Any) -> tuple[str, ...]:
    text = _clean(value)
    if text is None:
        return ()
    return tuple(part.strip() for part in text.split("|") if part.strip())


def money_to_string(value: Decimal) -> str:
    if not value.is_finite():
        raise ContractError("money_to_string: non-finite amount")
    quantized = value.quantize(CENT, rounding=ROUND_HALF_UP)
    if quantized == quantized.to_integral_value():
        return str(quantized.quantize(Decimal(1)))
    return format(quantized.normalize(), "f")


@dataclass(frozen=True)
class Provenance:
    source: str
    record_id: str
    locator: str
    excerpt: str | None = None


@dataclass(frozen=True)
class Profile:
    user_id: str
    home_currency: str
    current_available_balance: Decimal
    minimum_balance_to_keep: Decimal
    financial_priorities: tuple[str, ...] = ()
    protected_categories: tuple[str, ...] = ()
    reduce_categories: tuple[str, ...] = ()
    stop_categories: tuple[str, ...] = ()
    payment_methods: tuple[str, ...] = ()
    max_installment_months: int | None = None

    def __post_init__(self) -> None:
        parse_id(self.user_id, "user_id", prefix="user")
        parse_currency(self.home_currency, "home_currency")
        if self.current_available_balance < 0:
            raise ContractError("current_available_balance: must not be negative")
        if self.minimum_balance_to_keep < 0:
            raise ContractError("minimum_balance_to_keep: must not be negative")
        unknown = set(self.payment_methods) - PAYMENT_METHODS
        if unknown:
            raise ContractError(f"payment_methods_user_will_consider: unsupported {sorted(unknown)}")
        if self.max_installment_months is not None and self.max_installment_months <= 0:
            raise ContractError("max_installment_months: must be positive when present")

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Profile":
        return cls(
            user_id=parse_id(row.get("user_id"), "user_id", prefix="user"),
            home_currency=parse_currency(row.get("home_currency")),
            current_available_balance=parse_decimal(
                row.get("current_available_balance"), "current_available_balance"),
            minimum_balance_to_keep=parse_decimal(
                row.get("minimum_balance_to_keep"), "minimum_balance_to_keep"),
            financial_priorities=parse_pipe_list(row.get("financial_priorities")),
            protected_categories=parse_pipe_list(row.get("expense_categories_to_protect")),
            reduce_categories=parse_pipe_list(row.get("expense_categories_user_is_willing_to_reduce")),
            stop_categories=parse_pipe_list(row.get("expense_categories_user_is_willing_to_stop")),
            payment_methods=parse_pipe_list(row.get("payment_methods_user_will_consider")),
            max_installment_months=parse_int(
                row.get("max_installment_months"), "max_installment_months", required=False),
        )


@dataclass(frozen=True)
class ScopedRequest:
    request_id: str
    user_id: str
    request_date: date
    request_type: str
    requested_amount: Decimal
    desired_completion_date: date
    allows_partial_payment: bool
    request_text: str

    def __post_init__(self) -> None:
        parse_id(self.request_id, "request_id", prefix="request")
        parse_id(self.user_id, "user_id", prefix="user")
        parse_choice(self.request_type, "request_type", REQUEST_TYPES)
        if self.requested_amount <= 0:
            raise ContractError("requested_amount: must be positive")
        if self.desired_completion_date < self.request_date:
            raise ContractError("desired_completion_date: must not precede request_date")

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "ScopedRequest":
        return cls(
            request_id=parse_id(row.get("request_id"), "request_id", prefix="request"),
            user_id=parse_id(row.get("user_id"), "user_id", prefix="user"),
            request_date=parse_date(row.get("request_date"), "request_date"),
            request_type=parse_choice(row.get("request_type"), "request_type", REQUEST_TYPES),
            requested_amount=parse_decimal(row.get("requested_amount"), "requested_amount"),
            desired_completion_date=parse_date(
                row.get("desired_completion_date"), "desired_completion_date"),
            allows_partial_payment=parse_bool(
                row.get("allows_partial_payment"), "allows_partial_payment"),
            request_text=parse_text(row.get("request_text"), "request_text"),
        )


@dataclass(frozen=True)
class FinancialEvent:
    event_id: str
    user_id: str
    event_type: str
    description: str
    category: str
    direction: str
    amount: Decimal | None
    currency: str
    event_date: date
    settlement_date: date | None
    status: str
    linked_event_id: str | None = None
    flexibility: str | None = None
    minimum_allowed_amount: Decimal | None = None

    def __post_init__(self) -> None:
        parse_id(self.event_id, "event_id", prefix="event")
        parse_id(self.user_id, "user_id", prefix="user")
        parse_choice(self.event_type, "event_type", EVENT_TYPES)
        parse_choice(self.direction, "direction", DIRECTIONS)
        parse_choice(self.status, "status", EVENT_STATUSES)
        parse_currency(self.currency)
        if self.amount is not None and self.amount <= 0:
            raise ContractError(f"{self.event_id}: amount must be positive when present")
        if self.minimum_allowed_amount is not None and self.minimum_allowed_amount < 0:
            raise ContractError(f"{self.event_id}: minimum_allowed_amount must not be negative")
        if self.flexibility is not None:
            parse_choice(self.flexibility, "flexibility", FLEXIBILITIES)
        if self.linked_event_id is not None:
            parse_id(self.linked_event_id, "linked_event_id", prefix="event")
            if self.linked_event_id == self.event_id:
                raise ContractError(f"{self.event_id}: linked_event_id must not self-reference")

    @property
    def is_cash(self) -> bool:
        return self.direction in {"credit", "debit"} and self.event_type != "investment_valuation"

    @property
    def effective_date(self) -> date:
        return self.settlement_date or self.event_date

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "FinancialEvent":
        return cls(
            event_id=parse_id(row.get("event_id"), "event_id", prefix="event"),
            user_id=parse_id(row.get("user_id"), "user_id", prefix="user"),
            event_type=parse_choice(row.get("event_type"), "event_type", EVENT_TYPES),
            description=parse_text(row.get("description"), "description"),
            category=parse_text(row.get("category"), "category"),
            direction=parse_choice(row.get("direction"), "direction", DIRECTIONS),
            amount=parse_decimal(row.get("amount"), "amount", required=False),
            currency=parse_currency(row.get("currency")),
            event_date=parse_date(row.get("event_date"), "event_date"),
            settlement_date=parse_date(
                row.get("settlement_date"), "settlement_date", required=False),
            status=parse_choice(row.get("status"), "status", EVENT_STATUSES),
            linked_event_id=parse_id(
                row.get("linked_event_id"), "linked_event_id", prefix="event", required=False),
            flexibility=parse_choice(
                row.get("flexibility"), "flexibility", FLEXIBILITIES, required=False),
            minimum_allowed_amount=parse_decimal(
                row.get("minimum_allowed_amount"), "minimum_allowed_amount", required=False),
        )


@dataclass(frozen=True)
class PaymentOption:
    payment_option_id: str
    request_id: str
    payment_method: str
    payment_amount: Decimal
    number_of_payments: int
    first_payment_date: date
    payment_frequency_days: int | None
    financing_fee: Decimal
    total_payable_amount: Decimal

    def __post_init__(self) -> None:
        parse_id(self.payment_option_id, "payment_option_id", prefix="payment_option")
        parse_id(self.request_id, "request_id", prefix="request")
        parse_choice(self.payment_method, "payment_method", PAYMENT_METHODS)
        if self.payment_amount <= 0:
            raise ContractError(f"{self.payment_option_id}: payment_amount must be positive")
        if self.number_of_payments < 1:
            raise ContractError(f"{self.payment_option_id}: number_of_payments must be >= 1")
        if self.payment_frequency_days is not None and self.payment_frequency_days <= 0:
            raise ContractError(
                f"{self.payment_option_id}: payment_frequency_days must be positive when present")
        if self.payment_method == "installments" and self.number_of_payments > 1 \
                and self.payment_frequency_days is None:
            raise ContractError(
                f"{self.payment_option_id}: installments need payment_frequency_days")
        if self.financing_fee < 0:
            raise ContractError(f"{self.payment_option_id}: financing_fee must not be negative")
        scheduled = self.payment_amount * self.number_of_payments
        if self.total_payable_amount + CENT < scheduled:
            raise ContractError(
                f"{self.payment_option_id}: total_payable_amount below scheduled payments")

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "PaymentOption":
        return cls(
            payment_option_id=parse_id(
                row.get("payment_option_id"), "payment_option_id", prefix="payment_option"),
            request_id=parse_id(row.get("request_id"), "request_id", prefix="request"),
            payment_method=parse_choice(row.get("payment_method"), "payment_method", PAYMENT_METHODS),
            payment_amount=parse_decimal(row.get("payment_amount"), "payment_amount"),
            number_of_payments=parse_int(row.get("number_of_payments"), "number_of_payments"),
            first_payment_date=parse_date(row.get("first_payment_date"), "first_payment_date"),
            payment_frequency_days=parse_int(
                row.get("payment_frequency_days"), "payment_frequency_days", required=False),
            financing_fee=parse_decimal(row.get("financing_fee"), "financing_fee"),
            total_payable_amount=parse_decimal(
                row.get("total_payable_amount"), "total_payable_amount"),
        )


@dataclass(frozen=True)
class Message:
    message_id: str
    user_id: str
    request_id: str | None
    related_event_id: str | None
    sent_at: datetime
    source_type: str
    text: str

    def __post_init__(self) -> None:
        parse_id(self.message_id, "message_id", prefix="message")
        parse_id(self.user_id, "user_id", prefix="user")
        if self.request_id is not None:
            parse_id(self.request_id, "request_id", prefix="request")
        if self.related_event_id is not None:
            parse_id(self.related_event_id, "related_event_id", prefix="event")

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Message":
        return cls(
            message_id=parse_id(row.get("message_id"), "message_id", prefix="message"),
            user_id=parse_id(row.get("user_id"), "user_id", prefix="user"),
            request_id=parse_id(row.get("request_id"), "request_id", prefix="request",
                                required=False),
            related_event_id=parse_id(row.get("related_event_id"), "related_event_id",
                                      prefix="event", required=False),
            sent_at=parse_datetime(row.get("sent_at"), "sent_at"),
            source_type=parse_text(row.get("source_type"), "source_type"),
            text=parse_text(row.get("message_text"), "message_text"),
        )


@dataclass(frozen=True)
class ImageLink:
    image_id: str
    user_id: str
    request_id: str | None
    related_event_id: str | None

    def __post_init__(self) -> None:
        parse_id(self.image_id, "image_id", prefix="image")
        parse_id(self.user_id, "user_id", prefix="user")
        if self.request_id is not None:
            parse_id(self.request_id, "request_id", prefix="request")
        if self.related_event_id is not None:
            parse_id(self.related_event_id, "related_event_id", prefix="event")

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "ImageLink":
        return cls(
            image_id=parse_id(row.get("image_id"), "image_id", prefix="image"),
            user_id=parse_id(row.get("user_id"), "user_id", prefix="user"),
            request_id=parse_id(row.get("request_id"), "request_id", prefix="request",
                                required=False),
            related_event_id=parse_id(row.get("related_event_id"), "related_event_id",
                                      prefix="event", required=False),
        )


@dataclass(frozen=True)
class ExchangeRate:
    rate_date: date
    from_currency: str
    to_currency: str
    rate: Decimal

    def __post_init__(self) -> None:
        parse_currency(self.from_currency, "from_currency")
        parse_currency(self.to_currency, "to_currency")
        if self.from_currency == self.to_currency:
            raise ContractError("exchange rate: from_currency and to_currency must differ")
        if self.rate <= 0:
            raise ContractError("exchange rate: rate must be positive")

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "ExchangeRate":
        return cls(
            rate_date=parse_date(row.get("rate_date"), "rate_date"),
            from_currency=parse_currency(row.get("from_currency"), "from_currency"),
            to_currency=parse_currency(row.get("to_currency"), "to_currency"),
            rate=parse_decimal(row.get("rate"), "rate"),
        )


@dataclass(frozen=True)
class FactClaim:
    claim_id: str
    fact_ref: str
    field_name: str
    value: Any
    claim_kind: str
    grounding: str
    source_id: str
    observed_at: date
    provenance: Provenance

    def __post_init__(self) -> None:
        parse_text(self.claim_id, "claim_id")
        parse_text(self.fact_ref, "fact_ref")
        parse_text(self.field_name, "field_name")
        parse_choice(self.claim_kind, "claim_kind", CLAIM_KINDS)
        parse_choice(self.grounding, "grounding", GROUNDINGS)
        parse_text(self.source_id, "source_id")


@dataclass(frozen=True)
class ResolvedFact:
    fact_ref: str
    field_name: str
    accepted: FactClaim | None
    alternatives: tuple[FactClaim, ...]
    unresolved: bool
    reason: str = ""


@dataclass(frozen=True)
class CanonicalFact:
    fact_id: str
    fact_ref: str
    field_name: str
    value: Any
    source_kind: str
    provenance: tuple[Provenance, ...]

    def __post_init__(self) -> None:
        parse_text(self.fact_id, "fact_id")
        parse_text(self.fact_ref, "fact_ref")
        parse_text(self.field_name, "field_name")
        parse_text(self.source_kind, "source_kind")


@dataclass(frozen=True)
class PlanEntry:
    payment_date: date
    amount: Decimal

    def __post_init__(self) -> None:
        if self.amount <= 0:
            raise ContractError("plan entry: amount must be positive")


@dataclass(frozen=True)
class ChangeAction:
    kind: str
    event_id: str
    new_amount: Decimal | None = None

    def __post_init__(self) -> None:
        parse_choice(self.kind, "change kind", CHANGE_KINDS)
        parse_id(self.event_id, "change event_id", prefix="event")
        if self.kind == "stop":
            if self.new_amount is not None:
                raise ContractError("stop change must not carry a new amount")
        else:
            if self.new_amount is None:
                raise ContractError("reduce_to change requires a new amount")
            if self.new_amount < 0:
                raise ContractError("reduce_to amount must not be negative")

    @classmethod
    def stop(cls, event_id: str) -> "ChangeAction":
        return cls(kind="stop", event_id=event_id)

    @classmethod
    def reduce_to(cls, event_id: str, new_amount: Decimal) -> "ChangeAction":
        return cls(kind="reduce_to", event_id=event_id, new_amount=new_amount)

    def to_string(self) -> str:
        if self.kind == "stop":
            return f"stop:{self.event_id}"
        return f"reduce_to:{self.event_id}:{money_to_string(self.new_amount)}"


@dataclass(frozen=True)
class PaymentPlan:
    method: str
    status: str
    entries: tuple[PlanEntry, ...] = ()
    changes: tuple[ChangeAction, ...] = ()
    option_id: str | None = None

    def __post_init__(self) -> None:
        parse_choice(self.method, "payment method", OUTPUT_PAYMENT_METHODS)
        parse_choice(self.status, "affordability status", AFFORDABILITY_STATUSES)
        if self.option_id is not None:
            parse_id(self.option_id, "payment_option_id", prefix="payment_option")
        ordered = sorted(self.entries, key=lambda entry: entry.payment_date)
        if list(self.entries) != ordered:
            raise ContractError("payment plan entries must be chronological")
        stop_events = {c.event_id for c in self.changes if c.kind == "stop"}
        reduce_events = {c.event_id for c in self.changes if c.kind == "reduce_to"}
        if stop_events & reduce_events:
            raise ContractError("a plan must not stop and reduce the same event")

    def total_paid(self) -> Decimal:
        return sum((entry.amount for entry in self.entries), Decimal(0))

    def start_date(self) -> date | None:
        return self.entries[0].payment_date if self.entries else None

    def to_string(self) -> str:
        if not self.entries:
            return "none"
        return "|".join(
            f"{entry.payment_date.isoformat()}:{money_to_string(entry.amount)}"
            for entry in self.entries)


@dataclass(frozen=True)
class Decision:
    request_id: str
    amount_safe_to_pay: Decimal
    plan: PaymentPlan
    earliest_date_for_full_payment: date | None
    decision_explanation: str
    unresolved: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        parse_id(self.request_id, "request_id", prefix="request")
        if self.amount_safe_to_pay < 0:
            raise ContractError("amount_safe_to_pay must not be negative")

    @property
    def affordability_status(self) -> str:
        return self.plan.status

    @property
    def recommended_payment_method(self) -> str:
        return self.plan.method

    @property
    def payment_plan(self) -> str:
        return self.plan.to_string()

    @property
    def spending_changes_needed(self) -> str:
        if not self.plan.changes:
            return "none"
        return "|".join(change.to_string() for change in self.plan.changes)

    def to_row(self) -> dict[str, str]:
        return {
            "request_id": self.request_id,
            "amount_safe_to_pay": money_to_string(self.amount_safe_to_pay),
            "affordability_status": self.affordability_status,
            "recommended_payment_method": self.recommended_payment_method,
            "payment_plan": self.payment_plan,
            "earliest_date_for_full_payment": (
                self.earliest_date_for_full_payment.isoformat()
                if self.earliest_date_for_full_payment else ""),
            "spending_changes_needed": self.spending_changes_needed,
            "decision_explanation": self.decision_explanation,
        }


@dataclass(frozen=True)
class BalancePoint:
    day: date
    balance: Decimal


@dataclass(frozen=True)
class ForecastResult:
    start: date
    end: date
    start_balance: Decimal
    minimum_required: Decimal
    points: tuple[BalancePoint, ...]
    minimum: Decimal
    minimum_date: date
    end_balance: Decimal
    safe: bool

    def balance_on(self, day: date) -> Decimal:
        balance = self.start_balance
        for point in self.points:
            if point.day <= day:
                balance = point.balance
            else:
                break
        return balance


@dataclass(frozen=True)
class VerificationInput:
    request_id: str
    decision: Decision
    accepted_facts: tuple[CanonicalFact, ...]
    plan_entries: tuple[PlanEntry, ...]
    balance_points: tuple[BalancePoint, ...]
    minimum_projected_balance: Decimal
    minimum_required: Decimal
    checks: tuple[str, ...]
    unresolved: tuple[ResolvedFact, ...] = ()
