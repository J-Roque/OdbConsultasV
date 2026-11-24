import time
import unittest

from fastapi.testclient import TestClient

from obd_consultas.api.app import create_app
from obd_consultas.api.security import ApiSettings
from obd_consultas.application.queries import QueryService
from obd_consultas.bootstrap import PROVIDERS, RUNNERS
from obd_consultas.domain.models import QueryMode, QueryResult, QueryStatus, Source

TOKEN = "token-sintetico-de-pruebas-0123456789abcdef"
SETTINGS = ApiSettings(api_token=TOKEN, enable_assisted=True, rate_limit_per_minute=1000)


def make_client(settings=SETTINGS, **runners):
    service = fake_service(**runners) if runners else None
    return TestClient(create_app(service, settings=settings), headers={"X-OBD-Token": TOKEN})


def fake_service(stealth=None, assisted=None):
    """Servicio real con la misma matriz fuente/modo, pero runners sinteticos."""
    fakes = {QueryMode.STEALTH: stealth, QueryMode.ASSISTED: assisted}
    runners = {
        key: fakes[key[1]] or _unused_runner
        for key in RUNNERS
    }
    return QueryService((PROVIDERS[s]() for s in PROVIDERS), runners)


def _unused_runner(plate, timeout, **options):
    raise AssertionError("runner no esperado en esta prueba")


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = make_client()
        self.addCleanup(self.client.close)

    def test_health_and_catalog(self):
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})
        response = self.client.get("/v1/sources")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 6)
        by_source = {item["source"]: item for item in response.json()}
        self.assertTrue(by_source["soat"]["implemented"])
        self.assertTrue(by_source["sunarp"]["implemented"])
        self.assertTrue(by_source["mtc"]["implemented"])
        self.assertFalse(by_source["sutran"]["implemented"])

    def test_soat_requires_interaction_without_opening_browser(self):
        response = self.client.post("/v1/queries", json={"source": "soat", "plate": "abc-123"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "requires_interaction")
        self.assertEqual(response.json()["plate"], "ABC123")

    def test_sunarp_requires_interaction_without_opening_browser(self):
        response = self.client.post("/v1/queries", json={"source": "sunarp", "plate": "abc-123"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "requires_interaction")
        self.assertEqual(response.json()["plate"], "ABC123")

    def test_invalid_request(self):
        for payload in ({"source": "soat", "plate": "??"},
                        {"source": "unknown", "plate": "ABC123"}):
            with self.subTest(payload=payload):
                self.assertEqual(self.client.post("/v1/queries", json=payload).status_code, 422)

    def test_stealth_job_returns_real_result(self):
        result = QueryResult(
            Source.SUNARP,
            "ABC123",
            QueryStatus.SUCCESS,
            "https://consultavehicular.sunarp.gob.pe/",
            "Consulta sintetica",
            {"tarjeta": {"formato": "png"}},
        )
        called = []

        def runner(plate, timeout, **options):
            called.append((plate, timeout))
            return result

        client = make_client(stealth=runner)
        self.addCleanup(client.close)
        created = client.post(
            "/v1/queries/stealth",
            json={"source": "sunarp", "plate": "abc-123", "timeout": 10},
        )
        self.assertEqual(created.status_code, 202)
        job = created.json()
        self.assertIn(job["state"], {"pending", "running", "done"})
        self.assertEqual(job["poll_url"], f"/v1/jobs/{job['job_id']}")

        for _ in range(100):
            response = client.get(job["poll_url"])
            if response.json()["state"] == "done":
                break
            time.sleep(0.02)
        body = response.json()
        self.assertEqual(body["state"], "done")
        self.assertEqual(body["result"]["status"], "success")
        self.assertEqual(body["result"]["data"], {"tarjeta": {"formato": "png"}})
        self.assertEqual(called, [("ABC123", 10)])

    def test_stealth_job_failure_still_returns_query_result(self):
        def broken_runner(plate, timeout, **options):
            raise RuntimeError("boom")

        client = make_client(stealth=broken_runner)
        self.addCleanup(client.close)
        created = client.post(
            "/v1/queries/stealth", json={"source": "soat", "plate": "ABC123"}
        )
        for _ in range(100):
            response = client.get(created.json()["poll_url"])
            if response.json()["state"] == "done":
                break
            time.sleep(0.02)
        self.assertEqual(response.json()["result"]["status"], "unavailable")

    def test_stealth_job_rejects_bad_input(self):
        for payload in (
            {"source": "unknown", "plate": "ABC123"},
            {"source": "sunarp", "plate": "??"},
            {"source": "sunarp", "plate": "ABC123", "timeout": 1},
        ):
            with self.subTest(payload=payload):
                response = self.client.post("/v1/queries/stealth", json=payload)
                self.assertEqual(response.status_code, 422)

    def test_unknown_job_is_404(self):
        self.assertEqual(self.client.get("/v1/jobs/no-existe").status_code, 404)

    def test_assisted_job_returns_real_result(self):
        result = QueryResult(
            Source.MTC,
            "ABC123",
            QueryStatus.SUCCESS,
            "https://portal.mtc.gob.pe/",
            "Consulta sintetica",
            {"registros": []},
        )
        called = []

        def runner(plate, timeout, **options):
            called.append((plate, timeout, options["browser"]))
            return result

        client = make_client(assisted=runner)
        self.addCleanup(client.close)
        created = client.post(
            "/v1/queries/assisted",
            json={"source": "mtc", "plate": "abc-123", "timeout": 10, "browser": "chrome"},
        )
        self.assertEqual(created.status_code, 202)
        for _ in range(100):
            body = client.get(created.json()["poll_url"]).json()
            if body["state"] == "done":
                break
            time.sleep(0.02)
        self.assertEqual(body["result"]["status"], "success")
        self.assertEqual(called, [("ABC123", 10, "chrome")])

    def test_assisted_job_rejects_sources_without_captcha(self):
        response = self.client.post(
            "/v1/queries/assisted", json={"source": "sunarp", "plate": "ABC123"}
        )
        self.assertEqual(response.status_code, 422)
