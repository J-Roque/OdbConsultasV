"""Consulta desatendida de orden de captura del SAT de Lima.

Igual que MTC: sesion HTTP temporal, GET del formulario ASP.NET, lectura local
del captcha de imagen y POST con la placa. Si el portal rechaza el codigo se
pide un captcha nuevo, hasta ``MAX_ATTEMPTS`` veces. El captcha se usa una sola
vez y no se guarda.

Mientras el parser sea provisional, si ``OBD_DEBUG_DIR`` esta definido se guarda
el HTML de la respuesta final en esa carpeta para ajustar el parser. Esa carpeta
no debe versionarse (``artifacts/`` ya esta en ``.gitignore``).
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import os
from pathlib import Path
import re
from time import monotonic
from typing import Any

from obd_consultas.domain.models import QueryResult, QueryStatus, normalize_plate
from obd_consultas.infrastructure.connector_common import stamp_capture, validate_timeout
from obd_consultas.infrastructure.scrapling_engine import ScraplingUnavailable, http_session
from obd_consultas.providers.sat import (
    CAPTCHA_FIELD,
    PLATE_FIELD,
    SAT_FORM_URL,
    SatCaptchaRejected,
    SatParseError,
    captcha_url,
    form_fields,
    result_from_html,
    sat_result,
)

DEBUG_ENV = "OBD_DEBUG_DIR"
MAX_ATTEMPTS = 5
REQUEST_TIMEOUT = 30
_CODE = re.compile(r"^[A-Za-z0-9]{4,6}$")


class SatOcrUnavailable(RuntimeError):
    """Falta la dependencia de OCR local."""


def _new_ocr() -> Any:
    try:
        import ddddocr
    except ImportError as exc:
        raise SatOcrUnavailable("Falta el OCR local. Ejecuta: uv sync") from exc
    return ddddocr.DdddOcr(show_ad=False)


def _captcha_code(image: bytes, ocr: Any) -> str | None:
    """Codigo leido solo si tiene de 4 a 6 letras o numeros."""
    try:
        value = str(ocr.classification(image)).strip()
    except Exception:
        return None
    return value.upper() if _CODE.match(value) else None


def _body(response: Any) -> bytes:
    body = getattr(response, "body", b"")
    return body if isinstance(body, bytes) else str(body).encode()


def _save_debug(plate: str, html: bytes) -> Path | None:
    folder = os.environ.get(DEBUG_ENV, "").strip()
    if not folder:
        return None
    path = Path(folder) / f"sat-{plate}-{datetime.now(UTC):%Y%m%dT%H%M%S}.html"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(html)
    except OSError:
        return None
    return path


def query_sat_stealth(
    plate: str,
    timeout: int = 180,
    *,
    session_factory: Callable[..., Any] = http_session,
    ocr: Any = None,
    max_attempts: int = MAX_ATTEMPTS,
    **_options: Any,
) -> QueryResult:
    """Consulta el SAT de Lima sin ventana visible.

    Los flags de navegador se aceptan para compartir la CLI, pero no aplican:
    el SAT se consulta por HTTP.
    """
    plate = normalize_plate(plate)
    validate_timeout(timeout)
    if not 1 <= max_attempts <= 10:
        raise ValueError("Los intentos deben estar entre 1 y 10.")

    if ocr is None:
        try:
            ocr = _new_ocr()
        except SatOcrUnavailable as exc:
            return sat_result(plate, QueryStatus.UNAVAILABLE, str(exc))

    deadline = monotonic() + timeout
    try:
        with session_factory() as session:
            page = session.get(SAT_FORM_URL, timeout=REQUEST_TIMEOUT)
            if getattr(page, "status", 0) != 200:
                return sat_result(
                    plate, QueryStatus.UNAVAILABLE, "No se pudo cargar el formulario del SAT."
                )
            html = _body(page)

            for attempt in range(1, max_attempts + 1):
                if monotonic() >= deadline:
                    break
                image = session.get(captcha_url(html), timeout=REQUEST_TIMEOUT)
                code = _captcha_code(_body(image), ocr)
                if not code:
                    # Recargar el formulario trae otro captcha y otro __VIEWSTATE.
                    html = _body(session.get(SAT_FORM_URL, timeout=REQUEST_TIMEOUT))
                    continue

                data = form_fields(html)
                data[PLATE_FIELD] = plate
                data[CAPTCHA_FIELD] = code
                response = session.post(SAT_FORM_URL, data=data, timeout=REQUEST_TIMEOUT)
                html = _body(response)
                if getattr(response, "status", 0) != 200:
                    return sat_result(
                        plate,
                        QueryStatus.UNAVAILABLE,
                        f"El SAT respondio HTTP {getattr(response, 'status', 0)}.",
                    )
                try:
                    result = result_from_html(plate, html)
                except SatCaptchaRejected:
                    continue
                saved = _save_debug(plate, html)
                if result.status == QueryStatus.PARSE_ERROR and saved is not None:
                    result = sat_result(
                        plate, QueryStatus.PARSE_ERROR, f"{result.message} Archivo: {saved.name}"
                    )
                if result.status in {QueryStatus.SUCCESS, QueryStatus.NOT_FOUND}:
                    return stamp_capture(result, "stealth_ocr", attempts=attempt)
                return result
    except ScraplingUnavailable as exc:
        return sat_result(plate, QueryStatus.UNAVAILABLE, str(exc))
    except SatParseError as exc:
        return sat_result(plate, QueryStatus.PARSE_ERROR, str(exc))
    except Exception as exc:
        return sat_result(
            plate,
            QueryStatus.UNAVAILABLE,
            f"No se pudo completar la sesion con el SAT: {type(exc).__name__}.",
        )

    return sat_result(
        plate,
        QueryStatus.REQUIRES_INTERACTION,
        "El captcha del SAT no se pudo leer dentro del tiempo limite. Prueba de nuevo.",
    )
