"""Consulta desatendida de papeletas del Callao.

Como el SAT de Lima: sesion HTTP, GET del formulario (trae el captcha como PNG en
linea), lectura local del codigo con ddddocr y POST con la placa. Si el portal
rechaza el codigo, se pide un formulario nuevo, hasta ``MAX_ATTEMPTS`` veces. El
captcha se usa una sola vez y no se guarda.

Si ``OBD_DEBUG_DIR`` esta definido se guarda el HTML de la respuesta final, para
ajustar el parser cuando aparezca un caso con papeletas.
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
from obd_consultas.providers.callao import (
    CALLAO_FORM_URL,
    CALLAO_SEARCH_URL,
    SEARCH_BY_PLATE,
    CallaoCaptchaRejected,
    CallaoParseError,
    callao_result,
    captcha_image,
    form_fields,
    result_from_html,
)

DEBUG_ENV = "OBD_DEBUG_DIR"
MAX_ATTEMPTS = 5
REQUEST_TIMEOUT = 30
_CODE = re.compile(r"^[A-Za-z0-9]{3}$")


class CallaoOcrUnavailable(RuntimeError):
    """Falta la dependencia de OCR local."""


def _new_ocr() -> Any:
    try:
        import ddddocr
    except ImportError as exc:
        raise CallaoOcrUnavailable("Falta el OCR local. Ejecuta: uv sync") from exc
    return ddddocr.DdddOcr(show_ad=False)


def _captcha_code(image: bytes, ocr: Any) -> str | None:
    try:
        value = str(ocr.classification(image)).strip()
    except Exception:
        return None
    return value if _CODE.match(value) else None


def _body(response: Any) -> bytes:
    body = getattr(response, "body", b"")
    return body if isinstance(body, bytes) else str(body).encode()


def _save_debug(plate: str, html: bytes) -> Path | None:
    folder = os.environ.get(DEBUG_ENV, "").strip()
    if not folder:
        return None
    path = Path(folder) / f"callao-{plate}-{datetime.now(UTC):%Y%m%dT%H%M%S}.html"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(html)
    except OSError:
        return None
    return path


def query_callao_stealth(
    plate: str,
    timeout: int = 180,
    *,
    session_factory: Callable[..., Any] = http_session,
    ocr: Any = None,
    max_attempts: int = MAX_ATTEMPTS,
    **_options: Any,
) -> QueryResult:
    """Consulta el Callao sin ventana. Los flags de navegador no aplican (es HTTP)."""
    plate = normalize_plate(plate)
    validate_timeout(timeout)
    if not 1 <= max_attempts <= 10:
        raise ValueError("Los intentos deben estar entre 1 y 10.")

    if ocr is None:
        try:
            ocr = _new_ocr()
        except CallaoOcrUnavailable as exc:
            return callao_result(plate, QueryStatus.UNAVAILABLE, str(exc))

    deadline = monotonic() + timeout
    try:
        with session_factory() as session:
            for attempt in range(1, max_attempts + 1):
                if monotonic() >= deadline:
                    break
                # Cada GET trae un captcha y un captcha_key nuevos.
                page = session.get(CALLAO_FORM_URL, timeout=REQUEST_TIMEOUT)
                if getattr(page, "status", 0) != 200:
                    return callao_result(
                        plate, QueryStatus.UNAVAILABLE, "No se pudo cargar el formulario del Callao."
                    )
                html = _body(page)
                code = _captcha_code(captcha_image(html), ocr)
                if not code:
                    continue

                data = form_fields(html)
                data.update(tipo_busqueda=SEARCH_BY_PLATE, valor_busqueda=plate, captcha=code)
                response = session.post(CALLAO_SEARCH_URL, data=data, timeout=REQUEST_TIMEOUT)
                if getattr(response, "status", 0) != 200:
                    return callao_result(
                        plate,
                        QueryStatus.UNAVAILABLE,
                        f"El Callao respondio HTTP {getattr(response, 'status', 0)}.",
                    )
                body = _body(response)
                try:
                    result = result_from_html(plate, body, str(getattr(response, "url", "")))
                except CallaoCaptchaRejected:
                    continue
                saved = _save_debug(plate, body)
                if result.status == QueryStatus.PARSE_ERROR and saved is not None:
                    result = callao_result(
                        plate, QueryStatus.PARSE_ERROR, f"{result.message} Archivo: {saved.name}"
                    )
                return stamp_capture(result, "stealth_ocr", attempts=attempt)
    except ScraplingUnavailable as exc:
        return callao_result(plate, QueryStatus.UNAVAILABLE, str(exc))
    except CallaoParseError as exc:
        return callao_result(plate, QueryStatus.PARSE_ERROR, str(exc))
    except Exception as exc:
        return callao_result(
            plate,
            QueryStatus.UNAVAILABLE,
            f"No se pudo completar la sesion con el portal del Callao: {type(exc).__name__}.",
        )

    return callao_result(
        plate,
        QueryStatus.REQUIRES_INTERACTION,
        "El captcha del Callao no se pudo leer dentro del tiempo limite. Prueba de nuevo.",
    )
