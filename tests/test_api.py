import os
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from obd_consultas.api.app import create_app
from obd_consultas.domain.models import QueryResult, QueryStatus, Source


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app())
        self.addCleanup(self.client.close)

    def test_health_and_catalog(self):
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})
        response = self.client.get("/v1/sources")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 4)
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

        def runner(source, plate, timeout):
            called.append((source, plate, timeout))
            return result

        client = TestClient(create_app(stealth_runner=runner))
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
        self.assertEqual(called, [("sunarp", "ABC123", 10)])

    def test_stealth_job_failure_still_returns_query_result(self):
        def broken_runner(source, plate, timeout):
            raise RuntimeError("boom")

        client = TestClient(create_app(stealth_runner=broken_runner))
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

        def runner(source, plate, timeout, browser):
            called.append((source, plate, timeout, browser))
            return result

        client = TestClient(create_app(assisted_runner=runner))
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
        self.assertEqual(called, [("mtc", "ABC123", 10, "chrome")])

    def test_assisted_job_rejects_sources_without_captcha(self):
        response = self.client.post(
            "/v1/queries/assisted", json={"source": "sunarp", "plate": "ABC123"}
        )
        self.assertEqual(response.status_code, 422)

    def test_token_is_required_when_configured(self):
        with patch.dict(os.environ, {"OBD_API_TOKEN": "clave-sintetica"}):
            client = TestClient(
                create_app(
                    stealth_runner=lambda *_: QueryResult(
                        Source.SUNARP, "ABC123", QueryStatus.SUCCESS, "", "ok", {}
                    )
                )
            )
            self.addCleanup(client.close)
            self.assertEqual(client.get("/v1/sources").status_code, 401)
            self.assertEqual(
                client.get("/v1/sources", headers={"X-OBD-Token": "clave-sintetica"}).status_code,
                200,
            )
            self.assertEqual(
                client.post(
                    "/v1/queries/stealth",
                    json={"source": "sunarp", "plate": "ABC123"},
                    headers={"X-OBD-Token": "clave-sintetica"},
                ).status_code,
                202,
            )
