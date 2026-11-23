"""Pruebas del lector de la tarjeta TIVE sin ejecutar el modelo OCR."""
import base64
import unittest
from unittest.mock import patch

from obd_consultas.domain.models import QueryResult, QueryStatus, Source
from obd_consultas.infrastructure import sunarp_ocr
from obd_consultas.infrastructure.sunarp_ocr import (
    attach_tive_ocr,
    extract_tive_fields,
    fields_from_items,
)


def item(x, y, text, score=0.97, width=120):
    return (
        [[x, y], [x + width, y], [x + width, y + 20], [x, y + 20]],
        text,
        score,
    )


def items():
    return [
        item(7, 177, "N° PLACA:"),
        item(200, 178, "B8T117", 1.0),
        item(7, 198, "N° SERIE:"),
        item(200, 198, "1HGEJ7149TL056794"),
        item(7, 228, "N° VIN:"),
        item(116, 256, "Sunarp", 0.99),
        item(7, 252, "N° MOTOR:"),
        item(200, 254, "B16A1406590", 1.0),
        item(7, 278, "COLOR:"),
        item(200, 278, "ROJO"),
        item(7, 302, "MARCA:"),
        item(200, 302, "HONDA"),
        item(7, 326, "MODELO:"),
        item(200, 326, "CIVIC/96"),
        item(7, 350, "PLACA VIGENTE:"),
        item(200, 350, "B8T117"),
        item(7, 374, "PLACA ANTERIOR: AGV233"),
        item(7, 400, "ESTADO:"),
        item(200, 400, "ENCIRCULACION"),
        item(7, 428, "ANOTACIONES:"),
        item(200, 428, "NINGUNA", 1.0),
        item(7, 452, "SEDE:"),
        item(200, 452, "LIMA", 1.0),
        item(7, 478, "AÑO DE MODELO:"),
        item(7, 526, "PROPIETARIO(S):"),
        item(10, 554, "VALDEZTELLO,EVER", 0.87, 300),
    ]


class SunarpOcrTests(unittest.TestCase):
    def test_fields_from_items(self):
        fields = fields_from_items(items())
        self.assertEqual(fields["placa"]["valor"], "B8T117")
        self.assertEqual(fields["serie"]["valor"], "1HGEJ7149TL056794")
        self.assertEqual(fields["motor"]["valor"], "B16A1406590")
        self.assertEqual(fields["color"]["valor"], "ROJO")
        self.assertEqual(fields["marca"]["valor"], "HONDA")
        self.assertEqual(fields["modelo"]["valor"], "CIVIC/96")
        self.assertEqual(fields["placa_anterior"]["valor"], "AGV233")
        self.assertEqual(fields["estado"]["valor"], "EN CIRCULACION")
        self.assertEqual(fields["propietarios"]["valor"], ["VALDEZTELLO", "EVER"])
        self.assertIsNone(fields["vin"]["valor"])
        self.assertIsNone(fields["anio_modelo"]["valor"])
        self.assertEqual(fields["ocr"], "rapidocr")

    def test_low_confidence_items_are_ignored(self):
        data = [item(7, 177, "N° PLACA:"), item(200, 178, "B8T117", 0.40)]
        self.assertIsNone(fields_from_items(data)["placa"]["valor"])

    def test_extract_uses_injected_engine(self):
        fake_engine = lambda image: (items(), None)
        with patch.object(sunarp_ocr, "_engine", return_value=fake_engine):
            fields = extract_tive_fields(b"imagen")
        self.assertEqual(fields["marca"]["valor"], "HONDA")

    def test_attach_never_breaks_the_query(self):
        result = QueryResult(
            Source.SUNARP, "B8T117", QueryStatus.SUCCESS, "", "ok", {"tarjeta": {}}
        )
        with patch.object(sunarp_ocr, "_engine", side_effect=RuntimeError("sin modelo")):
            result = attach_tive_ocr(result, base64.b64encode(b"x").decode())
        self.assertFalse(result.data["vehiculo"]["disponible"])
        self.assertIn("tarjeta", result.data)


if __name__ == "__main__":
    unittest.main()
