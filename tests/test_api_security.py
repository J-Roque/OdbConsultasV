import threading
import unittest

from fastapi.testclient import TestClient
from obd_consultas.api.app import create_app
from obd_consultas.api.security import ApiSettings, RateLimiter, token_problem
from obd_consultas.domain.models import QueryResult, QueryStatus, Source

TOKEN = "token-sintetico-de-pruebas-0123456789abcdef"


def _ok(*_args):
    return QueryResult(Source.SUNARP, "ABC123", QueryStatus.SUCCESS, "", "ok", {})


def _client(settings, **kwargs):
    kwargs.setdefault("stealth_runner", _ok)
    kwargs.setdefault("assisted_runner", _ok)
    return TestClient(create_app(settings=settings, **kwargs))


class AuthTests(unittest.TestCase):
    def test_fails_closed_without_valid_token(self):
        for token in (None, "", "corto"):
            with self.subTest(token=token):
                client = _client(ApiSettings(api_token=token))
                self.addCleanup(client.close)
                self.assertEqual(client.get("/v1/sources").status_code, 503)
                self.assertEqual(
                    client.get("/v1/sources", headers={"X-OBD-Token": token or ""}).status_code,
                    503,
                )
                self.assertEqual(client.get("/health").status_code, 200)

    def test_rejects_missing_or_wrong_token(self):
        client = _client(ApiSettings(api_token=TOKEN))
        self.addCleanup(client.close)
        self.assertEqual(client.get("/v1/sources").status_code, 401)
        self.assertEqual(
            client.get("/v1/sources", headers={"X-OBD-Token": TOKEN + "x"}).status_code, 401
        )
        self.assertEqual(client.get("/v1/jobs/abc", headers={"X-OBD-Token": "nope"}).status_code, 401)
        self.assertEqual(client.get("/v1/sources", headers={"X-OBD-Token": TOKEN}).status_code, 200)

    def test_every_v1_route_requires_token(self):
        client = _client(ApiSettings(api_token=TOKEN, enable_assisted=True))
        self.addCleanup(client.close)
        checked = 0
        for route in client.app.routes:
            path = getattr(route, "path", "")
            if not path.startswith("/v1/"):
                continue
            for method in route.methods:
                with self.subTest(method=method, path=path):
                    url = path.replace("{job_id}", "abc")
                    response = client.request(method, url, json={"source": "soat", "plate": "ABC123"})
                    self.assertEqual(response.status_code, 401)
                    checked += 1
        self.assertGreaterEqual(checked, 5)

    def test_token_problem(self):
        self.assertIsNotNone(token_problem(None))
        self.assertIsNotNone(token_problem("x" * 31))
        self.assertIsNone(token_problem("x" * 32))


class HardeningTests(unittest.TestCase):
    def test_docs_disabled_by_default(self):
        client = _client(ApiSettings(api_token=TOKEN))
        self.addCleanup(client.close)
        for path in ("/docs", "/redoc", "/openapi.json"):
            with self.subTest(path=path):
                self.assertEqual(client.get(path).status_code, 404)

    def test_docs_can_be_enabled(self):
        client = _client(ApiSettings(api_token=TOKEN, enable_docs=True))
        self.addCleanup(client.close)
        self.assertEqual(client.get("/openapi.json").status_code, 200)

    def test_assisted_disabled_by_default(self):
        client = _client(ApiSettings(api_token=TOKEN))
        self.addCleanup(client.close)
        response = client.post(
            "/v1/queries/assisted",
            json={"source": "mtc", "plate": "ABC123"},
            headers={"X-OBD-Token": TOKEN},
        )
        self.assertEqual(response.status_code, 403)

    def test_rate_limit_applies_before_auth(self):
        client = _client(ApiSettings(api_token=TOKEN, rate_limit_per_minute=3))
        self.addCleanup(client.close)
        codes = [
            client.get("/v1/sources", headers={"X-OBD-Token": "malo"}).status_code for _ in range(4)
        ]
        self.assertEqual(codes, [401, 401, 401, 429])
        blocked = client.get("/v1/sources", headers={"X-OBD-Token": TOKEN})
        self.assertEqual(blocked.status_code, 429)
        self.assertIn("Retry-After", blocked.headers)

    def test_active_jobs_are_limited(self):
        release = threading.Event()

        def slow(*_args):
            release.wait(5)
            return _ok()

        client = TestClient(
            create_app(settings=ApiSettings(api_token=TOKEN, max_active_jobs=2), stealth_runner=slow),
            headers={"X-OBD-Token": TOKEN},
        )
        self.addCleanup(client.close)
        self.addCleanup(release.set)
        body = {"source": "sunarp", "plate": "ABC123", "timeout": 10}
        codes = [client.post("/v1/queries/stealth", json=body).status_code for _ in range(3)]
        self.assertEqual(codes, [202, 202, 429])

    def test_sensitive_responses_are_not_cached(self):
        client = _client(ApiSettings(api_token=TOKEN))
        self.addCleanup(client.close)
        response = client.get("/v1/sources", headers={"X-OBD-Token": TOKEN})
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")


class SettingsTests(unittest.TestCase):
    def test_from_env(self):
        settings = ApiSettings.from_env(
            {"OBD_API_TOKEN": f"  {TOKEN} ", "OBD_API_DOCS": "1", "OBD_API_RATE_LIMIT": "10"}
        )
        self.assertEqual(settings.api_token, TOKEN)
        self.assertTrue(settings.enable_docs)
        self.assertFalse(settings.enable_assisted)
        self.assertEqual(settings.rate_limit_per_minute, 10)

    def test_from_env_rejects_bad_numbers(self):
        for value in ("abc", "0"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ApiSettings.from_env({"OBD_API_RATE_LIMIT": value})


class RateLimiterTests(unittest.TestCase):
    def test_window_slides(self):
        now = [0.0]
        limiter = RateLimiter(2, 60, clock=lambda: now[0])
        self.assertEqual(limiter.retry_after("a"), 0)
        self.assertEqual(limiter.retry_after("a"), 0)
        self.assertGreater(limiter.retry_after("a"), 0)
        self.assertEqual(limiter.retry_after("b"), 0)
        now[0] = 61
        self.assertEqual(limiter.retry_after("a"), 0)


if __name__ == "__main__":
    unittest.main()
