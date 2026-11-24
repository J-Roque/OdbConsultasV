"""Papeletas de transito de la Municipalidad Provincial del Callao.

Portal: pagopapeletascallao.pe (enlazado desde gob.pe/municallao). Formulario
Laravel: ``_token``, ``captcha_key``, ``tipo_busqueda`` (1 = placa),
``valor_busqueda`` y ``captcha`` (3 caracteres, imagen PNG en linea).

Respuestas observadas:

- Codigo incorrecto: redireccion a ``/?error=Error al ingresar el codigo de seguridad``.
- Sin papeletas: ``<p class="alert alert-info">No hay resultados para mostrar.</p>``.
- Con papeletas: tabla ``#dataTable`` (columnas leidas desde su ``thead``).
"""
from __future__ import annotations

import base64
import binascii
import re
import unicodedata
from urllib.parse import parse_qs, urlparse

from obd_consultas.domain.models import QueryResult, QueryStatus, Source, normalize_plate
from obd_consultas.infrastructure.scrapling_engine import parse_html
from obd_consultas.providers.catalog import SOURCES

CALLAO_INFO = next(info for info in SOURCES if info.source == Source.CALLAO)
CALLAO_FORM_URL = "https://pagopapeletascallao.pe/"
CALLAO_SEARCH_URL = "https://pagopapeletascallao.pe/buscar"
SEARCH_BY_PLATE = "1"
_COMMENTS = re.compile(r"<!--.*?-->", re.DOTALL)
_NO_RESULTS = re.compile(r"no hay resultados para mostrar", re.IGNORECASE)
_CAPTCHA_ERROR = re.compile(r"c.digo de seguridad|captcha", re.IGNORECASE)
# Columnas que podrian identificar a una persona: no se exponen.
_PERSONAL = re.compile(r"nombre|infractor|conductor|propietario|dni|documento|direccion")


class CallaoParseError(ValueError):
    pass


class CallaoCaptchaRejected(CallaoParseError):
    pass


def _html(content: str | bytes) -> str:
    text = content.decode("utf-8", "replace") if isinstance(content, bytes) else content
    # El portal deja formularios e imagenes antiguos dentro de comentarios.
    return _COMMENTS.sub("", text)


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def column_key(title: str) -> str:
    plain = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", plain.lower()).strip("_")


def form_fields(content: str | bytes) -> dict[str, str]:
    page = parse_html(_html(content), url=CALLAO_FORM_URL)
    fields = {
        str(item.attrib.get("name")): str(item.attrib.get("value", ""))
        for item in page.css("form#formBuscar input[type=hidden]")
        if item.attrib.get("name")
    }
    if "_token" not in fields or "captcha_key" not in fields:
        raise CallaoParseError("El formulario del Callao no trae _token o captcha_key.")
    return fields


def captcha_image(content: str | bytes) -> bytes:
    page = parse_html(_html(content), url=CALLAO_FORM_URL)
    for img in page.css("img"):
        src = str(img.attrib.get("src", ""))
        if img.attrib.get("alt") == "captcha" and src.startswith("data:image"):
            try:
                return base64.b64decode(src.split(",", 1)[1], validate=True)
            except (IndexError, binascii.Error) as exc:
                raise CallaoParseError("La imagen del captcha del Callao no es valida.") from exc
    raise CallaoParseError("El formulario del Callao no trae la imagen del captcha.")


def _portal_error(url: str) -> str | None:
    values = parse_qs(urlparse(url).query).get("error")
    return _clean(values[0]) if values else None


def parse_papeletas(content: str | bytes, plate: str, url: str = "") -> dict[str, object]:
    plate = normalize_plate(plate)
    error = _portal_error(url)
    if error:
        if _CAPTCHA_ERROR.search(error):
            raise CallaoCaptchaRejected(error)
        raise CallaoParseError(f"El Callao respondio: {error[:200]}")

    html = _html(content)
    page = parse_html(html, url=CALLAO_SEARCH_URL)
    tables = page.css("table#dataTable")
    if tables:
        table = tables[0]
        keys = [column_key(_clean(th.get_all_text())) for th in table.css("thead th")]
        if "placa" not in keys:
            raise CallaoParseError("La tabla del Callao no tiene la columna Placa.")
        papeletas = []
        for tr in table.css("tbody tr"):
            cells = [_clean(td.get_all_text()) for td in tr.css("td")]
            if len(cells) != len(keys):
                raise CallaoParseError("Fila del Callao con un numero de columnas inesperado.")
            campos = {
                key: value
                for key, value in zip(keys, cells, strict=True)
                if key and value and not _PERSONAL.search(key)
            }
            if normalize_plate(campos.get("placa", "")) != plate:
                raise CallaoParseError("La tabla del Callao corresponde a otra placa.")
            papeletas.append(campos)
        if papeletas:
            return {"tiene_papeletas": True, "papeletas": papeletas, "mensaje": None}

    for alert in page.css("p.alert"):
        text = _clean(alert.get_all_text())
        if _NO_RESULTS.search(text):
            return {"tiene_papeletas": False, "papeletas": [], "mensaje": text}
    raise CallaoParseError("La pagina del Callao no tiene ni resultados ni el aviso de sin resultados.")


def callao_result(
    plate: str, status: QueryStatus, message: str, data: dict | None = None
) -> QueryResult:
    return QueryResult(Source.CALLAO, plate, status, CALLAO_INFO.url, message, data or {})


def result_from_html(plate: str, content: str | bytes, url: str = "") -> QueryResult:
    """``CallaoCaptchaRejected`` se propaga: el conector reintenta con otro codigo."""
    plate = normalize_plate(plate)
    try:
        data = parse_papeletas(content, plate, url)
    except CallaoCaptchaRejected:
        raise
    except CallaoParseError as exc:
        return callao_result(plate, QueryStatus.PARSE_ERROR, str(exc))
    if data["tiene_papeletas"]:
        return callao_result(plate, QueryStatus.SUCCESS, "Papeletas obtenidas del portal del Callao.", data)
    return callao_result(plate, QueryStatus.NOT_FOUND, "El Callao no registra papeletas para esta placa.", data)


class CallaoProvider:
    info = CALLAO_INFO

    def query(self, plate: str) -> QueryResult:
        return callao_result(
            normalize_plate(plate),
            QueryStatus.REQUIRES_INTERACTION,
            "El portal del Callao pide un codigo de seguridad. Usa --stealth (o /v1/queries/stealth): se lee con OCR local.",
        )
