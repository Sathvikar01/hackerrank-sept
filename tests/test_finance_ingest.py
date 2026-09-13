import tempfile
import unittest
from datetime import date
from pathlib import Path

from finance.ingest import Dataset, DatasetError

from tests import finance_fixtures as fixtures


class IngestTests(unittest.TestCase):
    def _fixture(self, root):
        fixtures.write_dataset(
            root,
            profiles=[
                fixtures.profile(user_id="user_01", current_available_balance=fixtures.D("100000")),
                fixtures.profile(user_id="user_02"),
            ],
            requests=[
                fixtures.request(
                    request_id="request_01", user_id="user_01",
                    request_date=date(2026, 1, 10), requested_amount=fixtures.D("5000"),
                    desired_completion_date=date(2026, 2, 10)),
                fixtures.request(
                    request_id="request_02", user_id="user_02",
                    request_date=date(2026, 1, 10), requested_amount=fixtures.D("5000"),
                    desired_completion_date=date(2026, 2, 10)),
            ],
            events=[
                fixtures.event(
                    event_id="event_01", user_id="user_01", event_date=date(2025, 12, 1),
                    settlement_date=date(2025, 12, 1), status="settled", direction="credit",
                    amount=fixtures.D("90000")),
                fixtures.event(
                    event_id="event_02", user_id="user_01", event_date=date(2026, 1, 20),
                    settlement_date=date(2026, 1, 20), status="scheduled",
                    amount=fixtures.D("100")),
                fixtures.event(
                    event_id="event_03", user_id="user_02", event_date=date(2026, 1, 15),
                    settlement_date=date(2026, 1, 15)),
            ],
            options=[
                fixtures.option(
                    option_id="payment_option_01", request_id="request_01",
                    payment_method="full_payment", number_of_payments=1,
                    first_payment_date=date(2026, 1, 10), payment_frequency_days=None,
                    total_payable_amount=fixtures.D("5000"), payment_amount=fixtures.D("5000")),
            ],
            messages=[
                fixtures.message(
                    message_id="message_01", user_id="user_01", request_id="request_01",
                    sent_at=fixtures.datetime(2026, 1, 5, 9, 0, 0)),
                fixtures.message(
                    message_id="message_02", user_id="user_01", request_id="request_01",
                    sent_at=fixtures.datetime(2026, 1, 15, 9, 0, 0)),
                fixtures.message(
                    message_id="message_03", user_id="user_01", request_id="request_02",
                    sent_at=fixtures.datetime(2026, 1, 5, 9, 0, 0)),
                fixtures.message(
                    message_id="message_04", user_id="user_01", request_id=None,
                    sent_at=fixtures.datetime(2026, 1, 1, 9, 0, 0)),
                fixtures.message(
                    message_id="message_05", user_id="user_02", request_id="request_02",
                    sent_at=fixtures.datetime(2026, 1, 5, 9, 0, 0)),
            ],
            images=[
                fixtures.image(image_id="image_01", user_id="user_01", request_id="request_01"),
                fixtures.image(image_id="image_02", user_id="user_02", request_id="request_02"),
            ],
            rates=[
                fixtures.ExchangeRate(
                    rate_date=date(2026, 1, 10), from_currency="USD", to_currency="ZAR",
                    rate=fixtures.D("18")),
            ],
        )
        return Dataset.load(Path(root))

    def test_load_and_scope_join_by_user_and_request(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset = self._fixture(directory)
            scope = dataset.scope("request_01")
            self.assertEqual(scope.request.request_id, "request_01")
            self.assertEqual(scope.profile.user_id, "user_01")
            self.assertEqual(
                [event.event_id for event in scope.events], ["event_01", "event_02"])
            self.assertEqual(
                [option.payment_option_id for option in scope.options], ["payment_option_01"])
            message_ids = [message.message_id for message in scope.messages]
            self.assertEqual(message_ids, ["message_04", "message_01"])
            self.assertNotIn("message_02", message_ids)
            self.assertNotIn("message_03", message_ids)
            self.assertNotIn("message_05", message_ids)
            self.assertEqual([link.image_id for link in scope.images], ["image_01"])
            self.assertEqual(
                scope.image_path("image_01"),
                Path(directory) / "media" / "images" / "image_01.png")

    def test_scope_sorts_options_by_payment_option_id(self):
        with tempfile.TemporaryDirectory() as directory:
            fixtures.write_dataset(
                Path(directory),
                profiles=[fixtures.profile(user_id="user_01")],
                requests=[fixtures.request(request_id="request_01", user_id="user_01")],
                events=[],
                options=[
                    fixtures.option(
                        option_id="payment_option_02", request_id="request_01",
                        payment_method="full_payment", number_of_payments=1,
                        first_payment_date=date(2026, 1, 1), payment_frequency_days=None,
                        payment_amount=fixtures.D("5000"),
                        total_payable_amount=fixtures.D("5000")),
                    fixtures.option(
                        option_id="payment_option_01", request_id="request_01",
                        payment_method="installments"),
                ],
            )
            dataset = Dataset.load(Path(directory))
            scope = dataset.scope("request_01")
            self.assertEqual(
                [option.payment_option_id for option in scope.options],
                ["payment_option_01", "payment_option_02"])

    def test_missing_file_and_unknown_request_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(DatasetError):
                Dataset.load(Path(directory))
            dataset = self._fixture(directory)
            with self.assertRaises(DatasetError):
                dataset.scope("request_99")


if __name__ == "__main__":
    unittest.main()
