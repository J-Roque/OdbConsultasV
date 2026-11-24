"""SAT de Lima (orden de captura): parser provisional y conector con OCR.

Todo el HTML es sintetico: imita la forma del formulario ASP.NET inspeccionado,
no respuestas reales del portal.
"""
import os
import tempfile
import unittest
from unittest.mock import patch

from obd_consultas.contracts import SatData, validate_data
from obd_consultas.domain.models import QueryStatus, Source
from obd_consultas.infrastructure import sat_stealth
from obd_consultas.providers import sat

FORM = """<html><body><form method="post" action="./Capturas.aspx">
<input type="hidden" name="__VIEWSTATE" value="vs{n}">
<input type="hidden" name="__VIEWSTATEGENERATOR" value="gen">
<input type="hidden" name="__EVENTVALIDATION" value="ev{n}">
<span id="ctl00_cplPrincipal_lblTitulo">CAPTURA DE VEHICULOS</span>
<div id="ctl00_cplPrincipal_busqPlaca">Placa:</div>
<input type="text" name="ctl00$cplPrincipal$txtPlaca">
<img src="../controles/JpegImage_VB.aspx?r={n}">
<input type="text" name="ctl00$cplPrincipal$txtCaptcha">
<input type="submit" name="ctl00$cplPrincipal$CaptchaContinue" value="Buscar">
<span id="ctl00_cplPrincipal_lblMensajeCapcha" style="color:Red;">{captcha}</span>
<div id="ctl00_cplPrincipal_fecConsulta"><span id="ctl00_cplPrincipal_lblMensajeVacio">{msg}</span></div>
<div id="ctl00_cplPrincipal_divCapturas" class="tabla_smallxx">
<span id="ctl00_cplPrincipal_lblFecha">{fecha}</span>
{extra}
</div>
</form></body></html>"""

NO_ORDER = "El vehículo de placa ABC123 no tiene orden de captura en la provincia de Lima."


def page(n=1, msg="", extra="", captcha="", fecha=""):
    return FORM.format(n=n, msg=msg, extra=extra, captcha=captcha, fecha=fecha)


ORDER_TABLE = """<table id="ctl00_cplPrincipal_grdCapturas">
<tr><th>Placa</th><th>Motivo</th><th>Fecha</th></tr>
<tr><td>ABC123</td><td>PAPELETAS</td><td>01/02/2026</td></tr>
</table>"""


class Response:
    def __init__(self, body, status=200):
        self.body = body.encode() if isinstance(body, str) else body
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
        if "JpegImage" in url:
            return Response(b"img")
        self.forms += 1
        return Response(page(n=self.forms))

    def post(self, url, data, **_):
        self.sent.append(dict(data))
        return Response(self.posts.pop(0))


class Ocr:
    def __init__(self, *codes):
        self.codes = list(codes)

    def classification(self, _image):
        return self.codes.pop(0)


class ParserTests(unittest.TestCase):
    def test_form_fields_and_captcha_url(self):
        fields = sat.form_fields(page(n=7))
        self.assertEqual(fields["__VIEWSTATE"], "vs7")
        self.assertEqual(fields[sat.SUBMIT_FIELD], "Buscar")
        self.assertEqual(
            sat.captcha_url(page(n=7)),
            "https://www.sat.gob.pe/VirtualSAT/controles/JpegImage_VB.aspx?r=7",
        )

    def test_order_found(self):
        result = sat.result_from_html("ABC-123", page(extra=ORDER_TABLE))
        self.assertEqual(result.status, QueryStatus.SUCCESS)
        self.assertTrue(result.data["tiene_orden_captura"])
        self.assertEqual(result.data["ordenes"][0]["campos"]["motivo"], "PAPELETAS")
        self.assertIn("PAPELETAS", result.data["ordenes"][0]["detalle"])
        self.assertIsInstance(validate_data(result), SatData)

    def test_no_order_like_real_response(self):
        html = page(msg=NO_ORDER, fecha="Informe actualizado al 22/11/2026")
        result = sat.result_from_html("ABC123", html)
        self.assertEqual(result.status, QueryStatus.NOT_FOUND)
        self.assertFalse(result.data["tiene_orden_captura"])
        self.assertEqual(result.data["mensaje"], NO_ORDER)
        self.assertEqual(result.data["actualizado_al"], "2026-11-22")
        self.assertIsInstance(validate_data(result), SatData)

    def test_captcha_rejected(self):
        with self.assertRaises(sat.SatCaptchaRejected):
            sat.parse_capturas(page(captcha="Codigo de seguridad incorrecto."), "ABC123")

    def test_unknown_page_is_parse_error_not_not_found(self):
        result = sat.result_from_html("ABC123", page(msg="Mantenimiento programado."))
        self.assertEqual(result.status, QueryStatus.PARSE_ERROR)
        self.assertEqual(result.data, {})

    def test_basic_mode_requires_stealth(self):
        result = sat.SatProvider().query("abc123")
        self.assertEqual(result.source, Source.SAT)
        self.assertEqual(result.status, QueryStatus.REQUIRES_INTERACTION)


class ConnectorTests(unittest.TestCase):
    def run_query(self, posts, codes, **kwargs):
        session = FakeSession(posts)
        result = sat_stealth.query_sat_stealth(
            "ABC123", 60, session_factory=lambda: session, ocr=Ocr(*codes), **kwargs
        )
        return result, session

    def test_retries_after_rejected_captcha(self):
        rejected = page(n=9, captcha="Codigo de seguridad incorrecto")
        result, session = self.run_query([rejected, page(extra=ORDER_TABLE)], ["ab12", "CD34"])
        self.assertEqual(result.status, QueryStatus.SUCCESS)
        self.assertEqual(result.data["capture"]["method"], "stealth_ocr")
        self.assertEqual(result.data["capture"]["attempts"], 2)
        self.assertEqual(session.sent[0][sat.CAPTCHA_FIELD], "AB12")
        self.assertEqual(session.sent[0][sat.PLATE_FIELD], "ABC123")
        # El segundo envio usa el __VIEWSTATE de la pagina que rechazo el codigo.
        self.assertEqual(session.sent[1]["__VIEWSTATE"], "vs9")
        self.assertIsInstance(validate_data(result), SatData)

    def test_unreadable_captcha_reloads_form(self):
        result, session = self.run_query(
            [page(msg=NO_ORDER)], ["??", "XY99"]
        )
        self.assertEqual(result.status, QueryStatus.NOT_FOUND)
        self.assertEqual(len(session.sent), 1)
        self.assertEqual(session.forms, 2)

    def test_gives_up_after_max_attempts(self):
        result, _ = self.run_query([], ["?", "?"], max_attempts=2)
        self.assertEqual(result.status, QueryStatus.REQUIRES_INTERACTION)
        self.assertEqual(result.data, {})

    def test_parse_error_saves_raw_html_when_debug_dir_set(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {sat_stealth.DEBUG_ENV: folder}):
                result, _ = self.run_query([page(msg="Pagina nueva")], ["AB12"])
            files = os.listdir(folder)
        self.assertEqual(result.status, QueryStatus.PARSE_ERROR)
        self.assertEqual(len(files), 1)
        self.assertIn(files[0], result.message)

    def test_no_debug_file_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(sat_stealth.DEBUG_ENV, None)
            with patch.object(sat_stealth.Path, "write_bytes") as write:
                self.run_query([page(msg=NO_ORDER)], ["AB12"])
        write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
