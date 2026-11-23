import unittest
from unittest.mock import patch

from obd_consultas.domain.models import QueryStatus
from obd_consultas.infrastructure import sutran_stealth


class FakeResponse:
    status = 200
    def __init__(self, payload):
        self.payload = payload
    def json(self):
        return self.payload


class FakePage:
    def __init__(self, payload):
        self.payload = payload
        self.response_listener = None
        self.filled = None
    def on(self, event, callback):
        self.response_listener = callback
    def wait_for_selector(self, *args, **kwargs):
        pass
    def locator(self, selector):
        return self
    def fill(self, plate, **kwargs):
        self.filled = plate
    def get_by_role(self, *args, **kwargs):
        return self
    def click(self, **kwargs):
        response = FakeResponse(self.payload)
        response.url = "https://api.dig.sutran.gob.pe/consultas/placa/B8T117"
        self.response_listener(response)
    def wait_for_timeout(self, timeout):
        pass


class FakeSession:
    def __init__(self, page):
        self.page = page
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def fetch(self, *args, **kwargs):
        kwargs["page_action"](self.page)


class SutranStealthTests(unittest.TestCase):
    def test_success_empty_result_is_not_found(self):
        payload = {
            "success": True,
            "data": {
                "criterio": {"tipo": "placa", "valor": "B8T117"},
                "fuentes": [{"nombre": "RECORD_INFRACCIONES", "ok": True}],
                "documentos": [],
            },
        }
        page = FakePage(payload)

        def factory(**kwargs):
            return FakeSession(page)

        result = sutran_stealth.query_sutran_stealth(
            "b8t-117", 10, session_factory=factory
        )
        self.assertEqual(page.filled, "B8T117")
        self.assertEqual(result.status, QueryStatus.NOT_FOUND)
        self.assertEqual(result.data["capture"]["method"], "stealth_api")


if __name__ == "__main__":
    unittest.main()
