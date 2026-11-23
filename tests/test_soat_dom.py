import copy
import unittest
from obd_consultas.domain.models import QueryStatus
from obd_consultas.providers.soat import SoatParseError
from obd_consultas.providers.soat_dom import parse_dom_capture, result_from_dom_capture


def capture():
    return {"format": "apeseg-dom-v1", "source_url": "https://www.apeseg.org.pe/consultas-soat/",
            "plate": "ABC123", "history_count": "2", "current": {
                "state": "VIGENTE", "dates": ["Desde01/01/2026", "Hasta31/12/2026"],
                "fields": {"Compañía de seguros": "COMPANIA SINTETICA", "N.° de certificado": "000001",
                           "Tipo de certificado": "DIGITAL", "Uso del vehículo": "PARTICULAR"}},
            "history": [
                {"company": "COMPANIA SINTETICA", "state": "VIGENTE", "dates": "01/01/2026 — 31/12/2026",
                 "details": ["Cert. 000001", "PARTICULAR", "DIGITAL"]},
                {"company": "COMPANIA SINTETICA", "state": "ANULADO", "dates": "01/01/2025 — 31/12/2025",
                 "details": ["Cert. 000002", "PARTICULAR", "FISICO", "Anulado el 02/01/2025 00:00"]}]}


class DomTests(unittest.TestCase):
    def test_complete_result_and_history(self):
        data = parse_dom_capture(capture(), "ABC123")
        self.assertEqual(len(data["certificados"]), 2)
        self.assertEqual(data["soat_vigente"]["numero_poliza"], "000001")
        self.assertEqual(data["certificados"][1]["estado"], "ANULADO")
        self.assertTrue(data["capture"]["history_complete"])

    def test_rejects_partial_history(self):
        data = capture()
        data["history"].pop()
        with self.assertRaises(SoatParseError):
            parse_dom_capture(data, "ABC123")

    def test_rejects_collapsed_history(self):
        data = capture()
        data["history"] = []
        with self.assertRaises(SoatParseError):
            parse_dom_capture(data, "ABC123")

    def test_single_certificate_without_history(self):
        data = capture()
        data.update(history=[], history_count="1")
        self.assertEqual(len(parse_dom_capture(data, "ABC123")["certificados"]), 1)

    def test_rejects_unexpected_origin_format_or_plate(self):
        for changes in ({"source_url": "https://example.com/consultas-soat/"},
                        {"source_url": "https://www.apeseg.org.pe/another/"},
                        {"format": "unknown"}, {"plate": "ZZZ999"}):
            data = capture()
            data.update(changes)
            with self.subTest(changes=changes), self.assertRaises(SoatParseError):
                parse_dom_capture(data, "ABC123")

    def test_rejects_main_certificate_mismatch(self):
        data = capture()
        data["history"][0]["company"] = "OTRA COMPANIA SINTETICA"
        with self.assertRaises(SoatParseError):
            parse_dom_capture(data, "ABC123")

    def test_import_is_identified_as_import(self):
        result = result_from_dom_capture(capture(), "ABC123", imported=True)
        self.assertEqual(result.status, QueryStatus.SUCCESS)
        self.assertEqual(result.data["capture"]["method"], "imported_browser_dom")
        self.assertIn("no se realizo una consulta nueva", result.message)

    def test_missing_fields_returns_parse_error(self):
        data = capture()
        data["current"]["fields"] = {}
        result = result_from_dom_capture(data, "ABC123")
        self.assertEqual(result.status, QueryStatus.PARSE_ERROR)
        self.assertEqual(result.data, {})
