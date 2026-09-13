from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from .contracts import (
    ContractError,
    ExchangeRate,
    FinancialEvent,
    ImageLink,
    Message,
    MissingRateError,
    PaymentOption,
    Profile,
    ScopedRequest,
)


class DatasetError(RuntimeError):
    pass


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise DatasetError(f"missing dataset file: {path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise DatasetError(f"dataset file has no header: {path}")
        return [row for row in reader]


def _index(rows: list[Any], key: str, label: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in rows:
        identifier = getattr(item, key)
        if identifier in result:
            raise DatasetError(f"{label}: duplicate id {identifier}")
        result[identifier] = item
    return result


@dataclass(frozen=True)
class RateBook:
    rates: tuple[ExchangeRate, ...] = ()

    def direct_rate(self, from_currency: str, to_currency: str, day: date) -> Decimal | None:
        for rate in self.rates:
            if rate.rate_date == day and rate.from_currency == from_currency \
                    and rate.to_currency == to_currency:
                return rate.rate
        return None

    def rate(self, from_currency: str, to_currency: str, day: date,
             *, allow_inverse: bool = False) -> Decimal:
        if from_currency == to_currency:
            return Decimal(1)
        direct = self.direct_rate(from_currency, to_currency, day)
        if direct is not None:
            return direct
        if allow_inverse:
            inverse = self.direct_rate(to_currency, from_currency, day)
            if inverse is not None and inverse != 0:
                return Decimal(1) / inverse
        raise MissingRateError(
            f"no {from_currency}->{to_currency} rate for {day.isoformat()}")

    def convert(self, amount: Decimal, from_currency: str, to_currency: str, day: date,
                *, allow_inverse: bool = False) -> Decimal:
        if from_currency == to_currency:
            return amount
        return amount * self.rate(from_currency, to_currency, day,
                                  allow_inverse=allow_inverse)


@dataclass(frozen=True)
class RequestScope:
    request: ScopedRequest
    profile: Profile
    events: tuple[FinancialEvent, ...]
    messages: tuple[Message, ...]
    images: tuple[ImageLink, ...]
    options: tuple[PaymentOption, ...]
    rate_book: RateBook
    dataset_root: Path

    def image_path(self, image_id: str) -> Path:
        return Path(self.dataset_root) / "media" / "images" / f"{image_id}.png"

    def event_by_id(self, event_id: str) -> FinancialEvent | None:
        for event in self.events:
            if event.event_id == event_id:
                return event
        return None


@dataclass(frozen=True)
class Dataset:
    root: Path
    profiles: Mapping[str, Profile]
    requests: Mapping[str, ScopedRequest]
    events_by_user: Mapping[str, tuple[FinancialEvent, ...]]
    options_by_request: Mapping[str, tuple[PaymentOption, ...]]
    messages_by_user: Mapping[str, tuple[Message, ...]]
    images_by_user: Mapping[str, tuple[ImageLink, ...]]
    rate_book: RateBook

    @classmethod
    def load(cls, root: Path | str) -> "Dataset":
        root = Path(root)
        profiles = _index(
            [Profile.from_row(row) for row in _read_rows(root / "financial_profiles.csv")],
            "user_id", "financial_profiles",
        )
        requests = _index(
            [ScopedRequest.from_row(row) for row in _read_rows(root / "requests.csv")],
            "request_id", "requests",
        )
        events: dict[str, list[FinancialEvent]] = defaultdict(list)
        for event in (FinancialEvent.from_row(row) for row in _read_rows(root / "financial_events.csv")):
            events[event.user_id].append(event)
        options: dict[str, list[PaymentOption]] = defaultdict(list)
        for option in (
            PaymentOption.from_row(row)
            for row in _read_rows(root / "request_payment_options.csv")
        ):
            options[option.request_id].append(option)
        messages: dict[str, list[Message]] = defaultdict(list)
        for message in (Message.from_row(row) for row in _read_rows(root / "messages.csv")):
            messages[message.user_id].append(message)
        images: dict[str, list[ImageLink]] = defaultdict(list)
        for link in (ImageLink.from_row(row) for row in _read_rows(root / "images.csv")):
            images[link.user_id].append(link)
        rate_book = RateBook(tuple(
            ExchangeRate.from_row(row) for row in _read_rows(root / "exchange_rates.csv")))

        dataset = cls(
            root=root,
            profiles=profiles,
            requests=requests,
            events_by_user={
                user: tuple(sorted(items, key=lambda item: (item.effective_date, item.event_id)))
                for user, items in events.items()
            },
            options_by_request={
                request_id: tuple(sorted(items, key=lambda item: item.payment_option_id))
                for request_id, items in options.items()
            },
            messages_by_user={
                user: tuple(sorted(items, key=lambda item: (item.sent_at, item.message_id)))
                for user, items in messages.items()
            },
            images_by_user={
                user: tuple(sorted(items, key=lambda item: item.image_id))
                for user, items in images.items()
            },
            rate_book=rate_book,
        )
        for request in dataset.requests.values():
            if request.user_id not in dataset.profiles:
                raise DatasetError(
                    f"{request.request_id}: unknown user {request.user_id}")
        return dataset

    def scope(self, request_id: str) -> RequestScope:
        request = self.requests.get(request_id)
        if request is None:
            raise DatasetError(f"unknown request_id: {request_id}")
        profile = self.profiles[request.user_id]
        events = self.events_by_user.get(request.user_id, ())
        event_ids = {event.event_id for event in events}
        messages = tuple(
            message
            for message in self.messages_by_user.get(request.user_id, ())
            if message.sent_at.date() <= request.request_date
            and (message.request_id is None or message.request_id == request.request_id)
        )
        images = tuple(
            link
            for link in self.images_by_user.get(request.user_id, ())
            if link.request_id == request.request_id
            or (link.request_id is None and link.related_event_id in event_ids)
        )
        options = self.options_by_request.get(request.request_id, ())
        return RequestScope(
            request=request,
            profile=profile,
            events=events,
            messages=messages,
            images=images,
            options=options,
            rate_book=self.rate_book,
            dataset_root=self.root,
        )
