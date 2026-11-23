"""Pruebas del flujo asistido de MTC con dobles; no abren navegadores."""
import contextlib
import io
import json
import time
import unittest
from unittest.mock import patch

from obd_consultas.domain.models import QueryStatus
from obd_consultas.infrastructure import mtc_browser
from obd_consultas.infrastructure.mtc_browser import (
    _result_from_holder,
    is_query_response,
    query_mtc_interactive,
)

API_URL = "https://rec.mtc.gob.pe/CITV/JrCITVConsultarFiltro?pArrParametros=1%7CABC123%7C%7C123456"


def record():
    return {
        "PLACA": "ABC123",
        "NRO_CERTI": "C-SINTETICO-001",
        "REVISIONVIGENCIAINICIO": "01/01/2026",
        "REVISIONVIGENCIAFINAL": "31/12/2026",
        "RESULTADO": "APROBADO",
        "ESTADO": "VIGENTE",
        "SRAZONSOCENTCER": "CENTRO SINTETICO",
        "DIRECCION": "AVENIDA SINTETICA 123",
        "TIPO_AMBITO": "NINGUNO",
        "TIPO_SERVICIO": "PARTICULAR",
        "TIPODOCUMENTO": "NRO DE CERTIFICADO",
        "OBSERVACION": "Sin observaciones",
    }


def payload():
    return {"orStatus": True, "orResult": [json.dumps(record())], "orCodigo": ""}


class FakeResponse:
    def __init__(self, url, status=200, payload=None):
        self.url = url
        self.status = status
        self._payload = payload

    def json(self):
        return self._payload


class FakeLocator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector

    def fill(self, value, timeout=None):
        self.page.filled = value
        if self.page.response is not None:
            for handler in list(self.page.handlers):
                handler(self.page.response)

    def count(self):
        return 1 if self.selector in self.page.visible else 0

    def is_visible(self):
        return self.selector in self.page.visible

    def inner_text(self):
        return "ABC123"


class FakePage:
    def __init__(self, response=None, visible=None, dom=None):
        self.handlers = []
        self.response = response
        self.visible = visible or {}
        self.dom = dom
        self.filled = None

    def on(self, event, handler):
        self.handlers.append(handler)

    def goto(self, url, **kwargs):
        self.url = url

    def locator(self, selector):
        return FakeLocator(self, selector)

    def evaluate(self, script):
        if script == mtc_browser.CAPTURE_SCRIPT:
            return self.dom
        return time.time() * 1000

    def wait_for_timeout(self, milliseconds):
        return None


class FakeBrowser:
    def __init__(self, page):
        self.page = page

    def new_context(self):
        return self

    def new_page(self):
        return self.page

    def close(self):
        return None


class FakeChromium:
    def __init__(self, page):
        self.page = page

    def launch(self, **kwargs):
        return FakeBrowser(self.page)


class FakePlaywright:
    def __init__(self, page):
        self.chromium = FakeChromium(page)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class MtcBrowserTests(unittest.TestCase):
    def test_query_response_matcher(self):
        self.assertTrue(is_query_response(API_URL))
        self.assertFalse(is_query_response("https://ejemplo.test/CITV/JrCITVConsultarFiltro"))

    def test_api_result_becomes_success(self):
        holder = {"status": 200, "payload": payload()}
        result = _result_from_holder("ABC123", holder)
        self.assertEqual(result.status, QueryStatus.SUCCESS)
        self.assertEqual(result.data["capture"]["method"], "browser_api")

    def test_dom_result_becomes_success(self):
        capture = {
            "format": "mtc-dom-v1",
            "source_url": "https://rec.mtc.gob.pe/Citv/ArConsultaCitv",
            "records": [record()],
        }
        result = _result_from_holder("ABC123", {"dom": capture})
        self.assertEqual(result.status, QueryStatus.SUCCESS)
        self.assertEqual(result.data["capture"]["method"], "browser_dom")

    def test_invalid_captcha_requests_interaction(self):
        holder = {"status": 200, "payload": {"orStatus": False, "orCodigo": "-1"}}
        result = _result_from_holder("ABC123", holder)
        self.assertEqual(result.status, QueryStatus.REQUIRES_INTERACTION)

    def test_timeout_requests_interaction(self):
        result = _result_from_holder("ABC123", {"error": TimeoutError("espera")})
        self.assertEqual(result.status, QueryStatus.REQUIRES_INTERACTION)

    def test_browser_error_is_unavailable(self):
        result = _result_from_holder("ABC123", {"error": RuntimeError("fallo")})
        self.assertEqual(result.status, QueryStatus.UNAVAILABLE)

    def test_full_path_drives_form(self):
        page = FakePage(FakeResponse(API_URL, 200, payload()))
        with patch.object(mtc_browser, "sync_playwright", return_value=FakePlaywright(page)):
            with contextlib.redirect_stderr(io.StringIO()):
                result = query_mtc_interactive(" abc-123 ", 10, "chrome")
        self.assertEqual(page.filled, "ABC123")
        self.assertEqual(result.status, QueryStatus.SUCCESS)
        self.assertEqual(result.plate, "ABC123")

    def test_full_path_uses_dom_fallback(self):
        capture = {
            "format": "mtc-dom-v1",
            "source_url": "https://rec.mtc.gob.pe/Citv/ArConsultaCitv",
            "records": [record()],
        }
        page = FakePage(visible={"#Panel1": 1, "#Spv1_3": 1}, dom=capture)
        with patch.object(mtc_browser, "sync_playwright", return_value=FakePlaywright(page)):
            with contextlib.redirect_stderr(io.StringIO()):
                result = query_mtc_interactive("ABC123", 10)
        self.assertEqual(result.status, QueryStatus.SUCCESS)
        self.assertEqual(result.data["capture"]["method"], "browser_dom")


if __name__ == "__main__":
    unittest.main()
