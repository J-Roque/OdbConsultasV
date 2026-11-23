"""Intento desatendido de SOAT con el navegador sigiloso de Scrapling.

El portal APESEG usa Cloudflare Turnstile. En vez de extraer o falsificar el
token, se conduce el formulario real del portal dentro de un navegador con
huella de Chrome; Scrapling resuelve el reto de Cloudflare y el propio widget
genera el token de la consulta. Si el portal exige intervencion, se devuelve
``requires_interaction`` y no se inventa un resultado.
"""
from __future__ import annotations

from datetime import datetime, timezone
from time import monotonic
from typing import Any, Callable

from obd_consultas.domain.models import QueryResult, QueryStatus, normalize_plate
from obd_consultas.infrastructure.scrapling_engine import (
    ScraplingUnavailable,
    stealth_session,
)
from obd_consultas.infrastructure.soat_browser import capture_result, is_query_response
from obd_consultas.providers.soat import SOAT_INFO, result_from_response, soat_result
from obd_consultas.providers.soat_dom import result_from_dom_capture

NOT_FOUND_TEXT = "No encontramos certificados SOAT"
BROWSER_TIMEOUT_MS = 45_000


def _is_timeout(error: BaseException) -> bool:
    return error.__class__.__name__ == "TimeoutError"


def _safe_json(response: Any) -> Any:
    try:
        return response.json()
    except Exception:
        return None


def _observe(page: Any, plate: str, timeout_ms: int, holder: dict[str, Any]) -> None:
    """Completa el formulario y espera la API o el resultado visible.

    Se registra el observador de respuestas antes de pulsar Consultar para no
    perder la respuesta JSON. El bucle acepta cualquiera de las dos vias porque
    el portal puede cambiar de comportamiento sin cambiar sus selectores.
    """

    def on_response(response: Any) -> None:
        if is_query_response(str(getattr(response, "url", "")), plate):
            holder["status"] = getattr(response, "status", None)
            holder["payload"] = _safe_json(response)

    page.on("response", on_response)
    page.locator(".soat-placa__input").fill(plate, timeout=20_000)
    page.get_by_role("button", name="Consultar", exact=True).click(timeout=15_000)

    deadline = monotonic() + (timeout_ms / 1000)
    while monotonic() < deadline:
        if "status" in holder or "payload" in holder:
            return
        if page.locator(".soat-resultado").count():
            holder["dom"] = capture_result(page)
            return
        notice = page.locator(".soat-aviso")
        if notice.count():
            holder["notice"] = notice.first.inner_text()
            return
        page.wait_for_timeout(500)


def _result_from_holder(plate: str, holder: dict[str, Any]) -> QueryResult:
    """Traduce lo observado a un estado del contrato, sin adivinar datos."""
    if "status" in holder:
        try:
            status = int(holder["status"])
        except (TypeError, ValueError):
            status = 0
        result = result_from_response(plate, status, holder.get("payload"))
        if result.status in {QueryStatus.SUCCESS, QueryStatus.NOT_FOUND}:
            result.data.setdefault(
                "capture",
                {
                    "method": "stealth_api",
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        return result
    if "dom" in holder:
        return result_from_dom_capture(holder["dom"], plate)
    if "notice" in holder:
        notice = " ".join(str(holder["notice"]).split())
        if NOT_FOUND_TEXT in notice and plate in notice:
            return soat_result(
                plate,
                QueryStatus.NOT_FOUND,
                "La fuente no encontro certificados para esta placa.",
                {"encontrado": False, "vigente": False, "soat_vigente": None, "certificados": []},
            )
        return soat_result(
            plate,
            QueryStatus.UNAVAILABLE,
            "El portal mostro un aviso sin datos del vehiculo.",
        )
    error = holder.get("error")
    if error is not None and _is_timeout(error):
        return soat_result(
            plate,
            QueryStatus.REQUIRES_INTERACTION,
            "No se recibio el resultado a tiempo. La verificacion puede seguir pendiente.",
        )
    if error is not None:
        return soat_result(
            plate,
            QueryStatus.UNAVAILABLE,
            "El navegador no pudo completar el formulario del portal.",
        )
    return soat_result(
        plate,
        QueryStatus.REQUIRES_INTERACTION,
        "El portal no entrego el resultado. Puede requerir verificacion manual.",
    )


def query_soat_stealth(
    plate: str,
    timeout: int = 180,
    *,
    headless: bool = True,
    real_chrome: bool = False,
    solve_cloudflare: bool = True,
    profile: str | None = None,
    proxy: str | None = None,
    session_factory: Callable[..., Any] = stealth_session,
) -> QueryResult:
    """Consulta SOAT sin ventana visible, salvo que ``headless=False``.

    No escribe cookies ni respuestas en disco. ``profile`` es opcional y solo
    reutiliza un perfil de navegador si el usuario lo pide expresamente.
    """
    plate = normalize_plate(plate)
    if not 10 <= timeout <= 600:
        raise ValueError("El tiempo de espera debe estar entre 10 y 600 segundos.")

    timeout_ms = timeout * 1000
    browser_timeout = min(max(timeout_ms, BROWSER_TIMEOUT_MS), 120_000)
    holder: dict[str, Any] = {}

    def page_action(page: Any) -> None:
        try:
            _observe(page, plate, timeout_ms, holder)
        except Exception as exc:  # Scrapling silencia esta excepcion
            holder["error"] = exc

    options = {
        "headless": headless,
        "real_chrome": real_chrome,
        "solve_cloudflare": solve_cloudflare,
        "timeout": browser_timeout,
        "retries": 1,
        "profile": profile,
        "proxy": proxy,
    }

    try:
        with session_factory(**options) as session:
            session.fetch(
                SOAT_INFO.url,
                page_action=page_action,
                timeout=browser_timeout,
                wait=(2_000 if solve_cloudflare else 0),
            )
    except ScraplingUnavailable as exc:
        return soat_result(plate, QueryStatus.UNAVAILABLE, str(exc))
    except Exception as exc:
        message = str(exc).lower()
        if "executable" in message and "exist" in message:
            return soat_result(
                plate,
                QueryStatus.UNAVAILABLE,
                "Falta el navegador sigiloso. Ejecuta: obd-consultas install-browsers",
            )
        if "cloudflare" in message:
            return soat_result(
                plate,
                QueryStatus.REQUIRES_INTERACTION,
                "Cloudflare no se pudo resolver automaticamente. Puede requerir intervencion.",
            )
        return soat_result(
            plate,
            QueryStatus.UNAVAILABLE,
            "No se pudo completar la sesion sigilosa. Comprueba el navegador y la conexion.",
        )

    return _result_from_holder(plate, holder)
