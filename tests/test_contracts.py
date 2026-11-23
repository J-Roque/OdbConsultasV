"""El ``data`` de cada fuente cumple su contrato (``obd_consultas.contracts``).

Reutiliza los fixtures sinteticos de los tests de cada fuente. Si un parser
agrega, quita o cambia un campo, estos tests fallan: hay que actualizar el
contrato (y la APK) a proposito, no por accidente.
"""
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from obd_consultas.api.app import create_app
from obd_consultas.api.security import ApiSettings
from obd_consultas.contracts import (
    ALL_MODELS,
    ContractError,
    MtcData,
    OcrUnavailable,
    SoatData,
    SunarpData,
    SunarpNotFound,
    SunarpVehicle,
    SutranData,
    validate_data,
)
from obd_consultas.domain.models import QueryResult, QueryStatus, Source
from obd_consultas.infrastructure import mtc_stealth, soat_stealth, sunarp_ocr, sunarp_stealth
from obd_consultas.infrastructure.connector_common import stamp_capture
from obd_consultas.providers import mtc, soat, soat_dom, sunarp, sutran
import test_mtc
import test_soat
import test_soat_dom
import test_sunarp
import test_sunarp_ocr
import test_sutran


class SoatContractTests(unittest.TestCase):
    def test_success_and_history(self):
        result = soat.result_from_response(
            "ABC123",
            200,
            test_soat.payload(
                test_soat.certificate(),
                test_soat.certificate(Estado="VENCIDO", FechaInicio="01/01/2025", FechaFin="31/12/2025"),
            ),
        )
        self.assertEqual(result.status, QueryStatus.SUCCESS)
        self.assertIsInstance(validate_data(result), SoatData)

    def test_not_found(self):
        result = soat.result_from_response("ABC123", 200, test_soat.payload())
        self.assertEqual(result.status, QueryStatus.NOT_FOUND)
        self.assertIsInstance(validate_data(result), SoatData)

    def test_dom_capture(self):
        result = soat_dom.result_from_dom_capture(test_soat_dom.capture(), "ABC123")
        self.assertEqual(result.status, QueryStatus.SUCCESS)
        data = validate_data(result)
        self.assertEqual(data.capture.method, "browser_dom")

    def test_stealth_stamps_capture(self):
        holder = {"status": 200, "payload": test_soat.payload(test_soat.certificate())}
        data = validate_data(soat_stealth._result_from_holder("ABC123", holder))
        self.assertEqual(data.capture.method, "stealth_api")

    def test_notice_not_found(self):
        notice = "No encontramos certificados SOAT para la placa ABC123"
        result = soat_stealth._result_from_holder("ABC123", {"notice": notice})
        self.assertEqual(result.status, QueryStatus.NOT_FOUND)
        self.assertIsInstance(validate_data(result), SoatData)


class SunarpContractTests(unittest.TestCase):
    def test_success(self):
        result = sunarp.result_from_response("ABC123", 200, test_sunarp.payload())
        self.assertIsInstance(validate_data(result), SunarpData)

    def test_not_found(self):
        result = sunarp.result_from_response(
            "ABC123", 200, {"cod": 0, "mensaje": "No se ha encontrado la placa", "model": None}
        )
        self.assertEqual(result.status, QueryStatus.NOT_FOUND)
        self.assertIsInstance(validate_data(result), SunarpNotFound)

    def test_dom_capture(self):
        result = sunarp.result_from_dom_capture(test_sunarp.dom_capture(), "ABC123")
        self.assertEqual(validate_data(result).capture.method, "stealth_dom")

    def test_ocr_fields(self):
        fake_engine = lambda image: (test_sunarp_ocr.items(), None)  # noqa: E731
        result = sunarp.result_from_response("ABC123", 200, test_sunarp.payload())
        with patch.object(sunarp_ocr, "_engine", return_value=fake_engine):
            result = sunarp_ocr.attach_tive_ocr(result, test_sunarp.PNG_BASE64)
        self.assertIsInstance(validate_data(result).vehiculo, SunarpVehicle)

    def test_ocr_failure_is_documented(self):
        result = sunarp.result_from_response("ABC123", 200, test_sunarp.payload())
        with patch.object(sunarp_ocr, "_engine", side_effect=RuntimeError("sin modelo")):
            result = sunarp_ocr.attach_tive_ocr(result, test_sunarp.PNG_BASE64)
        self.assertIsInstance(validate_data(result).vehiculo, OcrUnavailable)

    def test_stealth_path(self):
        holder = {"status": 200, "payload": test_sunarp.payload()}
        with patch.object(sunarp_stealth, "attach_tive_ocr", side_effect=lambda r, _img: r):
            result = sunarp_stealth._result_from_holder("ABC123", holder)
        self.assertEqual(validate_data(result).capture.method, "stealth_api")


class MtcContractTests(unittest.TestCase):
    def test_success(self):
        result = mtc.result_from_response("ABC123", 200, test_mtc.payload())
        data = validate_data(result)
        self.assertIsInstance(data, MtcData)
        self.assertEqual(len(data.registros), 3)

    def test_not_found(self):
        result = mtc.result_from_response("ABC123", 200, test_mtc.payload([]))
        self.assertEqual(result.status, QueryStatus.NOT_FOUND)
        self.assertIsInstance(validate_data(result), MtcData)

    def test_dom_and_ocr_capture(self):
        dom = mtc.result_from_dom_capture(test_mtc.dom_capture(), "ABC123")
        self.assertEqual(validate_data(dom).capture.method, "browser_dom")
        ocr = stamp_capture(
            mtc.result_from_response("ABC123", 200, test_mtc.payload()), "stealth_ocr", attempts=2
        )
        self.assertEqual(validate_data(ocr).capture.attempts, 2)
        self.assertTrue(hasattr(mtc_stealth, "query_mtc_stealth"))


class SutranContractTests(unittest.TestCase):
    def test_success_and_not_found(self):
        found = sutran.result_from_response("B8T117", 200, test_sutran.payload([{"nro": "M1"}]))
        empty = sutran.result_from_response("B8T117", 200, test_sutran.payload())
        self.assertEqual(found.status, QueryStatus.SUCCESS)
        self.assertEqual(empty.status, QueryStatus.NOT_FOUND)
        self.assertIsInstance(validate_data(found), SutranData)
        self.assertIsInstance(validate_data(empty), SutranData)


class ContractRulesTests(unittest.TestCase):
    def test_non_final_results_carry_no_data(self):
        results = [
            soat.result_from_response("ABC123", 403, None),
            sunarp.result_from_response("ABC123", 500, None),
            mtc.result_from_response("ABC123", 200, {"orStatus": False, "orCodigo": "-1"}),
            sutran.result_from_response("B8T117", 200, {"success": False}),
            soat_stealth._result_from_holder("ABC123", {}),
        ]
        for result in results:
            with self.subTest(source=result.source, status=result.status):
                self.assertNotIn(result.status, {QueryStatus.SUCCESS, QueryStatus.NOT_FOUND})
                self.assertIsNone(validate_data(result))

    def test_detects_contract_drift(self):
        result = soat.result_from_response("ABC123", 200, test_soat.payload(test_soat.certificate()))
        drifted = QueryResult(
            result.source, result.plate, result.status, result.source_url, result.message,
            {**result.data, "campo_nuevo": 1},
        )
        with self.assertRaises(ContractError):
            validate_data(drifted)
        broken = QueryResult(Source.MTC, "ABC123", QueryStatus.UNAVAILABLE, "", "x", {"a": 1})
        with self.assertRaises(ContractError):
            validate_data(broken)

    def test_openapi_publishes_every_contract(self):
        token = "t" * 40
        client = TestClient(create_app(settings=ApiSettings(api_token=token, enable_docs=True)))
        self.addCleanup(client.close)
        schema = client.get("/openapi.json").json()
        components = set(schema["components"]["schemas"])
        missing = {m.__name__ for m in ALL_MODELS} - components
        self.assertEqual(missing, set())
        data_schema = schema["components"]["schemas"]["QueryResponse"]["properties"]["data"]
        refs = {item.get("$ref", "").rsplit("/", 1)[-1] for item in data_schema["anyOf"]}
        self.assertTrue({m.__name__ for m in ALL_MODELS} <= refs)


if __name__ == "__main__":
    unittest.main()
