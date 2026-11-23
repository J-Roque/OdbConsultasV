"""Piezas compartidas por los conectores stealth y asistidos.

Cada conector conserva lo propio de su portal (selectores, como observar la
respuesta, como interpretar avisos). Aqui vive lo que era identico en todos:
validar el timeout, leer JSON sin romper, sellar el metodo de captura y traducir
errores de sesion o de navegador a estados del contrato.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from obd_consultas.domain.models import QueryResult, QueryStatus

MIN_TIMEOUT = 10
MAX_TIMEOUT = 600
FINAL_STATUSES = frozenset({QueryStatus.SUCCESS, QueryStatus.NOT_FOUND})

MISSING_BROWSER = "Falta el navegador sigiloso. Ejecuta: obd-consultas install-browsers"
CLOUDFLARE_FAILED = "Cloudflare no se pudo resolver automaticamente. Puede requerir intervencion."
SESSION_FAILED = "No se pudo completar la sesion sigilosa. Comprueba el navegador y la conexion."
RESULT_TIMEOUT = "No se recibio el resultado a tiempo. La verificacion puede seguir pendiente."
FORM_FAILED = "El navegador no pudo completar el formulario del portal."
NO_RESULT = "El portal no entrego el resultado. Puede requerir verificacion manual."


class ResultFactory(Protocol):
    """Construye un ``QueryResult`` de una fuente concreta (``soat_result``, ...)."""

    def __call__(
        self, plate: str, status: QueryStatus, message: str, data: dict[str, Any] | None = None
    ) -> QueryResult: ...


ResponseParser = Callable[[str, int, object], QueryResult]


def validate_timeout(timeout: int) -> None:
    if not MIN_TIMEOUT <= timeout <= MAX_TIMEOUT:
        raise ValueError(
            f"El tiempo de espera debe estar entre {MIN_TIMEOUT} y {MAX_TIMEOUT} segundos."
        )


def is_timeout(error: BaseException | None) -> bool:
    # Playwright, Patchright y Scrapling tienen cada uno su TimeoutError.
    return error is not None and error.__class__.__name__ == "TimeoutError"


def safe_json(response: Any) -> Any:
    try:
        return response.json()
    except Exception:
        return None


def http_status(value: object) -> int:
    try:
        return int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return 0


def stamp_capture(result: QueryResult, method: str, **extra: object) -> QueryResult:
    """Anota como se obtuvo un resultado final; no pisa una anotacion previa."""
    if result.status in FINAL_STATUSES:
        result.data.setdefault(
            "capture",
            {"method": method, **extra, "captured_at": datetime.now(UTC).isoformat()},
        )
    return result


def result_from_api(
    holder: dict[str, Any], plate: str, parse: ResponseParser, method: str = "stealth_api"
) -> QueryResult:
    """Interpreta la respuesta JSON capturada en ``holder['status'/'payload']``."""
    result = parse(plate, http_status(holder.get("status")), holder.get("payload"))
    return stamp_capture(result, method)


def result_from_error(
    plate: str,
    holder: dict[str, Any],
    make: ResultFactory,
    *,
    timeout_message: str = RESULT_TIMEOUT,
    failure_message: str = FORM_FAILED,
    empty_message: str = NO_RESULT,
) -> QueryResult:
    """Cierre comun cuando no se observo ningun dato: nunca inventa un exito."""
    error = holder.get("error")
    if is_timeout(error):
        return make(plate, QueryStatus.REQUIRES_INTERACTION, timeout_message)
    if error is not None:
        return make(plate, QueryStatus.UNAVAILABLE, failure_message)
    return make(plate, QueryStatus.REQUIRES_INTERACTION, empty_message)


def session_failure(
    plate: str,
    exc: Exception,
    make: ResultFactory,
    *,
    challenge_words: tuple[str, ...] = ("cloudflare",),
    challenge_message: str = CLOUDFLARE_FAILED,
    failure_message: str = SESSION_FAILED,
) -> QueryResult:
    """Traduce un fallo al abrir o conducir la sesion del navegador."""
    from obd_consultas.infrastructure.scrapling_engine import ScraplingUnavailable

    if isinstance(exc, ScraplingUnavailable):
        return make(plate, QueryStatus.UNAVAILABLE, str(exc))
    message = str(exc).lower()
    if "executable" in message and "exist" in message:
        return make(plate, QueryStatus.UNAVAILABLE, MISSING_BROWSER)
    if any(word in message for word in challenge_words):
        return make(plate, QueryStatus.REQUIRES_INTERACTION, challenge_message)
    return make(plate, QueryStatus.UNAVAILABLE, failure_message)


def stealth_options(
    *,
    headless: bool,
    real_chrome: bool,
    solve_cloudflare: bool,
    timeout_ms: int,
    profile: str | None,
    proxy: str | None,
) -> dict[str, Any]:
    return {
        "headless": headless,
        "real_chrome": real_chrome,
        "solve_cloudflare": solve_cloudflare,
        "timeout": timeout_ms,
        "retries": 1,
        "profile": profile,
        "proxy": proxy,
    }


def guarded(action: Callable[[Any], None], holder: dict[str, Any]) -> Callable[[Any], None]:
    """Envuelve el ``page_action``: Scrapling silencia sus excepciones."""

    def run(page: Any) -> None:
        try:
            action(page)
        except Exception as exc:
            holder["error"] = exc

    return run
