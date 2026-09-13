from __future__ import annotations

import csv
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from finance.contracts import (
    ExchangeRate,
    FinancialEvent,
    ImageLink,
    Message,
    PaymentOption,
    Profile,
    ScopedRequest,
)
from finance.forecast import ForecastPolicy
from finance.ingest import RateBook, RequestScope


def D(value) -> Decimal:
    return Decimal(str(value))


def profile(**overrides) -> Profile:
    data = dict(
        user_id="user_01",
        home_currency="ZAR",
        current_available_balance=D("100000"),
        minimum_balance_to_keep=D("10000"),
        financial_priorities=(),
        protected_categories=(),
        reduce_categories=(),
        stop_categories=(),
        payment_methods=("full_payment", "partial_payment", "installments"),
        max_installment_months=12,
    )
    data.update(overrides)
    return Profile(**data)


def request(**overrides) -> ScopedRequest:
    data = dict(
        request_id="request_01",
        user_id="user_01",
        request_date=date(2026, 1, 1),
        request_type="purchase",
        requested_amount=D("5000"),
        desired_completion_date=date(2026, 2, 1),
        allows_partial_payment=True,
        request_text="Can I buy this?",
    )
    data.update(overrides)
    return ScopedRequest(**data)


def event(event_id: str = "event_01", **overrides) -> FinancialEvent:
    data = dict(
        event_id=event_id,
        user_id="user_01",
        event_type="expense",
        description="Groceries",
        category="groceries",
        direction="debit",
        amount=D("100"),
        currency="ZAR",
        event_date=date(2026, 1, 5),
        settlement_date=date(2026, 1, 5),
        status="scheduled",
        linked_event_id=None,
        flexibility="fixed",
        minimum_allowed_amount=None,
    )
    data.update(overrides)
    return FinancialEvent(**data)


def option(option_id: str = "payment_option_01", **overrides) -> PaymentOption:
    data = dict(
        payment_option_id=option_id,
        request_id="request_01",
        payment_method="installments",
        payment_amount=D("1000"),
        number_of_payments=3,
        first_payment_date=date(2026, 1, 1),
        payment_frequency_days=30,
        financing_fee=D("0"),
        total_payable_amount=D("3000"),
    )
    data.update(overrides)
    return PaymentOption(**data)


def message(message_id: str = "message_01", **overrides) -> Message:
    data = dict(
        message_id=message_id,
        user_id="user_01",
        request_id="request_01",
        related_event_id=None,
        sent_at=datetime(2026, 1, 1, 9, 0, 0),
        source_type="employer",
        text="Sample message",
    )
    data.update(overrides)
    return Message(**data)


def image(image_id: str = "image_01", **overrides) -> ImageLink:
    data = dict(
        image_id=image_id,
        user_id="user_01",
        request_id="request_01",
        related_event_id=None,
    )
    data.update(overrides)
    return ImageLink(**data)


def scope(
    events=(),
    messages=(),
    images=(),
    options=(),
    profile: Profile | None = None,
    request: ScopedRequest | None = None,
    rates=(),
    dataset_root: Path | None = None,
) -> RequestScope:
    return RequestScope(
        request=request or globals()["request"](),
        profile=profile or globals()["profile"](),
        events=tuple(events),
        messages=tuple(messages),
        images=tuple(images),
        options=tuple(options),
        rate_book=RateBook(tuple(rates)),
        dataset_root=dataset_root or Path("dataset"),
    )


def no_variable_policy(**overrides) -> ForecastPolicy:
    data = dict(variable_spending_enabled=False)
    data.update(overrides)
    return ForecastPolicy(**data)


def write_dataset(
    root: Path,
    profiles=(),
    requests=(),
    events=(),
    options=(),
    messages=(),
    images=(),
    rates=(),
) -> Path:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    _write(root / "financial_profiles.csv", [
        "user_id", "home_currency", "current_available_balance", "minimum_balance_to_keep",
        "financial_priorities", "expense_categories_to_protect",
        "expense_categories_user_is_willing_to_reduce", "expense_categories_user_is_willing_to_stop",
        "payment_methods_user_will_consider", "max_installment_months",
    ], [
        [
            item.user_id, item.home_currency, str(item.current_available_balance),
            str(item.minimum_balance_to_keep), "|".join(item.financial_priorities),
            "|".join(item.protected_categories), "|".join(item.reduce_categories),
            "|".join(item.stop_categories), "|".join(item.payment_methods),
            "" if item.max_installment_months is None else str(item.max_installment_months),
        ]
        for item in profiles
    ])
    _write(root / "requests.csv", [
        "request_id", "user_id", "request_date", "request_type", "requested_amount",
        "desired_completion_date", "allows_partial_payment", "request_text",
    ], [
        [
            item.request_id, item.user_id, item.request_date.isoformat(), item.request_type,
            str(item.requested_amount), item.desired_completion_date.isoformat(),
            "true" if item.allows_partial_payment else "false", item.request_text,
        ]
        for item in requests
    ])
    _write(root / "financial_events.csv", [
        "event_id", "user_id", "event_type", "description", "category", "direction", "amount",
        "currency", "event_date", "settlement_date", "status", "linked_event_id",
        "flexibility", "minimum_allowed_amount",
    ], [
        [
            item.event_id, item.user_id, item.event_type, item.description, item.category,
            item.direction, "" if item.amount is None else str(item.amount), item.currency,
            item.event_date.isoformat(),
            "" if item.settlement_date is None else item.settlement_date.isoformat(),
            item.status, item.linked_event_id or "",
            item.flexibility or "",
            "" if item.minimum_allowed_amount is None else str(item.minimum_allowed_amount),
        ]
        for item in events
    ])
    _write(root / "request_payment_options.csv", [
        "payment_option_id", "request_id", "payment_method", "payment_amount",
        "number_of_payments", "first_payment_date", "payment_frequency_days",
        "financing_fee", "total_payable_amount",
    ], [
        [
            item.payment_option_id, item.request_id, item.payment_method,
            str(item.payment_amount), str(item.number_of_payments),
            item.first_payment_date.isoformat(),
            "" if item.payment_frequency_days is None else str(item.payment_frequency_days),
            str(item.financing_fee), str(item.total_payable_amount),
        ]
        for item in options
    ])
    _write(root / "messages.csv", [
        "message_id", "user_id", "request_id", "related_event_id", "sent_at", "source_type",
        "message_text",
    ], [
        [
            item.message_id, item.user_id, item.request_id or "", item.related_event_id or "",
            item.sent_at.strftime("%Y-%m-%dT%H:%M:%SZ"), item.source_type, item.text,
        ]
        for item in messages
    ])
    _write(root / "images.csv", [
        "image_id", "user_id", "request_id", "related_event_id",
    ], [
        [item.image_id, item.user_id, item.request_id or "", item.related_event_id or ""]
        for item in images
    ])
    _write(root / "exchange_rates.csv", [
        "rate_date", "from_currency", "to_currency", "rate",
    ], [
        [item.rate_date.isoformat(), item.from_currency, item.to_currency, str(item.rate)]
        for item in rates
    ])
    return root


def _write(path: Path, header, rows) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
