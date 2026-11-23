"""Pruebas del conector MTC con respuestas sinteticas; no usan red."""
import json
import unittest

from obd_consultas.domain.models import QueryStatus
from obd_consultas.providers.mtc import (
    MtcProvider,
    parse_mtc,
    result_from_dom_capture,
    result_from_response,
)


def record(plate="ABC123", state="VIGENTE"):
    return {
        "PLACA": plate,
        "NRO_CERTI": "C-SINTETICO-001",
        "REVISIONVIGENCIAINICIO": "01/01/2026",
        "REVISIONVIGENCIAFINAL": "31/12/2026",
        "RESULTADO": "APROBADO",
        "ESTADO": state,
        "SRAZONSOCENTCER": "CENTRO &amp; SINTETICO",
        "DIRECCION": "AVENIDA SINTETICA 123",
        "TIPO_AMBITO": "NINGUNO",
        "TIPO_SERVICIO": "PARTICULAR",
        "TIPODOCUMENTO": "NRO DE CERTIFICADO",
        "OBSERVACION": "Sin observaciones",
    }


def payload(records=None):
    records = records if records is not None else [record(), record(state="VENCIDO"), record(state="VENCIDO")]
    return {"orStatus": True, "orResult": [json.dumps(item) for item in records], "orCodigo": ""}


def dom_capture():
    return {
        "format": "mtc-dom-v1",
        "source_url": "https://rec.mtc.gob.pe/Citv/ArConsultaCitv",
        "records": [record()],
    }


class MtcParserTests(unittest.TestCase):
    def test_success_normalizes_three_records(self):
        data = parse_mtc(payload(), "abc-123")
        self.assertTrue(data["encontrado"])
        self.assertEqual(len(data["registros"]), 3)
        self.assertEqual([item["etiqueta"] for item in data["registros"]],
                         ["ULTIMO", "PENULTIMO", "ANTEPENULTIMO"])
        first = data["registros"][0]
        self.assertEqual(first["placa"], "ABC123")
        self.assertEqual(first["empresa"], "CENTRO & SINTETICO")
        self.assertEqual(first["vigencia_desde"], "2026-01-01")
        self.assertEqual(first["vigencia_hasta"], "2026-12-31")
        self.assertEqual(data["vigente"]["numero_certificado"], "C-SINTETICO-001")

    def test_real_portal_shape_with_array_and_trailing_count(self):
        response = {
            "orStatus": True,
            "orResult": [json.dumps([record(), record(state="VENCIDO")], ensure_ascii=False), 2],
            "orCodigo": "",
        }
        result = result_from_response("ABC123", 200, response)
        self.assertEqual(result.status, QueryStatus.SUCCESS)
        self.assertEqual(len(result.data["registros"]), 2)
        self.assertEqual(result.data["vigente"]["estado"], "VIGENTE")

    def test_wrong_plate_is_parse_error(self):
        result = result_from_response("ABC123", 200, payload([record("XYZ999")]))
        self.assertEqual(result.status, QueryStatus.PARSE_ERROR)

    def test_invalid_date_is_parse_error(self):
        item = record()
        item["REVISIONVIGENCIAINICIO"] = "fecha rara"
        self.assertEqual(result_from_response("ABC123", 200, payload([item])).status,
                         QueryStatus.PARSE_ERROR)

    def test_invalid_record_json_is_parse_error(self):
        result = result_from_response("ABC123", 200, {"orStatus": True, "orResult": ["no-json"]})
        self.assertEqual(result.status, QueryStatus.PARSE_ERROR)

    def test_invalid_captcha_requests_interaction(self):
        result = result_from_response("ABC123", 200, {"orStatus": False, "orCodigo": "-1"})
        self.assertEqual(result.status, QueryStatus.REQUIRES_INTERACTION)

    def test_other_error_is_unavailable(self):
        result = result_from_response("ABC123", 200, {"orStatus": False, "orCodigo": "99"})
        self.assertEqual(result.status, QueryStatus.UNAVAILABLE)

    def test_empty_result_is_not_found(self):
        result = result_from_response("ABC123", 200, payload([]))
        self.assertEqual(result.status, QueryStatus.NOT_FOUND)
        self.assertFalse(result.data["encontrado"])

    def test_http_errors(self):
        self.assertEqual(result_from_response("ABC123", 403, None).status, QueryStatus.REQUIRES_INTERACTION)
        self.assertEqual(result_from_response("ABC123", 429, None).status, QueryStatus.UNAVAILABLE)
        self.assertEqual(result_from_response("ABC123", 500, None).status, QueryStatus.UNAVAILABLE)
        self.assertEqual(result_from_response("ABC123", 404, None).status, QueryStatus.UNAVAILABLE)

    def test_non_json_payload_is_parse_error(self):
        self.assertEqual(result_from_response("ABC123", 200, None).status, QueryStatus.PARSE_ERROR)

    def test_provider_requires_interactive(self):
        result = MtcProvider().query("abc-123")
        self.assertEqual(result.status, QueryStatus.REQUIRES_INTERACTION)
        self.assertIn("--stealth", result.message)


class MtcDomTests(unittest.TestCase):
    def test_dom_capture(self):
        result = result_from_dom_capture(dom_capture(), "ABC123")
        self.assertEqual(result.status, QueryStatus.SUCCESS)
        self.assertEqual(result.data["registros"][0]["placa"], "ABC123")
        self.assertEqual(result.data["capture"]["method"], "browser_dom")

    def test_dom_capture_rejects_other_portal(self):
        capture = dom_capture()
        capture["source_url"] = "https://ejemplo.test/Citv/ArConsultaCitv"
        self.assertEqual(result_from_dom_capture(capture, "ABC123").status, QueryStatus.PARSE_ERROR)

    def test_dom_capture_rejects_wrong_format(self):
        capture = dom_capture()
        capture["format"] = "otro"
        self.assertEqual(result_from_dom_capture(capture, "ABC123").status, QueryStatus.PARSE_ERROR)


if __name__ == "__main__":
    unittest.main()
