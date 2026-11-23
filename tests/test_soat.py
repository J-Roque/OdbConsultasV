"""Fixtures sinteticos: no contienen registros de vehiculos reales."""
import unittest

from obd_consultas.domain.models import QueryStatus
from obd_consultas.infrastructure.soat_browser import is_query_response
from obd_consultas.providers.soat import SoatParseError, parse_soat, result_from_response


def certificate(**changes):
    return dict({"Placa": "ABC123", "Estado": "VIGENTE", "NombreCompania": "ASEGURADORA DE PRUEBA",
                 "FechaInicio": "01/01/2026", "FechaFin": "31/12/2026", "NumeroPoliza": "SINTETICA-001"}, **changes)


def payload(*certificates):
    return {"placa": "ABC123", "certificados": list(certificates)}


class SoatTests(unittest.TestCase):
    def test_normalizes_certificates_and_preserves_history(self):
        result = parse_soat(payload(certificate(), certificate(Estado="VENCIDO", FechaInicio="01/01/2025", FechaFin="31/12/2025")), "ABC123")
        self.assertTrue(result["encontrado"])
        self.assertTrue(result["vigente"])
        self.assertEqual(len(result["certificados"]), 2)
        self.assertEqual(result["soat_vigente"]["aseguradora"], "ASEGURADORA DE PRUEBA")
        self.assertEqual(result["soat_vigente"]["vigencia_hasta"], "2026-12-31")

    def test_expired_and_future_do_not_count_as_active(self):
        for state in ("VENCIDO", "FUTURO", "ANULADO"):
            with self.subTest(state=state):
                result = parse_soat(payload(certificate(Estado=state)), "ABC123")
                self.assertFalse(result["vigente"])
                self.assertIsNone(result["soat_vigente"])

    def test_explicit_empty_and_portal_sentinel_are_not_found(self):
        for data in (payload(), payload({"NombreCompania": "No encontrada"})):
            with self.subTest(data=data):
                self.assertEqual(result_from_response("ABC123", 200, data).status, QueryStatus.NOT_FOUND)

    def test_unexpected_json_never_becomes_not_found(self):
        for data in ({}, {"message": "Error"}, {"placa": "ABC123"},
                     {"placa": "ABC123", "certificados": None}, payload(None)):
            with self.subTest(data=data):
                self.assertEqual(result_from_response("ABC123", 200, data).status, QueryStatus.PARSE_ERROR)

    def test_rejects_mismatching_plate(self):
        with self.assertRaises(SoatParseError):
            parse_soat({"placa": "ZZZ999", "certificados": []}, "ABC123")
        with self.assertRaises(SoatParseError):
            parse_soat(payload(certificate(Placa="ZZZ999")), "ABC123")

    def test_rejects_unrecognized_state_and_invalid_dates(self):
        for changes in ({"Estado": "DESCONOCIDO"}, {"FechaFin": "31/02/2026"},
                        {"FechaInicio": None}, {"FechaInicio": "01/01/2027"},
                        {"NombreCompania": {}}, {"FechaFin": "2026-12-31"}):
            with self.subTest(changes=changes):
                self.assertEqual(result_from_response("ABC123", 200, payload(certificate(**changes))).status, QueryStatus.PARSE_ERROR)

    def test_http_failures_do_not_report_vehicle_status(self):
        for code, expected in ((403, QueryStatus.REQUIRES_INTERACTION), (429, QueryStatus.UNAVAILABLE),
                               (503, QueryStatus.UNAVAILABLE), (404, QueryStatus.UNAVAILABLE)):
            with self.subTest(code=code):
                result = result_from_response("ABC123", code, {})
                self.assertEqual(result.status, expected)
                self.assertEqual(result.data, {})

    def test_capture_ignores_other_plates_hosts_and_paths(self):
        self.assertTrue(is_query_response("https://www.apeseg.org.pe/wp-json/apeseg-soat/v1/placa/ABC123", "ABC123"))
        for url in ("https://www.apeseg.org.pe/wp-json/apeseg-soat/v1/placa/ZZZ999",
                    "https://example.com/wp-json/apeseg-soat/v1/placa/ABC123",
                    "https://www.apeseg.org.pe/wp-json/apeseg-soat/v1/placa/ABC123/other"):
            with self.subTest(url=url):
                self.assertFalse(is_query_response(url, "ABC123"))
