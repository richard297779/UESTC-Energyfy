import unittest
from unittest.mock import patch

from uestc_energy import api


class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.requests = 0

    def get(self, *args, **kwargs):
        self.requests += 1
        return FakeResponse(self.payloads.pop(0))


class ApiTests(unittest.TestCase):
    def test_direct_balance(self):
        session = FakeSession([
            {"e": 0, "m": "操作成功", "d": {"fjh": "A-101", "syje": 12.5, "sydl": 30}},
        ])

        data, signed = api._once(session)

        self.assertEqual(data["syje"], 12.5)
        self.assertEqual(signed, "")

    def test_signed_proxy_response(self):
        session = FakeSession([
            {"e": 0, "m": "操作成功", "d": {"url": "https://example.test/query"}},
        ])

        data, signed = api._once(session)

        self.assertIsNone(data)
        self.assertEqual(signed, "https://example.test/query")

    def test_business_message_is_not_reported_as_parse_error(self):
        session = FakeSession([
            {"e": 0, "m": "操作成功", "d": "学生住宿信息不存在"},
        ])

        with self.assertRaisesRegex(api.TransientQueryError, "住宿绑定"):
            api._once(session)
        self.assertEqual(session.requests, 1)

    def test_retry_recovers_after_transient_business_error(self):
        session = FakeSession([
            {"e": 0, "m": "操作成功", "d": "学生住宿信息不存在"},
            {"e": 0, "m": "操作成功", "d": {"fjh": "A-101", "syje": 9.5}},
        ])

        with patch("uestc_energy.api.time.sleep"):
            result = api.query(session, seconds=1)

        self.assertEqual(result["balance"], 9.5)
        self.assertEqual(session.requests, 2)

    def test_signed_proxy_is_fetched_immediately(self):
        session = FakeSession([
            {"e": 0, "m": "操作成功", "d": {"url": "https://example.test/query"}},
            {"e": 0, "m": "操作成功", "d": {"fjh": "A-101", "syje": 8.5}},
        ])

        result = api.query(session, seconds=1)

        self.assertEqual(result["balance"], 8.5)
        self.assertEqual(result["source"], "proxy")
        self.assertEqual(session.requests, 2)

    def test_direct_response_without_balance_fields(self):
        session = FakeSession([
            {"e": 0, "m": "操作成功", "d": {"fjh": "A-101"}},
        ])

        with self.assertRaisesRegex(api.QueryError, "未返回余额字段"):
            api._once(session)


if __name__ == "__main__":
    unittest.main()
