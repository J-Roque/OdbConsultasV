import unittest

from obd_consultas.domain.models import QueryStatus
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


if __name__ == "__main__":
    unittest.main()
