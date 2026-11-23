"""Pruebas del conector SUNARP con respuestas sinteticas; no usan red."""
import base64
import unittest

from obd_consultas.domain.models import QueryStatus
from obd_consultas.providers.sunarp import (
    SunarpProvider,
    parse_sunarp,
    result_from_dom_capture,
    result_from_response,
)

PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def sede(plate="ABC123"):
    return {
        "prefijo": "OR0101",
        "regPubId": "01",
        "oficRegId": "01",
        "nombre": "LIMA",
        "fgBaja": "0",
        "placa": plate + " ",
        "numPartida": "50190361",
    }


def payload(**overrides):
    model = {
        "imagen": PNG_BASE64,
        "msgAlertaRobo": "",
        "sedes": [sede()],
    }
    model.update(overrides.pop("model", {}))
    value = {"cod": 1, "mensaje": "Placa encontrada satisfactoriamente", "mensajeTxt": "", "model": model}
    value.update(overrides)
    return value


def dom_capture(rows=None):
    return {
        "format": "sunarp-dom-v1",
        "source_url": "https://consultavehicular.sunarp.gob.pe/consulta-vehicular/inicio",
        "image": "data:image/png;base64," + PNG_BASE64,
        "alert": "",
        "rows": rows if rows is not None else [["1", "ABC123", "50190361", "LIMA"]],
    }


class SunarpParserTests(unittest.TestCase):
    def test_success_exposes_image_and_sedes(self):
        data = parse_sunarp(payload(), "abc-123")
        self.assertTrue(data["encontrado"])
        self.assertTrue(data["plate_verified"])
        self.assertEqual(data["sedes"][0]["placa"], "ABC123")
        self.assertEqual(data["sedes"][0]["num_partida"], "50190361")
        self.assertEqual(data["tarjeta"]["formato"], "png")
        self.assertEqual((data["tarjeta"]["ancho"], data["tarjeta"]["alto"]), (1, 1))
        self.assertEqual(len(data["tarjeta"]["sha256"]), 64)
        self.assertEqual(base64.b64decode(data["tarjeta"]["base64"]), base64.b64decode(PNG_BASE64))
        self.assertIsNone(data["alerta_robo"])

    def test_alerta_robo_is_surfaced(self):
        result = result_from_response("ABC123", 200, payload(model={"msgAlertaRobo": "ALERTA SINTETICA"}))
        self.assertEqual(result.status, QueryStatus.SUCCESS)
        self.assertEqual(result.data["alerta_robo"], "ALERTA SINTETICA")
        self.assertIn("ALERTA SINTETICA", result.message)

    def test_not_found_message(self):
        result = result_from_response(
            "ABC123",
            200,
            {"cod": 0, "mensaje": "No se ha encontrado la placa del vehiculo ingresado",
             "mensajeTxt": "Intentar nuevamente", "model": None},
        )
        self.assertEqual(result.status, QueryStatus.NOT_FOUND)
        self.assertFalse(result.data["encontrado"])

    def test_not_found_message_repairs_portal_encoding(self):
        result = result_from_response(
            "ABC123",
            200,
            {"cod": 0, "mensaje": "No se ha encontrado la placa del veh\u251c\u00a1culo", "model": None},
        )
        self.assertEqual(result.status, QueryStatus.NOT_FOUND)
        self.assertIn("veh\u00edculo", result.message)

    def test_other_error_is_not_not_found(self):
        result = result_from_response(
            "ABC123",
            200,
            {"cod": 0, "mensaje": "Servicio temporalmente no disponible", "model": None},
        )
        self.assertEqual(result.status, QueryStatus.UNAVAILABLE)
        self.assertEqual(result.data, {})

    def test_unknown_code_is_unavailable(self):
        result = result_from_response("ABC123", 200, {"cod": 99, "model": None})
        self.assertEqual(result.status, QueryStatus.UNAVAILABLE)

    def test_invalid_base64_is_parse_error(self):
        result = result_from_response("ABC123", 200, payload(model={"imagen": "no-es-base64"}))
        self.assertEqual(result.status, QueryStatus.PARSE_ERROR)

    def test_non_png_image_is_parse_error(self):
        result = result_from_response(
            "ABC123", 200, payload(model={"imagen": base64.b64encode(b"no es png").decode()})
        )
        self.assertEqual(result.status, QueryStatus.PARSE_ERROR)

    def test_wrong_plate_is_parse_error(self):
        result = result_from_response("ABC123", 200, payload(model={"sedes": [sede("XYZ999")]}))
        self.assertEqual(result.status, QueryStatus.PARSE_ERROR)

    def test_missing_sedes_is_parse_error(self):
        result = result_from_response("ABC123", 200, payload(model={"sedes": []}))
        self.assertEqual(result.status, QueryStatus.PARSE_ERROR)

    def test_missing_model_is_parse_error(self):
        result = result_from_response("ABC123", 200, {"cod": 1})
        self.assertEqual(result.status, QueryStatus.PARSE_ERROR)

    def test_http_errors(self):
        self.assertEqual(result_from_response("ABC123", 403, None).status, QueryStatus.REQUIRES_INTERACTION)
        self.assertEqual(result_from_response("ABC123", 429, None).status, QueryStatus.UNAVAILABLE)
        self.assertEqual(result_from_response("ABC123", 503, None).status, QueryStatus.UNAVAILABLE)
        self.assertEqual(result_from_response("ABC123", 404, None).status, QueryStatus.UNAVAILABLE)

    def test_non_json_payload_is_parse_error(self):
        self.assertEqual(result_from_response("ABC123", 200, None).status, QueryStatus.PARSE_ERROR)

    def test_provider_requires_cli(self):
        result = SunarpProvider().query("abc-123")
        self.assertEqual(result.status, QueryStatus.REQUIRES_INTERACTION)
        self.assertEqual(result.plate, "ABC123")
        self.assertEqual(result.data, {})


class SunarpDomTests(unittest.TestCase):
    def test_dom_capture_with_visible_sede(self):
        result = result_from_dom_capture(dom_capture(), "ABC123")
        self.assertEqual(result.status, QueryStatus.SUCCESS)
        self.assertTrue(result.data["plate_verified"])
        self.assertEqual(result.data["capture"]["method"], "stealth_dom")

    def test_dom_capture_without_sede_is_not_verified(self):
        result = result_from_dom_capture(dom_capture(rows=[]), "ABC123")
        self.assertEqual(result.status, QueryStatus.SUCCESS)
        self.assertFalse(result.data["plate_verified"])
        self.assertIn("no se pudo verificar", result.message)

    def test_dom_capture_rejects_other_portal(self):
        capture = dom_capture()
        capture["source_url"] = "https://ejemplo.test/consulta-vehicular"
        self.assertEqual(result_from_dom_capture(capture, "ABC123").status, QueryStatus.PARSE_ERROR)

    def test_dom_capture_rejects_missing_image(self):
        capture = dom_capture()
        capture["image"] = ""
        self.assertEqual(result_from_dom_capture(capture, "ABC123").status, QueryStatus.PARSE_ERROR)


if __name__ == "__main__":
    unittest.main()
