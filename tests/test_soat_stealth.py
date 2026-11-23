"""Pruebas del modo sigiloso con dobles; no abren navegadores ni consultan APESEG."""
import unittest
from unittest.mock import patch

from obd_consultas.domain.models import QueryStatus
from obd_consultas.infrastructure import soat_stealth
from obd_consultas.infrastructure.scrapling_engine import ScraplingUnavailable
from obd_consultas.infrastructure.soat_stealth import (
    _observe,
    _result_from_holder,
    query_soat_stealth,
)

API_URL = "https://www.apeseg.org.pe/wp-json/apeseg-soat/v1/placa/ABC123"


def certificate():
    return {
        "Placa": "ABC123",
        "Estado": "VIGENTE",
        "NombreCompania": "ASEGURADORA SINTETICA",
        "FechaInicio": "01/01/2026",
        "FechaFin": "31/12/2026",
        "NumeroPoliza": "SINTETICA-001",
    }


def api_payload():
    return {"placa": "ABC123", "certificados": [certificate()]}


def dom_capture():
    return {
        "format": "apeseg-dom-v1",
        "source_url": "https://www.apeseg.org.pe/consultas-soat/",
        "plate": "ABC123",
        "history_count": "1",
        "current": {
            "state": "VIGENTE",
            "dates": ["Desde01/01/2026", "Hasta31/12/2026"],
            "fields": {
                "Compañía de seguros": "ASEGURADORA SINTETICA",
                "N.° de certificado": "SINTETICA-001",
                "Tipo de certificado": "DIGITAL",
                "Uso del vehículo": "PARTICULAR",
            },
        },
        "history": [],
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
        if self.selector == "button":
            for handler in list(self.page.handlers):
                handler(self.page.response)

    def count(self):
        return self.page.visible.get(self.selector, 0)

    @property
    def first(self):
        return self

    def inner_text(self):
        return self.page.notice

    def wait_for(self, **kwargs):
        return None


class FakePage:
    def __init__(self, response=None, visible=None, notice=""):
        self.handlers = []
        self.response = response
        self.visible = visible or {}
        self.notice = notice
        self.filled = None

    def on(self, event, handler):
        self.handlers.append(handler)

    def locator(self, selector):
        return FakeLocator(self, selector)

    def get_by_role(self, role, name, exact):
        return FakeLocator(self, "button")

    def wait_for_timeout(self, milliseconds):
        return None


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


class StealthTests(unittest.TestCase):
    def test_drives_form_and_parses_api_json(self):
        page = FakePage(FakeResponse(API_URL, 200, api_payload()))
        holder = {}
        _observe(page, "ABC123", 1_000, holder)
        self.assertEqual(page.filled, "ABC123")
        result = _result_from_holder("ABC123", holder)
        self.assertEqual(result.status, QueryStatus.SUCCESS)
        self.assertEqual(len(result.data["certificados"]), 1)
        self.assertEqual(result.data["capture"]["method"], "stealth_api")

    def test_dom_fallback_when_json_is_not_available(self):
        page = FakePage(visible={".soat-resultado": 1})
        holder = {}
        with patch.object(soat_stealth, "capture_result", return_value=dom_capture()):
            _observe(page, "ABC123", 1_000, holder)
        result = _result_from_holder("ABC123", holder)
        self.assertEqual(result.status, QueryStatus.SUCCESS)
        self.assertEqual(result.data["soat_vigente"]["aseguradora"], "ASEGURADORA SINTETICA")

    def test_explicit_not_found_notice(self):
        page = FakePage(
            visible={".soat-aviso": 1},
            notice="No encontramos certificados SOAT para la placa ABC123",
        )
        holder = {}
        _observe(page, "ABC123", 1_000, holder)
        result = _result_from_holder("ABC123", holder)
        self.assertEqual(result.status, QueryStatus.NOT_FOUND)
        self.assertFalse(result.data["encontrado"])

    def test_other_notice_is_not_not_found(self):
        page = FakePage(visible={".soat-aviso": 1}, notice="Servicio temporalmente no disponible")
        holder = {}
        _observe(page, "ABC123", 1_000, holder)
        result = _result_from_holder("ABC123", holder)
        self.assertEqual(result.status, QueryStatus.UNAVAILABLE)
        self.assertEqual(result.data, {})

    def test_timeout_requests_interaction(self):
        page = FakePage()
        holder = {}
        _observe(page, "ABC123", 30, holder)
        result = _result_from_holder("ABC123", holder)
        self.assertEqual(result.status, QueryStatus.REQUIRES_INTERACTION)
        self.assertEqual(result.data, {})

    def test_http_403_requests_interaction(self):
        result = _result_from_holder("ABC123", {"status": 403, "payload": None})
        self.assertEqual(result.status, QueryStatus.REQUIRES_INTERACTION)

    def test_browser_timeout_requests_interaction(self):
        result = _result_from_holder("ABC123", {"error": TimeoutError("sin respuesta")})
        self.assertEqual(result.status, QueryStatus.REQUIRES_INTERACTION)

    def test_browser_failure_is_unavailable(self):
        result = _result_from_holder("ABC123", {"error": RuntimeError("fallo")})
        self.assertEqual(result.status, QueryStatus.UNAVAILABLE)
        self.assertEqual(result.data, {})

    def test_missing_browser_points_to_install_command(self):
        def broken_session(**_):
            raise RuntimeError("Executable doesn't exist at /tmp/chromium")

        result = query_soat_stealth("ABC123", 10, session_factory=broken_session)
        self.assertEqual(result.status, QueryStatus.UNAVAILABLE)
        self.assertIn("install-browsers", result.message)

    def test_missing_dependency_is_reported(self):
        def unavailable_session(**_):
            raise ScraplingUnavailable("Scrapling no esta instalado.")

        result = query_soat_stealth("ABC123", 10, session_factory=unavailable_session)
        self.assertEqual(result.status, QueryStatus.UNAVAILABLE)
        self.assertIn("Scrapling", result.message)

    def test_full_path_normalizes_plate(self):
        page = FakePage(FakeResponse(API_URL, 200, api_payload()))
        result = query_soat_stealth(
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


if __name__ == "__main__":
    unittest.main()
