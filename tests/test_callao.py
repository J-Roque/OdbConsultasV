"""Callao: parser de pagopapeletascallao.pe y conector HTTP con OCR.

El HTML es sintetico: imita la forma real del formulario Laravel y del aviso de
sin resultados (inspeccionados el 23/11/2026). La tabla con papeletas es una
suposicion basada en ``#dataTable`` del script del portal.
"""
import base64
import os
import tempfile
import unittest
from unittest.mock import patch

from obd_consultas.contracts import CallaoData, validate_data
from obd_consultas.domain.models import QueryStatus, Source
from obd_consultas.infrastructure import callao_stealth
from obd_consultas.providers import callao

FORM = """<html><body>
<!-- <form id="formBuscar" action="https://otro.host/buscar"><input type="hidden" name="_token" value="viejo"></form> -->
<form id="formBuscar" action="/buscar" method="post">
<input type="hidden" name="_token" value="tok{n}"><input type="hidden" name="captcha_key" value="key{n}">
<select name="tipo_busqueda"><option value="1">Numero de Placa</option></select>
</form>
<!-- <img src="https://otro.host/captcha/default" alt="captcha"> -->
<img src="data:image/png;base64,{png}" alt="captcha">
<input type="text" name="captcha" id="captcha" maxlength="3">
{result}
</body></html>"""

NO_RESULTS = '<div class="table-responsive"><p class="alert alert-info">No hay resultados para mostrar.</p></div>'
TABLE = """<table id="dataTable"><thead><tr><th></th><th>Placa</th><th>Cod. Infraccion</th>
<th>N° Papeleta</th><th>Fecha</th><th>Infractor</th><th>Importe</th><th>Cuota</th></tr></thead>
<tbody>{rows}</tbody></table>"""
ROW = ("<tr><td><input type='checkbox'></td><td>{plate}</td><td>M20</td><td>{num}</td>"
       "<td>01/02/2026</td><td>JUAN PEREZ</td><td>S/ 462.00</td><td>1</td></tr>")
WRONG_URL = "https://pagopapeletascallao.pe/?error=Error%20al%20ingresar%20el%20c%C3%B3digo%20de%20seguridad"


def page(n=1, result=""):
    return FORM.format(n=n, png=base64.b64encode(f"png-{n}".encode()).decode(), result=result)


def table(*rows):
    return TABLE.format(rows="".join(rows))


class ParserTests(unittest.TestCase):
    def test_fields_and_captcha_ignore_commented_markup(self):
        self.assertEqual(callao.form_fields(page(n=4)), {"_token": "tok4", "captcha_key": "key4"})
        self.assertEqual(callao.captcha_image(page(n=4)), b"png-4")

    def test_no_results_like_real_page(self):
        result = callao.result_from_html("ABC-123", page(result=NO_RESULTS), callao.CALLAO_SEARCH_URL)
        self.assertEqual(result.status, QueryStatus.NOT_FOUND)
        self.assertFalse(result.data["tiene_papeletas"])
        self.assertEqual(result.data["mensaje"], "No hay resultados para mostrar.")
        self.assertIsInstance(validate_data(result), CallaoData)

    def test_table_rows_without_personal_columns(self):
        html = page(result=table(ROW.format(plate="ABC123", num="P1"), ROW.format(plate="ABC123", num="P2")))
        result = callao.result_from_html("ABC123", html)
        self.assertEqual(result.status, QueryStatus.SUCCESS)
        first = result.data["papeletas"][0]
        self.assertEqual(first["n_papeleta"], "P1")
        self.assertEqual(first["importe"], "S/ 462.00")
        self.assertNotIn("infractor", first)
        self.assertNotIn("JUAN PEREZ", first.values())
        self.assertIsInstance(validate_data(result), CallaoData)

    def test_row_for_other_plate_is_parse_error(self):
        result = callao.result_from_html("ABC123", page(result=table(ROW.format(plate="XYZ999", num="P1"))))
        self.assertEqual(result.status, QueryStatus.PARSE_ERROR)
        self.assertEqual(result.data, {})

    def test_wrong_captcha_redirect_raises(self):
        with self.assertRaises(callao.CallaoCaptchaRejected):
            callao.result_from_html("ABC123", page(), WRONG_URL)

    def test_other_portal_error_is_parse_error(self):
        url = "https://pagopapeletascallao.pe/?error=Servicio%20no%20disponible"
        result = callao.result_from_html("ABC123", page(), url)
        self.assertEqual(result.status, QueryStatus.PARSE_ERROR)
        self.assertIn("Servicio no disponible", result.message)

    def test_unknown_page_is_parse_error_not_not_found(self):
        result = callao.result_from_html("ABC123", page(result="<p>Mantenimiento</p>"))
        self.assertEqual(result.status, QueryStatus.PARSE_ERROR)

    def test_basic_mode_requires_stealth(self):
        result = callao.CallaoProvider().query("abc123")
        self.assertEqual(result.source, Source.CALLAO)
        self.assertEqual(result.status, QueryStatus.REQUIRES_INTERACTION)
        self.assertIn("--stealth", result.message)


class Response:
    def __init__(self, body, url=callao.CALLAO_SEARCH_URL, status=200):
        self.body = body.encode()
        self.url = url
        self.status = status


class FakeSession:
    def __init__(self, posts):
        self.posts = list(posts)
        self.sent = []
        self.forms = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, **_):
        self.forms += 1
        return Response(page(n=self.forms), url=url)

    def post(self, url, data, **_):
        self.sent.append(dict(data))
        return self.posts.pop(0)


class Ocr:
    def __init__(self, *codes):
        self.codes = list(codes)

    def classification(self, _image):
        return self.codes.pop(0)


class ConnectorTests(unittest.TestCase):
    def run_query(self, posts, codes, **kwargs):
        session = FakeSession(posts)
        result = callao_stealth.query_callao_stealth(
            "ABC123", 60, session_factory=lambda: session, ocr=Ocr(*codes), **kwargs
        )
        return result, session

    def test_retries_with_new_form_after_wrong_captcha(self):
        wrong = Response(page(), url=WRONG_URL)
        result, session = self.run_query([wrong, Response(page(result=NO_RESULTS))], ["123", "a7B"])
        self.assertEqual(result.status, QueryStatus.NOT_FOUND)
        self.assertEqual(result.data["capture"]["attempts"], 2)
        self.assertEqual(session.sent[0]["valor_busqueda"], "ABC123")
        self.assertEqual(session.sent[0]["tipo_busqueda"], callao.SEARCH_BY_PLATE)
        # El segundo envio usa el token y el codigo del formulario nuevo.
        self.assertEqual(session.sent[1]["_token"], "tok2")
        self.assertEqual(session.sent[1]["captcha"], "a7B")
        self.assertIsInstance(validate_data(result), CallaoData)

    def test_unreadable_captcha_loads_new_form_without_posting(self):
        result, session = self.run_query([Response(page(result=NO_RESULTS))], ["??", "123"])
        self.assertEqual(result.status, QueryStatus.NOT_FOUND)
        self.assertEqual(len(session.sent), 1)
        self.assertEqual(session.forms, 2)

    def test_gives_up_after_max_attempts(self):
        result, _ = self.run_query([], ["?", "?"], max_attempts=2)
        self.assertEqual(result.status, QueryStatus.REQUIRES_INTERACTION)
        self.assertEqual(result.data, {})

    def test_http_error_is_unavailable(self):
        result, _ = self.run_query([Response("", status=500)], ["123"])
        self.assertEqual(result.status, QueryStatus.UNAVAILABLE)

    def test_parse_error_saves_html_when_debug_dir_set(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {callao_stealth.DEBUG_ENV: folder}):
                result, _ = self.run_query([Response(page(result="<p>Nueva</p>"))], ["123"])
            files = os.listdir(folder)
        self.assertEqual(result.status, QueryStatus.PARSE_ERROR)
        self.assertEqual(len(files), 1)
        self.assertIn(files[0], result.message)


if __name__ == "__main__":
    unittest.main()
