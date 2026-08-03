from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from streamlit.testing.v1 import AppTest

from temu_orders import (
    ORDER_LIST_API,
    TemuAPIConfig,
    TemuOpenAPIClient,
    TemuOrderNoteStore,
    classify_deadline,
    normalize_order_items,
    sign_temu_parameters,
)


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self.payload


class _FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.calls = []

    def post(self, url, *, json, timeout):
        self.calls.append((url, json, timeout))
        return _FakeResponse(self.responses.pop(0))


class TemuOrderTests(unittest.TestCase):
    def test_signature_matches_official_temu_example(self) -> None:
        parameters = {
            "access_token": "2nifvmpyymvypwmcms5ct4uqqudrwgpmzbcnmkt1jzjkuaf3x56iixym",
            "app_key": "f9d5cc9313893a20d5aa85c654e8f503",
            "data_type": "JSON",
            "sendRequestList": [
                {
                    "orderSendInfoList": [
                        {
                            "quantity": 1,
                            "orderSn": "211-21905473070712792",
                            "parentOrderSn": "PO-211-21905452099192792",
                            "goodsId": 601099548666279,
                            "skuId": 17592352673534,
                        }
                    ],
                    "carrierId": "699272611",
                    "trackingNumber": "270324232756",
                }
            ],
            "sendType": 0,
            "timestamp": 1711009072,
            "type": "bg.logistics.shipment.confirm",
        }
        secret = "c7e0a1a63542be4de3cb5488f9fba8149e8fc290"
        self.assertEqual(
            sign_temu_parameters(parameters, secret),
            "4CCF219942D4180C6DDA3CE36C1B838F",
        )

    def test_client_builds_signed_order_request(self) -> None:
        session = _FakeSession(
            [
                {
                    "success": True,
                    "result": {"totalItemNum": 0, "pageItems": []},
                }
            ]
        )
        config = TemuAPIConfig("app", "secret", "token")
        client = TemuOpenAPIClient(config, session=session)
        self.assertEqual(
            client.list_orders(create_after=1, create_before=2),
            [],
        )
        _, payload, _ = session.calls[0]
        self.assertEqual(payload["type"], ORDER_LIST_API)
        self.assertEqual(payload["regionId"], 211)
        self.assertEqual(payload["pageSize"], 100)
        self.assertEqual(len(payload["sign"]), 32)
        self.assertNotIn("app_secret", payload)

    def test_normalize_status_deadline_and_products(self) -> None:
        now = datetime(2026, 8, 3, 12, tzinfo=timezone.utc)
        deadline = int((now + timedelta(hours=3)).timestamp())
        rows = normalize_order_items(
            [
                {
                    "parentOrderMap": {
                        "parentOrderSn": "PO-123",
                        "parentOrderStatus": 2,
                        "expectShipLatestTime": deadline,
                        "parentOrderLabel": [
                            {"name": "soon_to_be_overdue", "value": 1}
                        ],
                    },
                    "orderList": [
                        {
                            "orderSn": "O-1",
                            "goodsName": "Snack box",
                            "spec": "Large",
                            "quantity": 2,
                            "thumbUrl": "https://img.example.com/1.jpg",
                            "fulfillmentType": "fulfillBySeller",
                        }
                    ],
                }
            ],
            timezone_name="UTC",
            notes={"PO-123": "Ưu tiên"},
            now=now,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["deadline_state"], "Sắp trễ")
        self.assertEqual(rows[0]["shipping_progress"], "Chưa giao đơn vị vận chuyển")
        self.assertEqual(rows[0]["products"], "Snack box")
        self.assertEqual(rows[0]["quantity"], 2)
        self.assertEqual(rows[0]["note"], "Ưu tiên")

    def test_package_lookup_falls_back_to_existing_label_list(self) -> None:
        session = _FakeSession(
            [
                {
                    "success": True,
                    "result": {"totalItemNum": 0, "unshippedPackage": []},
                },
                {
                    "success": True,
                    "result": {
                        "totalItemNum": 1,
                        "shippingLabelInfoList": [
                            {"packageSn": "PK-1", "shippingLabelStatus": 1}
                        ],
                    },
                },
            ]
        )
        client = TemuOpenAPIClient(
            TemuAPIConfig("app", "secret", "token"), session=session
        )
        packages = client.get_order_packages(parent_order_sn="PO-1")
        self.assertEqual(packages[0]["packageSn"], "PK-1")
        self.assertEqual(len(session.calls), 2)

    def test_deadline_marks_overdue_and_shipped(self) -> None:
        now = datetime.now(timezone.utc)
        self.assertEqual(
            classify_deadline(2, now - timedelta(minutes=1), now=now),
            "Quá hạn",
        )
        self.assertEqual(classify_deadline(4, None, now=now), "Đã giao đi")

    def test_note_store_persists_and_removes_local_note(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TemuOrderNoteStore(Path(directory) / "notes.json")
            saved = store.save_note("PO-1", "Kiểm tra địa chỉ")
            self.assertEqual(saved["notes"]["PO-1"], "Kiểm tra địa chỉ")
            self.assertEqual(store.load()["notes"]["PO-1"], "Kiểm tra địa chỉ")
            store.save_note("PO-1", "")
            self.assertNotIn("PO-1", store.load()["notes"])

    def test_page_shows_safe_setup_when_temu_secret_is_missing(self) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        app = AppTest.from_file(
            project_dir / "app_pages" / "temu_orders.py",
            default_timeout=30,
        )
        app.secrets = {"admin": {"password": "test"}}
        app.session_state["admin_authenticated"] = True
        app.run()
        self.assertEqual([], list(app.exception))
        self.assertGreaterEqual(len(app.warning), 1)
        self.assertIn("Chưa kết nối Temu Open API", app.warning[0].value)

    def test_page_renders_query_form_without_calling_api(self) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        app = AppTest.from_file(
            project_dir / "app_pages" / "temu_orders.py",
            default_timeout=30,
        )
        app.secrets = {
            "admin": {"password": "test"},
            "temu": {
                "app_key": "app",
                "app_secret": "secret",
                "access_token": "token",
            },
        }
        app.session_state["admin_authenticated"] = True
        app.run()
        self.assertEqual([], list(app.exception))
        self.assertEqual(len(app.date_input), 1)
        self.assertIn("Kiểm tra đơn Temu", app.button[0].label)

    def test_app_registers_temu_orders_route(self) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        source = (project_dir / "app.py").read_text(encoding="utf-8")
        self.assertIn('url_path="temu-orders"', source)
        self.assertIn("temu_orders_page", source)


if __name__ == "__main__":
    unittest.main()
