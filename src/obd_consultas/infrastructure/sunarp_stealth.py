"""Intento desatendido de SUNARP con el navegador sigiloso de Scrapling.

El portal es una aplicacion Angular protegida por Turnstile. En vez de extraer
o falsificar el token, se completa el formulario oficial dentro de un navegador
con huella de Chrome; el propio widget genera el token. La respuesta oficial es
una imagen PNG de la tarjeta TIVE, no una ficha JSON con los datos del vehiculo.
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
from obd_consultas.infrastructure.sunarp_ocr import attach_tive_ocr
from obd_consultas.providers.sunarp import (
    SUNARP_FORM_URL,
    result_from_dom_capture,
    result_from_response,
    sunarp_result,
)

BROWSER_TIMEOUT_MS = 60_000
CAPTCHA_TEXT = "captcha no resuelto"

CAPTURE_SCRIPT = r"""() => {
  const image = document.querySelector('.container-data-vehiculo img');
  const alert = document.querySelector('.msg-alerta-robo');
  const rows = Array.from(document.querySelectorAll('nz-table tbody tr')).map((row) =>
    Array.from(row.querySelectorAll('td')).map((cell) => cell.textContent.trim())
  );
  return {
    format: 'sunarp-dom-v1',
    source_url: location.href,
    image: image ? image.getAttribute('src') : '',
    alert: alert ? alert.textContent.trim() : '',
    rows: rows
  };
}"""


def _is_timeout(error: BaseException) -> bool:
    return error.__class__.__name__ == "TimeoutError"


def _safe_json(response: Any) -> Any:
    try:
        return response.json()
    except Exception:
        return None


def _capture_dom(page: Any) -> Any:
    return page.evaluate(CAPTURE_SCRIPT)


def _observe(page: Any, plate: str, timeout_ms: int, holder: dict[str, Any]) -> None:
    """Completa el formulario y espera la API o la tarjeta visible."""

    def on_response(response: Any) -> None:
        if "getDatosVehiculo" in str(getattr(response, "url", "")):
            holder["status"] = getattr(response, "status", None)
            holder["payload"] = _safe_json(response)

    page.on("response", on_response)
    page.wait_for_selector("#nroPlaca", timeout=30_000)
    page.locator("#nroPlaca").fill(plate, timeout=20_000)
    # El widget Turnstile suele resolver el reto solo en el navegador sigiloso.
    # Turnstile puede tardar unos segundos en resolver el reto automaticamente.
    page.wait_for_timeout(6_000)

    button = page.get_by_role("button", name="Realizar Busqueda", exact=True)
    button.click(timeout=15_000)

    deadline = monotonic() + (timeout_ms / 1000)
    attempts = 0
    max_attempts = 3
    while monotonic() < deadline:
        if "status" in holder or "payload" in holder:
            return
        if page.locator(".container-data-vehiculo img").count():
            holder["dom"] = _capture_dom(page)
            return
        popup = page.locator(".swal2-popup")
        if popup.count():
            text = " ".join(str(popup.first.inner_text()).split())
            if CAPTCHA_TEXT in text.lower():
                holder["captcha"] = text
                # El aviso de SweetAlert bloquea el formulario: hay que cerrarlo.
                try:
                    page.locator(".swal2-confirm").click(timeout=2_000)
                except Exception:
                    pass
                if attempts < max_attempts:
                    attempts += 1
                    page.wait_for_timeout(6_000)
                    button.click(timeout=15_000)
                    continue
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
        if result.status == QueryStatus.SUCCESS:
            payload = holder.get("payload")
            model = payload.get("model") if isinstance(payload, dict) else None
            if isinstance(model, dict) and isinstance(model.get("imagen"), str):
                result = attach_tive_ocr(result, model["imagen"])
        return result
    if "dom" in holder:
        result = result_from_dom_capture(holder["dom"], plate)
        capture = holder["dom"]
        if (
            result.status == QueryStatus.SUCCESS
            and isinstance(capture, dict)
            and isinstance(capture.get("image"), str)
            and capture["image"].startswith("data:image/png;base64,")
        ):
            result = attach_tive_ocr(result, capture["image"].split(",", 1)[1])
        return result
    if "captcha" in holder:
        return sunarp_result(
            plate,
            QueryStatus.REQUIRES_INTERACTION,
            "El portal exige resolver la verificacion Turnstile. Usa --show-browser o el navegador visible.",
        )
    error = holder.get("error")
    if error is not None and _is_timeout(error):
        return sunarp_result(
            plate,
            QueryStatus.REQUIRES_INTERACTION,
            "No se recibio el resultado a tiempo. La verificacion puede seguir pendiente.",
        )
    if error is not None:
        return sunarp_result(
            plate,
            QueryStatus.UNAVAILABLE,
            "El navegador no pudo completar el formulario del portal.",
        )
    return sunarp_result(
        plate,
        QueryStatus.REQUIRES_INTERACTION,
        "El portal no entrego el resultado. Puede requerir verificacion manual.",
    )


def query_sunarp_stealth(
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
    """Consulta SUNARP sin ventana visible, salvo que ``headless=False``.

    No escribe cookies ni respuestas en disco. ``profile`` es opcional y solo
    reutiliza un perfil de navegador si el usuario lo pide expresamente.
    """
    plate = normalize_plate(plate)
    if not 10 <= timeout <= 600:
        raise ValueError("El tiempo de espera debe estar entre 10 y 600 segundos.")

    timeout_ms = timeout * 1000
    # Turnstile no se resuelve siempre en el primer navegador. Con un timeout
    # normal se prueban varias sesiones nuevas antes de pedir intervencion.
    attempts = 3 if timeout >= 60 else 1
    per_attempt_ms = max(30_000, timeout_ms // attempts)
    browser_timeout = min(max(per_attempt_ms, BROWSER_TIMEOUT_MS), 120_000)

    options = {
        "headless": headless,
        "real_chrome": real_chrome,
        "solve_cloudflare": solve_cloudflare,
        "timeout": browser_timeout,
        "retries": 1,
        "profile": profile,
        "proxy": proxy,
    }

    for attempt in range(1, attempts + 1):
        holder: dict[str, Any] = {}

        def page_action(page: Any) -> None:
            try:
                _observe(page, plate, per_attempt_ms, holder)
            except Exception as exc:  # Scrapling silencia esta excepcion
                holder["error"] = exc

        try:
            with session_factory(**options) as session:
                session.fetch(
                    SUNARP_FORM_URL,
                    page_action=page_action,
                    timeout=browser_timeout,
                    wait=(2_000 if solve_cloudflare else 0),
                )
        except ScraplingUnavailable as exc:
            return sunarp_result(plate, QueryStatus.UNAVAILABLE, str(exc))
        except Exception as exc:
            message = str(exc).lower()
            if "executable" in message and "exist" in message:
                return sunarp_result(
                    plate,
                    QueryStatus.UNAVAILABLE,
                    "Falta el navegador sigiloso. Ejecuta: obd-consultas install-browsers",
                )
            if "cloudflare" in message:
                return sunarp_result(
                    plate,
                    QueryStatus.REQUIRES_INTERACTION,
                    "Cloudflare no se pudo resolver automaticamente. Puede requerir intervencion.",
                )
            return sunarp_result(
                plate,
                QueryStatus.UNAVAILABLE,
                "No se pudo completar la sesion sigilosa. Comprueba el navegador y la conexion.",
            )

        result = _result_from_holder(plate, holder)
        if result.status != QueryStatus.REQUIRES_INTERACTION:
            return result
        # Un fallo de navegador no se arregla abriendo otra sesion.
        error = holder.get("error")
        if error is not None and not _is_timeout(error):
            return result

    return sunarp_result(
        plate,
        QueryStatus.REQUIRES_INTERACTION,
        "Turnstile no se resolvio en ningun intento. Prueba de nuevo o usa el navegador visible.",
    )
