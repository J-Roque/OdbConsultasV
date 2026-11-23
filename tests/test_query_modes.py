import unittest
from unittest.mock import patch

from obd_consultas.application.queries import QueryService
from obd_consultas.bootstrap import PROVIDERS, RUNNERS, build_service
from obd_consultas.domain.models import (
    InvalidPlate,
    QueryMode,
    QueryResult,
    QueryStatus,
    Source,
    UnsupportedMode,
)


class QueryModeTests(unittest.TestCase):
    def test_bootstrap_mode_matrix(self):
        service = build_service()
        self.assertEqual(
            {s: service.modes(s) for s in Source},
            {
                Source.SOAT: [QueryMode.BASIC, QueryMode.STEALTH, QueryMode.ASSISTED],
                Source.SUNARP: [QueryMode.BASIC, QueryMode.STEALTH],
                Source.MTC: [QueryMode.BASIC, QueryMode.STEALTH, QueryMode.ASSISTED],
                Source.SUTRAN: [QueryMode.BASIC, QueryMode.STEALTH],
            },
        )
        self.assertEqual(service.sources_for(QueryMode.ASSISTED), [Source.SOAT, Source.MTC])

    def test_run_normalizes_and_forwards_options(self):
        calls = []

        def runner(plate, timeout, **options):
            calls.append((plate, timeout, options))
            return QueryResult(Source.MTC, plate, QueryStatus.SUCCESS, "", "ok")

        service = QueryService(
            (cls() for cls in PROVIDERS.values()), {(Source.MTC, QueryMode.STEALTH): runner}
        )
        result = service.run(Source.MTC, " abc-123 ", QueryMode.STEALTH, timeout=30, headless=False)
        self.assertEqual(result.status, QueryStatus.SUCCESS)
        self.assertEqual(calls, [("ABC123", 30, {"headless": False})])

    def test_validates_before_running(self):
        def runner(*_args, **_kwargs):
            raise AssertionError("no debe ejecutarse")

        service = QueryService(
            (cls() for cls in PROVIDERS.values()), {(Source.SOAT, QueryMode.STEALTH): runner}
        )
        with self.assertRaises(InvalidPlate):
            service.run(Source.SOAT, "??", QueryMode.STEALTH)
        with self.assertRaises(UnsupportedMode):
            service.run(Source.SUNARP, "ABC123", QueryMode.STEALTH)
        for timeout in (9, 601):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                service.run(Source.SOAT, "ABC123", QueryMode.STEALTH, timeout=timeout)

    def test_basic_mode_uses_provider(self):
        result = build_service().run(Source.SUNARP, "abc123")
        self.assertEqual(result.status, QueryStatus.REQUIRES_INTERACTION)

    def test_rejects_inconsistent_registry(self):
        noop = lambda *a, **k: None  # noqa: E731
        with self.assertRaises(ValueError):
            QueryService([PROVIDERS[Source.SOAT]()], {(Source.MTC, QueryMode.STEALTH): noop})
        with self.assertRaises(ValueError):
            QueryService([PROVIDERS[Source.SOAT]()], {(Source.SOAT, QueryMode.BASIC): noop})

    def test_lazy_runner_imports_on_call_and_drops_none_options(self):
        runner = RUNNERS[(Source.SUNARP, QueryMode.STEALTH)]
        with patch(
            "obd_consultas.infrastructure.sunarp_stealth.query_sunarp_stealth",
            return_value="resultado",
        ) as target:
            self.assertEqual(runner("ABC123", 60, headless=True, proxy=None), "resultado")
        target.assert_called_once_with("ABC123", 60, headless=True)

    def test_assisted_runner_passes_browser_channel(self):
        runner = RUNNERS[(Source.MTC, QueryMode.ASSISTED)]
        with patch(
            "obd_consultas.infrastructure.mtc_browser.query_mtc_interactive",
            return_value="resultado",
        ) as target:
            runner("ABC123", 60, browser="chrome")
            runner("ABC123", 60)
        self.assertEqual(
            [c.args for c in target.call_args_list],
            [("ABC123", 60, "chrome"), ("ABC123", 60, "msedge")],
        )


if __name__ == "__main__":
    unittest.main()
