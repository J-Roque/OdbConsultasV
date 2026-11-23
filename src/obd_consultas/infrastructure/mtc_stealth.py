"""Consulta desatendida del MTC con OCR local del captcha de imagen.

El portal MTC protege el formulario con un captcha numerico de seis digitos.
Este modulo conduce el formulario oficial con una sesion HTTP, lee el captcha con
OCR local y reintenta con una imagen nueva si el portal lo rechaza. No extrae ni
reutiliza cookies de otro usuario: cada consulta crea una sesion temporal y
obtiene su propio captcha.

El OCR puede fallar. Si despues de varios intentos no se obtiene una respuesta
valida, se devuelve ``requires_interaction`` y se ofrece el modo asistido. El
captcha se usa una sola vez y no se guarda.
"""
from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone
from time import monotonic
from typing import Any, Callable

from obd_consultas.domain.models import QueryResult, QueryStatus, normalize_plate
from obd_consultas.infrastructure.scrapling_engine import ScraplingUnavailable, http_session
from obd_consultas.providers.mtc import MTC_FORM_URL, mtc_result, result_from_response

MTC_BASE = "https://rec.mtc.gob.pe"
CAPTCHA_URL = f"{MTC_BASE}/CITV/refrescarCaptcha"
QUERY_URL = f"{MTC_BASE}/CITV/JrCITVConsultarFiltro"
HEADERS = {"Content-Type": "application/json"}
MAX_ATTEMPTS = 5
REQUEST_TIMEOUT = 30


class MtcOcrUnavailable(RuntimeError):
    """Falta la dependencia de OCR local."""


def _new_ocr() -> Any:
    try:
        import ddddocr
    except ImportError as exc:
        raise MtcOcrUnavailable(
            "Falta el OCR local. Ejecuta: uv sync"
        ) from exc
    return ddddocr.DdddOcr(show_ad=False)


def _captcha_code(image: bytes, ocr: Any) -> str | None:
    """Devuelve el codigo solo si el OCR entrego seis digitos."""
    try:
        value = str(ocr.classification(image)).strip()
    except Exception:
        return None
    return value if len(value) == 6 and value.isdigit() else None


def _decode_captcha(payload: object) -> bytes:
    if not isinstance(payload, dict) or payload.get("orStatus") is not True:
        raise ValueError("El portal no entrego el captcha.")
    value = payload.get("orResult")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("La imagen del captcha vino vacia.")
    try:
        return base64.b64decode("".join(value.split()), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("La imagen del captcha no es base64 valido.") from exc


def _add_capture(result: QueryResult, attempts: int) -> QueryResult:
    result.data.setdefault(
        "capture",
        {
            "method": "stealth_ocr",
            "attempts": attempts,
            "captured_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return result


def query_mtc_stealth(
    plate: str,
    timeout: int = 180,
    *,
    session_factory: Callable[..., Any] = http_session,
    ocr: Any = None,
    max_attempts: int = MAX_ATTEMPTS,
    **_options: Any,
) -> QueryResult:
    """Consulta MTC sin ventana visible ni intervencion humana.

    Los flags de navegador (`headless`, `real_chrome`, etc.) se aceptan para
    compartir la CLI con los demos conectores, pero no aplican: MTC usa HTTP.
    """
    plate = normalize_plate(plate)
    if not 10 <= timeout <= 600:
        raise ValueError("El tiempo de espera debe estar entre 10 y 600 segundos.")
    if not 1 <= max_attempts <= 10:
        raise ValueError("Los intentos deben estar entre 1 y 10.")

    if ocr is None:
        try:
            ocr = _new_ocr()
        except MtcOcrUnavailable as exc:
            return mtc_result(plate, QueryStatus.UNAVAILABLE, str(exc))

    deadline = monotonic() + timeout
    last_status: QueryStatus | None = None

    try:
        with session_factory() as session:
            form = session.get(MTC_FORM_URL, timeout=REQUEST_TIMEOUT)
            if getattr(form, "status", 0) != 200:
                return mtc_result(
                    plate, QueryStatus.UNAVAILABLE, "No se pudo cargar el formulario oficial."
                )

            for attempt in range(1, max_attempts + 1):
                if monotonic() >= deadline:
                    break
                captcha = session.get(CAPTCHA_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
                image = _decode_captcha(captcha.json())
                code = _captcha_code(image, ocr)
                if not code:
                    last_status = QueryStatus.REQUIRES_INTERACTION
                    continue

                response = session.get(
                    QUERY_URL,
                    params={"pArrParametros": f"1|{plate}||{code}"},
                    headers=HEADERS,
                    timeout=REQUEST_TIMEOUT,
                )
                payload = response.json()
                result = result_from_response(plate, getattr(response, "status", 0), payload)
                if result.status in {QueryStatus.SUCCESS, QueryStatus.NOT_FOUND}:
                    return _add_capture(result, attempt)
                if result.status == QueryStatus.REQUIRES_INTERACTION and payload.get("orCodigo") == "-1":
                    last_status = QueryStatus.REQUIRES_INTERACTION
                    continue
                return result
    except ScraplingUnavailable as exc:
        return mtc_result(plate, QueryStatus.UNAVAILABLE, str(exc))
    except (ValueError, KeyError, TypeError) as exc:
        return mtc_result(
            plate,
            QueryStatus.UNAVAILABLE,
            f"No se pudo interpretar la respuesta del portal: {type(exc).__name__}.",
        )
    except Exception as exc:
        message = str(exc).lower()
        if "cloudflare" in message:
            return mtc_result(
                plate,
                QueryStatus.REQUIRES_INTERACTION,
                "Cloudflare no se pudo resolver automaticamente.",
            )
        return mtc_result(
            plate,
            QueryStatus.UNAVAILABLE,
            "No se pudo completar la sesion con el portal MTC.",
        )

    return mtc_result(
        plate,
        last_status or QueryStatus.REQUIRES_INTERACTION,
        "El captcha no se pudo resolver dentro del tiempo limite. Prueba de nuevo o usa --interactive.",
    )
