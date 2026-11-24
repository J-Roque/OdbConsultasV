"""Normaliza la consulta de orden de captura del SAT de Lima.

El portal es un formulario ASP.NET (placa + captcha de imagen) que devuelve el
resultado en la misma pagina. Este modulo solo interpreta el HTML; la sesion y
el captcha viven en :mod:`obd_consultas.infrastructure.sat_stealth`.

El caso "sin orden de captura" se valido con una respuesta real el 24/11/2026.
El caso "con orden" sigue siendo provisional (tabla generica en ``divCapturas``),
por eso la fuente queda ``implemented=False``.
"""
from __future__ import annotations

import re
from typing import Any

from obd_consultas.domain.models import QueryResult, QueryStatus, Source, normalize_plate
from obd_consultas.infrastructure.scrapling_engine import parse_html
from obd_consultas.providers.catalog import SOURCES

SAT_INFO = next(info for info in SOURCES if info.source == Source.SAT)
SAT_FORM_URL = SAT_INFO.url

CAPTCHA_FIELD = "ctl00$cplPrincipal$txtCaptcha"
PLATE_FIELD = "ctl00$cplPrincipal$txtPlaca"
SUBMIT_FIELD = "ctl00$cplPrincipal$CaptchaContinue"

_NO_ORDER = re.compile(
    r"no (tiene|registra|presenta|cuenta con|se encontr)|sin orden|no existe", re.IGNORECASE
)
_DATE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


class SatParseError(ValueError):
    pass


class SatCaptchaRejected(SatParseError):
    """El portal rechazo el codigo de seguridad: hay que pedir otro captcha."""


def _clean(text: object) -> str:
    return " ".join(str(text or "").split())


def form_fields(html: str | bytes) -> dict[str, str]:
    """Campos ocultos de ASP.NET que hay que reenviar en el POST."""
    page = parse_html(html, url=SAT_FORM_URL)
    fields: dict[str, str] = {}
    for node in page.css("input[type=hidden]"):
        name = node.attrib.get("name")
        if name:
            fields[str(name)] = str(node.attrib.get("value") or "")
    if "__VIEWSTATE" not in fields:
        raise SatParseError("El formulario del SAT no trae __VIEWSTATE.")
    submit = page.css(f"input[name='{SUBMIT_FIELD}']").first
    fields[SUBMIT_FIELD] = str(submit.attrib.get("value") or "") if submit is not None else ""
    return fields


def captcha_url(html: str | bytes) -> str:
    """URL absoluta de la imagen del captcha de esta pagina."""
    page = parse_html(html, url=SAT_FORM_URL)
    for node in page.css("img"):
        src = str(node.attrib.get("src") or "")
        if "jpegimage" in src.lower():
            return str(page.urljoin(src))
    raise SatParseError("La pagina no trae la imagen del captcha.")


def _label(page: Any, suffix: str) -> str:
    """Texto de la etiqueta ``ctl00_cplPrincipal_<suffix>`` (vacio si no esta)."""
    node = page.css(f"[id='ctl00_cplPrincipal_{suffix}']").first
    return _clean(node.get_all_text(strip=True)) if node is not None else ""


def _iso_date(text: str) -> str | None:
    match = _DATE.search(text)
    if match is None:
        return None
    day, month, year = match.groups()
    return f"{year}-{int(month):02d}-{int(day):02d}"


def _tables(page: Any) -> list[dict[str, str]]:
    """Filas de las tablas de resultado dentro de ``divCapturas``, con su encabezado."""
    rows: list[dict[str, str]] = []
    for table in page.css("[id='ctl00_cplPrincipal_divCapturas'] table"):
        trs = table.css("tr")
        if len(trs) < 2:
            continue
        header = [_clean(c.get_all_text(strip=True)).lower() for c in trs[0].css("th, td")]
        if len(header) < 2 or any(not h for h in header):
            continue
        for tr in trs[1:]:
            cells = [_clean(c.get_all_text(strip=True)) for c in tr.css("td")]
            if any(cells):
                rows.append(dict(zip(header, cells, strict=False)))
    return rows


def parse_capturas(html: str | bytes, plate: str) -> dict[str, object]:
    """Lee la pagina de resultado. Lanza ``SatCaptchaRejected`` si el codigo fallo.

    Validado el 24/11/2026 con una respuesta real sin orden de captura:
    ``lblMensajeVacio`` trae el mensaje y ``lblFecha`` la fecha del informe.
    El caso con orden (tabla en ``divCapturas``) aun no se vio en real.
    """
    normalize_plate(plate)
    page = parse_html(html, url=SAT_FORM_URL)
    captcha_error = _label(page, "lblMensajeCapcha")
    if captcha_error:
        raise SatCaptchaRejected(captcha_error)

    mensaje = _label(page, "lblMensajeVacio") or None
    actualizado_al = _iso_date(_label(page, "lblFecha"))
    ordenes = [
        {"detalle": " · ".join(v for v in row.values() if v), "campos": row}
        for row in _tables(page)
    ]
    if ordenes:
        return {
            "tiene_orden_captura": True,
            "ordenes": ordenes,
            "mensaje": mensaje,
            "actualizado_al": actualizado_al,
        }
    if mensaje and _NO_ORDER.search(mensaje):
        return {
            "tiene_orden_captura": False,
            "ordenes": [],
            "mensaje": mensaje,
            "actualizado_al": actualizado_al,
        }
    raise SatParseError(
        "No se reconocio la respuesta del SAT. Se guarda el HTML para ajustar el parser."
    )


def sat_result(
    plate: str, status: QueryStatus, message: str, data: dict | None = None
) -> QueryResult:
    return QueryResult(Source.SAT, plate, status, SAT_INFO.url, message, data or {})


def result_from_html(plate: str, html: str | bytes) -> QueryResult:
    """``SatCaptchaRejected`` se propaga para que el conector reintente."""
    plate = normalize_plate(plate)
    try:
        data = parse_capturas(html, plate)
    except SatCaptchaRejected:
        raise
    except SatParseError as exc:
        return sat_result(plate, QueryStatus.PARSE_ERROR, str(exc))
    if data["tiene_orden_captura"]:
        return sat_result(
            plate, QueryStatus.SUCCESS, "El SAT de Lima registra orden de captura para esta placa.", data
        )
    return sat_result(
        plate, QueryStatus.NOT_FOUND, "El SAT de Lima no registra orden de captura para esta placa.", data
    )


class SatProvider:
    info = SAT_INFO

    def query(self, plate: str) -> QueryResult:
        return sat_result(
            normalize_plate(plate),
            QueryStatus.REQUIRES_INTERACTION,
            "El SAT de Lima protege la consulta con un captcha de imagen. Usa el modo stealth (OCR local).",
        )
