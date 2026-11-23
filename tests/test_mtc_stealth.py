"""Pruebas del modo desatendido de MTC con dobles; no usan red ni OCR real."""
import base64
import json
import unittest
from unittest.mock import patch

from obd_consultas.domain.models import QueryStatus
from obd_consultas.infrastructure import mtc_stealth
from obd_consultas.infrastructure.mtc_stealth import query_mtc_stealth

PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


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


def success_payload():
    return {"orStatus": True, "orResult": [json.dumps([record()])], "orCodigo": ""}


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status = status
        self._payload = payload

    def json(self):
        return self._payload


class FakeOcr:
    def __init__(self, codes):
        self.codes = list(codes)

    def classification(self, image):
        return self.codes.pop(0) if self.codes else ""


class FakeSession:
    def __init__(self, form_status=200, responses=None):
        self.form_status = form_status
        self.responses = list(responses or [])
        self.codes = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url, **kwargs):
        if "refrescarCaptcha" in url:
            return FakeResponse(200, {"orStatus": True, "orResult": PNG_BASE64})
        if "JrCITVConsultarFiltro" in url:
            params = kwargs.get("params") or {}
            self.codes.append(params.get("pArrParametros", ""))
            return FakeResponse(200, self.responses.pop(0))
        return FakeResponse(self.form_status, {})


class MtcStealthTests(unittest.TestCase):
    def test_success_on_first_attempt(self):
        session = FakeSession(responses=[success_payload()])
        result = query_mtc_stealth(
            "abc-123", 10, session_factory=lambda **_: session, ocr=FakeOcr(["123456"])
        )
        self.assertEqual(result.status, QueryStatus.SUCCESS)
        self.assertEqual(result.data["capture"]["method"], "stealth_ocr")
        self.assertEqual(result.data["capture"]["attempts"], 1)
        self.assertIn("ABC123", session.codes[0])

    def test_retries_when_captcha_is_rejected(self):
        session = FakeSession(responses=[
            {"orStatus": False, "orCodigo": "-1"},
            success_payload(),
        ])
        result = query_mtc_stealth(
            "ABC123", 10,
            session_factory=lambda **_: session,
            ocr=FakeOcr(["111111", "222222"]),
        )
        self.assertEqual(result.status, QueryStatus.SUCCESS)
        self.assertEqual(result.data["capture"]["attempts"], 2)

    def test_skips_non_numeric_ocr_output(self):
        session = FakeSession(responses=[success_payload()])
        result = query_mtc_stealth(
            "ABC123", 10,
            session_factory=lambda **_: session,
            ocr=FakeOcr(["gnl", "333333"]),
        )
        self.assertEqual(result.status, QueryStatus.SUCCESS)
        self.assertEqual(len(session.codes), 1)

    def test_not_found_is_preserved(self):
        session = FakeSession(responses=[{"orStatus": True, "orResult": [], "orCodigo": ""}])
        result = query_mtc_stealth(
            "ABC123", 10, session_factory=lambda **_: session, ocr=FakeOcr(["123456"])
        )
        self.assertEqual(result.status, QueryStatus.NOT_FOUND)

    def test_all_attempts_failed_requests_interaction(self):
        session = FakeSession(responses=[{"orStatus": False, "orCodigo": "-1"}] * 3)
        result = query_mtc_stealth(
            "ABC123", 10,
            session_factory=lambda **_: session,
            ocr=FakeOcr(["111111", "222222", "333333"]),
            max_attempts=3,
        )
        self.assertEqual(result.status, QueryStatus.REQUIRES_INTERACTION)

    def test_missing_ocr_dependency_is_reported(self):
        with patch.object(mtc_stealth, "_new_ocr", side_effect=mtc_stealth.MtcOcrUnavailable("Falta OCR")):
            result = query_mtc_stealth("ABC123", 10)
        self.assertEqual(result.status, QueryStatus.UNAVAILABLE)
        self.assertIn("OCR", result.message)

    def test_form_failure_is_unavailable(self):
        session = FakeSession(form_status=503)
        result = query_mtc_stealth(
            "ABC123", 10, session_factory=lambda **_: session, ocr=FakeOcr(["123456"])
        )
        self.assertEqual(result.status, QueryStatus.UNAVAILABLE)

    def test_normalizes_plate_in_query(self):
        session = FakeSession(responses=[success_payload()])
        result = query_mtc_stealth(
            " abc-123 ", 10, session_factory=lambda **_: session, ocr=FakeOcr(["123456"])
        )
        self.assertEqual(result.plate, "ABC123")
        self.assertIn("ABC123", session.codes[0])


if __name__ == "__main__":
    unittest.main()
