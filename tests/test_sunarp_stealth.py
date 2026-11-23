"""Pruebas del modo sigiloso de SUNARP con dobles; no abren navegadores."""
import unittest
from unittest.mock import patch

from obd_consultas.domain.models import QueryStatus
from obd_consultas.infrastructure import sunarp_stealth
from obd_consultas.infrastructure.scrapling_engine import ScraplingUnavailable
from obd_consultas.infrastructure.sunarp_stealth import (
    _observe,
    _result_from_holder,
    query_sunarp_stealth,
)

API_URL = "https://api-gateway.sunarp.gob.pe:9443/sunarp/multiservicios/multiservicio-consvehicular/consulta/getDatosVehiculo"
PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def payload():
    return {
        "cod": 1,
        "mensaje": "Placa encontrada satisfactoriamente",
        "mensajeTxt": "",
        "model": {
            "imagen": PNG_BASE64,
            "msgAlertaRobo": "",
            "sedes": [
                {
                    "prefijo": "OR0101",
                    "regPubId": "01",
                    "oficRegId": "01",
                    "nombre": "LIMA",
                    "fgBaja": "0",
                    "placa": "ABC123 ",
                    "numPartida": "50190361",
                }
            ],
        },
    }


def dom_capture():
    return {
        "format": "sunarp-dom-v1",
        "source_url": "https://consultavehicular.sunarp.gob.pe/consulta-vehicular/inicio",
        "image": "data:image/png;base64," + PNG_BASE64,
        "alert": "",
        "rows": [["1", "ABC123", "50190361", "LIMA"]],
    }


class FakeResponse:
    def __init__(self, url, status=200, payload=None):
        self.url = url
        self.status = status
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("La respuesta no es JSON.")
        return self._payload


class FakeLocator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector

    def fill(self, value, timeout=None):
        self.page.filled = value

    def click(self, timeout=None):
        if self.selector == "button" and self.page.response is not None:
            for handler in list(self.page.handlers):
                handler(self.page.response)

    def count(self):
        return self.page.visible.get(self.selector, 0)

    @property
    def first(self):
        return self

    def inner_text(self):
        return self.page.popup


class FakePage:
    def __init__(self, response=None, visible=None, popup="", dom=None):
        self.handlers = []
        self.response = response
        self.visible = visible or {}
        self.popup = popup
        self.dom = dom
        self.filled = None
        self.waited = None

    def on(self, event, handler):
        self.handlers.append(handler)

    def wait_for_selector(self, selector, timeout=None):
        self.waited = selector

    def locator(self, selector):
        return FakeLocator(self, selector)

    def get_by_role(self, role, name, exact):
        return FakeLocator(self, "button")

    def wait_for_timeout(self, milliseconds):
        return None

    def evaluate(self, script):
        return self.dom


class FakeSession:
    def __init__(self, page):
        self.page = page

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def fetch(self, url, **kwargs):
        kwargs["page_action"](self.page)
        return None


class SunarpStealthTests(unittest.TestCase):
    def setUp(self):
        # El OCR real se prueba por separado; aqui solo se comprueba el flujo.
        patcher = patch.object(
            sunarp_stealth,
            "attach_tive_ocr",
            side_effect=lambda result, image: result,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_drives_form_and_parses_api_json(self):
        page = FakePage(FakeResponse(API_URL, 200, payload()))
        holder = {}
        _observe(page, "ABC123", 1_000, holder)
        self.assertEqual(page.filled, "ABC123")
        result = _result_from_holder("ABC123", holder)
        self.assertEqual(result.status, QueryStatus.SUCCESS)
        self.assertEqual(result.data["capture"]["method"], "stealth_api")
        self.assertTrue(result.data["plate_verified"])

    def test_dom_fallback_when_json_is_not_available(self):
        page = FakePage(visible={".container-data-vehiculo img": 1}, dom=dom_capture())
        holder = {}
        _observe(page, "ABC123", 1_000, holder)
        result = _result_from_holder("ABC123", holder)
        self.assertEqual(result.status, QueryStatus.SUCCESS)
        self.assertEqual(result.data["capture"]["method"], "stealth_dom")

    def test_captcha_requests_interaction(self):
        page = FakePage(visible={".swal2-popup": 1}, popup="Captcha no resuelto")
        holder = {}
        _observe(page, "ABC123", 30, holder)
        result = _result_from_holder("ABC123", holder)
        self.assertEqual(result.status, QueryStatus.REQUIRES_INTERACTION)
        self.assertIn("Turnstile", result.message)

    def test_timeout_requests_interaction(self):
        page = FakePage()
        holder = {}
        _observe(page, "ABC123", 30, holder)
        result = _result_from_holder("ABC123", holder)
        self.assertEqual(result.status, QueryStatus.REQUIRES_INTERACTION)

    def test_http_403_requests_interaction(self):
        result = _result_from_holder("ABC123", {"status": 403, "payload": None})
        self.assertEqual(result.status, QueryStatus.REQUIRES_INTERACTION)

    def test_browser_failure_is_unavailable(self):
        result = _result_from_holder("ABC123", {"error": RuntimeError("fallo")})
        self.assertEqual(result.status, QueryStatus.UNAVAILABLE)
        self.assertEqual(result.data, {})

    def test_missing_browser_points_to_install_command(self):
        def broken_session(**_):
            raise RuntimeError("Executable doesn't exist at /tmp/chromium")

        result = query_sunarp_stealth("ABC123", 10, session_factory=broken_session)
        self.assertEqual(result.status, QueryStatus.UNAVAILABLE)
        self.assertIn("install-browsers", result.message)

    def test_missing_dependency_is_reported(self):
        def unavailable_session(**_):
            raise ScraplingUnavailable("Scrapling no esta instalado.")

        result = query_sunarp_stealth("ABC123", 10, session_factory=unavailable_session)
        self.assertEqual(result.status, QueryStatus.UNAVAILABLE)
        self.assertIn("Scrapling", result.message)

    def test_retries_fresh_session_when_turnstile_fails(self):
        states = [
            {"captcha": "Captcha no resuelto"},
            {"status": 200, "payload": payload()},
        ]
        sessions = []

        def observe(page, plate, timeout_ms, holder):
            holder.update(states.pop(0))

        def factory(**_):
            session = FakeSession(FakePage())
            sessions.append(session)
            return session

        with patch.object(sunarp_stealth, "_observe", side_effect=observe):
            result = query_sunarp_stealth("ABC123", 60, session_factory=factory)
        self.assertEqual(result.status, QueryStatus.SUCCESS)
        self.assertEqual(len(sessions), 2)

    def test_all_sessions_failed_requests_interaction(self):
        def observe(page, plate, timeout_ms, holder):
            holder["captcha"] = "Captcha no resuelto"

        with patch.object(sunarp_stealth, "_observe", side_effect=observe):
            result = query_sunarp_stealth(
                "ABC123", 60, session_factory=lambda **_: FakeSession(FakePage())
            )
        self.assertEqual(result.status, QueryStatus.REQUIRES_INTERACTION)
        self.assertIn("ningun intento", result.message)

    def test_full_path_normalizes_plate(self):
        page = FakePage(FakeResponse(API_URL, 200, payload()))
        result = query_sunarp_stealth(
            " abc-123 ",
            10,
            session_factory=lambda **_: FakeSession(page),
        )
        self.assertEqual(result.plate, "ABC123")
        self.assertEqual(result.status, QueryStatus.SUCCESS)

    def test_never_success_without_observed_data(self):
        result = _result_from_holder("ABC123", {})
        self.assertEqual(result.status, QueryStatus.REQUIRES_INTERACTION)
        self.assertEqual(result.data, {})

    def test_api_not_found_is_not_success(self):
        result = _result_from_holder(
            "ABC123",
            {"status": 200, "payload": {"cod": 0, "mensaje": "No se ha encontrado la placa", "model": None}},
        )
        self.assertEqual(result.status, QueryStatus.NOT_FOUND)
        self.assertFalse(result.data["encontrado"])
        self.assertEqual(result.data["capture"]["method"], "stealth_api")


if __name__ == "__main__":
    unittest.main()
