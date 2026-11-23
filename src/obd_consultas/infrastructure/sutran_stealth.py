"""Consulta desatendida de infracciones publicas de SUTRAN."""
from __future__ import annotations

from collections.abc import Callable
import sys
from typing import Any

from obd_consultas.domain.models import QueryResult, QueryStatus, normalize_plate
from obd_consultas.infrastructure.connector_common import (
    guarded,
    result_from_api,
    result_from_error,
    safe_json,
    session_failure,
    stealth_options,
    validate_timeout,
)
from obd_consultas.infrastructure.scrapling_engine import stealth_session
from obd_consultas.providers.sutran import (
    SUTRAN_API_HOST,
    SUTRAN_FORM_URL,
    result_from_response,
    sutran_result,
)

TOKEN_WAIT_MS = 45_000
TOKEN_SCRIPT = "document.querySelector('input[name=cf-turnstile-response]')?.value || ''"  # noqa: S105 - JS que lee el widget


def _observe(page: Any, plate: str, timeout_ms: int, headless: bool, holder: dict[str, Any]) -> None:
    def on_response(response: Any) -> None:
        url = str(getattr(response, "url", ""))
        if SUTRAN_API_HOST not in url or "/consultas/placa/" not in url:
            return
        holder["status"] = getattr(response, "status", None)
        holder["payload"] = safe_json(response)

    page.on("response", on_response)
    page.wait_for_selector('input[name="placa"]', timeout=30_000)
    page.locator('input[name="placa"]').fill(plate, timeout=20_000)

    # El portal exige el token de Turnstile en la cabecera X-Captcha-Token.
    # Si el widget no lo entrega, no tiene sentido enviar el formulario:
    # la API responderia 403 CAPTCHA_INVALID.
    token_wait = min(timeout_ms, TOKEN_WAIT_MS)
    elapsed = 0
    while elapsed < token_wait:
        if page.evaluate(TOKEN_SCRIPT):
            break
        page.wait_for_timeout(500)
        elapsed += 500
    else:
        holder["captcha"] = "sin token"
        return

    if not headless:
        print(
            "Resuelve Turnstile si aparece y pulsa Consultar en el navegador.",
            file=sys.stderr,
            flush=True,
        )
    page.get_by_role("button", name="Consultar", exact=True).click(timeout=15_000)

    elapsed = 0
    while elapsed < timeout_ms:
        if "status" in holder:
            return
        page.wait_for_timeout(500)
        elapsed += 500


def _result_from_holder(plate: str, holder: dict[str, Any]) -> QueryResult:
    if "captcha" in holder:
        return sutran_result(
            plate,
            QueryStatus.REQUIRES_INTERACTION,
            "SUTRAN no entrego el token de Turnstile. El portal permite consultar por placa, pero exige verificacion del navegador.",
        )
    if "status" in holder:
        return result_from_api(holder, plate, result_from_response)
    # Sin respuesta: un error del navegador es "no disponible"; si no hubo error,
    # el portal simplemente no contesto (un timeout tambien cae aqui).
    holder = {"error": RuntimeError()} if holder.get("error") is not None else {}
    return result_from_error(
        plate,
        holder,
        sutran_result,
        failure_message="El navegador no pudo completar el formulario de SUTRAN.",
        empty_message="SUTRAN no entrego el resultado. Puede requerir verificacion manual.",
    )


def query_sutran_stealth(
    plate: str,
    timeout: int = 180,
    *,
    headless: bool = True,
    real_chrome: bool = False,
    profile: str | None = None,
    proxy: str | None = None,
    session_factory: Callable[..., Any] = stealth_session,
) -> QueryResult:
    plate = normalize_plate(plate)
    validate_timeout(timeout)
    timeout_ms = timeout * 1000
    browser_timeout = min(max(timeout_ms, 60_000), 120_000)
    holder: dict[str, Any] = {}
    options = stealth_options(
        headless=headless,
        real_chrome=real_chrome,
        # El solver de Cloudflare de Scrapling falla aqui: intenta hacer clic en
        # un checkbox de un iframe que se destruye y aborta la pagina.
        solve_cloudflare=False,
        timeout_ms=browser_timeout,
        profile=profile,
        proxy=proxy,
    )
    try:
        with session_factory(**options) as session:
            session.fetch(
                SUTRAN_FORM_URL,
                page_action=guarded(
                    lambda page: _observe(page, plate, timeout_ms, headless, holder), holder
                ),
                timeout=browser_timeout,
                wait=2_000,
            )
    except Exception as exc:
        return session_failure(
            plate,
            exc,
            sutran_result,
            challenge_words=("cloudflare", "turnstile"),
            challenge_message="SUTRAN exige resolver la verificacion Turnstile.",
            failure_message="No se pudo completar la sesion con el portal SUTRAN.",
        )
    return _result_from_holder(plate, holder)
