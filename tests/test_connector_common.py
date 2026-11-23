import unittest

from obd_consultas.domain.models import QueryResult, QueryStatus, Source
from obd_consultas.infrastructure.connector_common import (
    MISSING_BROWSER,
    guarded,
    http_status,
    is_timeout,
    result_from_api,
    result_from_error,
    safe_json,
    session_failure,
    stamp_capture,
    validate_timeout,
)
from obd_consultas.infrastructure.scrapling_engine import ScraplingUnavailable


def make(plate, status, message, data=None):
    return QueryResult(Source.SOAT, plate, status, "", message, data or {})


class TimeoutError(Exception):  # mismo nombre que el de Playwright/Patchright
    pass


class CommonTests(unittest.TestCase):
    def test_validate_timeout(self):
        validate_timeout(10)
        validate_timeout(600)
        for value in (9, 601):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_timeout(value)

    def test_small_helpers(self):
        self.assertTrue(is_timeout(TimeoutError()))
        self.assertFalse(is_timeout(RuntimeError()))
        self.assertFalse(is_timeout(None))
        self.assertEqual(http_status("200"), 200)
        self.assertEqual(http_status(None), 0)

        class Broken:
            def json(self):
                raise ValueError

        self.assertIsNone(safe_json(Broken()))

    def test_stamp_capture_only_on_final_results(self):
        ok = stamp_capture(make("ABC123", QueryStatus.SUCCESS, "ok"), "stealth_ocr", attempts=2)
        self.assertEqual(ok.data["capture"]["method"], "stealth_ocr")
        self.assertEqual(ok.data["capture"]["attempts"], 2)
        pending = stamp_capture(make("ABC123", QueryStatus.UNAVAILABLE, "x"), "stealth_api")
        self.assertNotIn("capture", pending.data)

    def test_result_from_api(self):
        seen = []

        def parse(plate, status, payload):
            seen.append((plate, status, payload))
            return make(plate, QueryStatus.SUCCESS, "ok")

        result = result_from_api({"status": "200", "payload": {"a": 1}}, "ABC123", parse)
        self.assertEqual(seen, [("ABC123", 200, {"a": 1})])
        self.assertEqual(result.data["capture"]["method"], "stealth_api")

    def test_result_from_error_never_succeeds(self):
        cases = {
            "timeout": ({"error": TimeoutError()}, QueryStatus.REQUIRES_INTERACTION),
            "error": ({"error": RuntimeError()}, QueryStatus.UNAVAILABLE),
            "empty": ({}, QueryStatus.REQUIRES_INTERACTION),
        }
        for name, (holder, expected) in cases.items():
            with self.subTest(name):
                self.assertEqual(result_from_error("ABC123", holder, make).status, expected)

    def test_session_failure(self):
        cases = (
            (ScraplingUnavailable("Scrapling no esta instalado."), QueryStatus.UNAVAILABLE, "Scrapling"),
            (RuntimeError("Executable doesn't exist at x"), QueryStatus.UNAVAILABLE, MISSING_BROWSER),
            (RuntimeError("Cloudflare challenge"), QueryStatus.REQUIRES_INTERACTION, "Cloudflare"),
            (RuntimeError("otra cosa"), QueryStatus.UNAVAILABLE, "sesion"),
        )
        for exc, status, text in cases:
            with self.subTest(exc=str(exc)):
                result = session_failure("ABC123", exc, make)
                self.assertEqual(result.status, status)
                self.assertIn(text, result.message)

    def test_guarded_stores_exception(self):
        holder = {}
        guarded(lambda page: (_ for _ in ()).throw(RuntimeError("x")), holder)("pagina")
        self.assertIsInstance(holder["error"], RuntimeError)


if __name__ == "__main__":
    unittest.main()
