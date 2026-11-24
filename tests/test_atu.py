"""ATU: parser de la foto de la pagina y conector stealth con pagina falsa.

Las filas con infracciones son sinteticas: imitan las columnas reales de la
pasarela (inspeccionadas el 23/11/2026), no datos de una placa real.
"""
import unittest

from obd_consultas.contracts import AtuData, validate_data
from obd_consultas.domain.models import QueryStatus, Source
from obd_consultas.infrastructure import atu_stealth
from obd_consultas.providers import atu

HEAD = [
    "Ver Acta", "Seleccionar", "Placa", "Tipo Acta", "Reglamento", "Acta Fiscalización",
    "Falta", "Tipo Infractor", "Fecha Infracción", "¿Reincidencia?", "Importe",
    "Gastos/Costas", "Total Deuda", "Total Pagado", "Total a Pagar", "Estado",
]
NO_INFRACTION = "La placa consultada no cuenta con infracción registrada al momento de la consulta."


def row(plate="ABC123", acta="A-0001"):
    return ["", "", plate, "TRANSPORTE", "DS 017-2009", acta, "F.1", "TRANSPORTISTA",
            "01/02/2026", "NO", "S/ 500.00", "S/ 0.00", "S/ 500.00", "S/ 0.00", "S/ 500.00", "PENDIENTE"]


def snapshot(**values):
    base = {"modal": None, "icon": None, "head": HEAD, "rows": [["Sin Registros"]], "counter": None}
    base.update(values)
    return base


class ParserTests(unittest.TestCase):
    def test_column_key(self):
        self.assertEqual(atu.column_key("Acta Fiscalización"), "acta_fiscalizacion")
        self.assertEqual(atu.column_key("¿Reincidencia?"), "reincidencia")
        self.assertEqual(atu.column_key("Gastos/Costas"), "gastos_costas")

    def test_no_infraction_like_real_page(self):
        result = atu.result_from_snapshot("abc-123", snapshot(modal=NO_INFRACTION, icon="info"))
        self.assertEqual(result.status, QueryStatus.NOT_FOUND)
        self.assertFalse(result.data["tiene_infracciones"])
        self.assertEqual(result.data["mensaje"], NO_INFRACTION)
        self.assertIsInstance(validate_data(result), AtuData)

    def test_rows_become_infractions_without_action_columns(self):
        result = atu.result_from_snapshot(
            "ABC123", snapshot(rows=[row(), row(acta="A-0002")], counter="Registros 1 - 2 de 2")
        )
        self.assertEqual(result.status, QueryStatus.SUCCESS)
        first = result.data["infracciones"][0]
        self.assertEqual(first["acta_fiscalizacion"], "A-0001")
        self.assertEqual(first["total_a_pagar"], "S/ 500.00")
        self.assertNotIn("ver_acta", first)
        self.assertNotIn("seleccionar", first)
        self.assertTrue(result.data["completo"])
        self.assertIsInstance(validate_data(result), AtuData)

    def test_more_pages_marks_incomplete(self):
        result = atu.result_from_snapshot("ABC123", snapshot(rows=[row()], counter="Registros 1 - 10 de 14"))
        self.assertEqual(result.data["total_registros"], 14)
        self.assertFalse(result.data["completo"])

    def test_row_for_other_plate_is_parse_error(self):
        result = atu.result_from_snapshot("ABC123", snapshot(rows=[row(plate="XYZ999")]))
        self.assertEqual(result.status, QueryStatus.PARSE_ERROR)
        self.assertEqual(result.data, {})

    def test_unknown_notice_is_not_not_found(self):
        result = atu.result_from_snapshot("ABC123", snapshot(modal="Sistema en mantenimiento", icon="info"))
        self.assertEqual(result.status, QueryStatus.PARSE_ERROR)

    def test_error_notice_is_unavailable(self):
        result = atu.result_from_snapshot("ABC123", snapshot(modal="Servicio no disponible", icon="error"))
        self.assertEqual(result.status, QueryStatus.UNAVAILABLE)

    def test_recaptcha_notice_requires_interaction(self):
        result = atu.result_from_snapshot("ABC123", snapshot(modal="Error de validación captcha", icon="error"))
        self.assertEqual(result.status, QueryStatus.REQUIRES_INTERACTION)

    def test_basic_mode_requires_stealth(self):
        result = atu.AtuProvider().query("abc123")
        self.assertEqual(result.source, Source.ATU)
        self.assertEqual(result.status, QueryStatus.REQUIRES_INTERACTION)
        self.assertIn("--stealth", result.message)


class FakeLocator:
    def __init__(self, page, name):
        self.page, self.name = page, name

    @property
    def first(self):
        return self

    def dispatch_event(self, _event):
        self.page.actions.append(("menu", self.name))

    def fill(self, value, **_):
        self.page.actions.append(("fill", value))

    def click(self, **_):
        self.page.actions.append(("click", self.name))
        self.page.searched = True


class FakePage:
    def __init__(self, result_after=1, result=None):
        self.actions = []
        self.searched = False
        self.polls = 0
        self.result_after = result_after
        self.result = result or snapshot(modal=NO_INFRACTION, icon="info")

    def wait_for_timeout(self, _ms):
        pass

    def wait_for_selector(self, *_args, **_kwargs):
        pass

    @property
    def keyboard(self):
        return self

    def press(self, key):
        self.actions.append(("key", key))

    def get_by_text(self, text, **_):
        return FakeLocator(self, text)

    def get_by_role(self, _role, name, **_):
        return FakeLocator(self, name)

    def locator(self, selector):
        return FakeLocator(self, selector)

    def evaluate(self, script):
        if script == atu_stealth.SELECT_PLATE:
            self.actions.append(("select", "placa"))
            return None
        assert self.searched, "no se debe leer resultado antes de buscar"
        self.polls += 1
        return self.result if self.polls >= self.result_after else snapshot()


class FakeSession:
    def __init__(self, page):
        self.page = page

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def fetch(self, _url, page_action, **_):
        page_action(self.page)


class ConnectorTests(unittest.TestCase):
    def run_query(self, *pages, timeout=120):
        pages = list(pages)
        used = []

        def factory(**_options):
            page = pages.pop(0)
            used.append(page)
            return FakeSession(page)

        return atu_stealth.query_atu_stealth("ABC123", timeout, session_factory=factory), used

    def test_selects_plate_search_and_reads_notice(self):
        result, used = self.run_query(FakePage(result_after=3))
        self.assertEqual(result.status, QueryStatus.NOT_FOUND)
        self.assertEqual(result.data["capture"]["method"], "stealth_dom")
        self.assertEqual(
            used[0].actions,
            [("key", "Escape"), ("menu", atu_stealth.MENU_ITEM), ("select", "placa"),
             ("fill", "ABC123"), ("click", "BUSCAR")],
        )

    def test_retries_with_new_session_when_page_shows_nothing(self):
        silent = FakePage(result_after=10_000)
        result, used = self.run_query(silent, FakePage())
        self.assertEqual(len(used), 2)
        self.assertEqual(result.status, QueryStatus.NOT_FOUND)

    def test_gives_up_after_max_sessions(self):
        result, used = self.run_query(*(FakePage(result_after=10_000) for _ in range(atu_stealth.MAX_SESSIONS)))
        self.assertEqual(len(used), atu_stealth.MAX_SESSIONS)
        self.assertEqual(result.status, QueryStatus.REQUIRES_INTERACTION)
        self.assertEqual(result.data, {})

    def test_browser_error_is_unavailable(self):
        class Broken(FakePage):
            def wait_for_selector(self, *_args, **_kwargs):
                raise RuntimeError("selector roto")

        result, _ = self.run_query(Broken())
        self.assertEqual(result.status, QueryStatus.UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
