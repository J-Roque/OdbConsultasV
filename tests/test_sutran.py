import unittest

from obd_consultas.domain.models import QueryStatus
from obd_consultas.infrastructure import sutran_stealth
from obd_consultas.providers.sutran import (
    SutranProvider,
    parse_sutran,
    result_from_response,
)


def payload(documentos=None, plate="B8T117"):
    return {
        "success": True,
        "data": {
            "criterio": {"tipo": "placa", "valor": plate},
            "fuentes": [
                {"nombre": "RECORD_INFRACCIONES", "ok": True},
                {"nombre": "PAPELETAS_CINEMOMETRO", "ok": True},
            ],
            "documentos": documentos if documentos is not None else [],
        },
    }


class SutranParserTests(unittest.TestCase):
    def test_empty_result_is_not_found(self):
        result = result_from_response("B8T117", 200, payload())
        self.assertEqual(result.status, QueryStatus.NOT_FOUND)
        self.assertFalse(result.data["encontrado"])
        self.assertEqual(result.data["criterio"]["valor"], "B8T117")

    def test_success_normalizes_documents(self):
        documents = [{"nroDocumento": "M123", "tipo": "PAPELETA"}]
        data = parse_sutran(payload(documents), "b8t-117")
        self.assertTrue(data["encontrado"])
        self.assertEqual(data["documentos"], documents)

    def test_wrong_plate_is_parse_error(self):
        result = result_from_response("B8T117", 200, payload(plate="ABC123"))
        self.assertEqual(result.status, QueryStatus.PARSE_ERROR)

    def test_http_errors(self):
        self.assertEqual(result_from_response("B8T117", 403, None).status,
                         QueryStatus.REQUIRES_INTERACTION)
        self.assertEqual(result_from_response("B8T117", 429, None).status,
                         QueryStatus.UNAVAILABLE)
        self.assertEqual(result_from_response("B8T117", 500, None).status,
                         QueryStatus.UNAVAILABLE)

    def test_provider_requires_stealth(self):
        result = SutranProvider().query("b8t-117")
        self.assertEqual(result.status, QueryStatus.REQUIRES_INTERACTION)
        self.assertIn("--stealth", result.message)


class FakeLocator:
    def __init__(self, page, name):
        self.page, self.name = page, name

    def fill(self, value, **_):
        self.page.events.append(("fill", value))

    def click(self, **_):
        self.page.events.append(("click", self.name))
        if self.page.response is not None:
            self.page.handler(self.page.response)


class FakeResponse:
    url = "https://api.dig.sutran.gob.pe/consultas/placa/B8T117"
    status = 200

    def json(self):
        return payload()


class FakePage:
    def __init__(self, response=None):
        self.response = response
        self.events = []
        self.waited = 0

    def on(self, _event, handler):
        self.handler = handler

    def wait_for_selector(self, *_args, **_kwargs):
        pass

    def locator(self, selector):
        return FakeLocator(self, selector)

    def get_by_role(self, _role, name, **_):
        return FakeLocator(self, name)

    def wait_for_timeout(self, ms):
        self.waited += ms

    def evaluate(self, _script):
        raise AssertionError("el conector no debe leer el token de Turnstile")


class SutranObserveTests(unittest.TestCase):
    def test_clicks_consultar_without_waiting_for_token(self):
        page, holder = FakePage(FakeResponse()), {}
        sutran_stealth._observe(page, "B8T117", 30_000, True, holder)
        self.assertEqual(page.events, [("fill", "B8T117"), ("click", "Consultar")])
        self.assertEqual(holder["status"], 200)
        result = sutran_stealth._result_from_holder("B8T117", holder)
        self.assertEqual(result.status, QueryStatus.NOT_FOUND)

    def test_no_api_response_requires_interaction(self):
        page, holder = FakePage(), {}
        sutran_stealth._observe(page, "B8T117", 10_000, True, holder)
        self.assertGreaterEqual(page.waited, sutran_stealth.SITE_TOKEN_WAIT_MS)
        result = sutran_stealth._result_from_holder("B8T117", holder)
        self.assertEqual(result.status, QueryStatus.REQUIRES_INTERACTION)


if __name__ == "__main__":
    unittest.main()
