"""Consulta desatendida de infracciones publicas de SUTRAN."""
from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
import sys
from time import monotonic
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

# El sitio (Angular) pide el token de Turnstile recien al pulsar Consultar: crea
# el widget oficial con appearance "interaction-only", espera su callback hasta
# 120 s y lo envia en X-Captcha-Token. El conector no lee ni fabrica el token:
# solo pulsa Consultar y observa la respuesta de la API.
SITE_TOKEN_WAIT_MS = 120_000
# Sin ventana nadie puede marcar la casilla: si en este tiempo no hay respuesta,
# conviene una sesion nueva en vez de esperar los 120 s del sitio.
HEADLESS_WAIT_MS = 50_000
MAX_SESSIONS = 3
MIN_ATTEMPT_MS = 40_000
# Detecta si Cloudflare mostro la casilla de verificacion (Turnstile visible).
# Solo mira si el iframe oficial ocupa espacio; no lo toca ni lee el token.
CHALLENGE_VISIBLE = """() => [...document.querySelectorAll('iframe')].some(f =>
  (f.src || '').includes('challenges.cloudflare.com') && f.offsetWidth > 0 && f.offsetHeight > 0)"""


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
    if not headless:
        print(
            "Si aparece la verificacion de Cloudflare en el navegador, resuelvela.",
            file=sys.stderr,
            flush=True,
        )
    page.get_by_role("button", name="Consultar", exact=True).click(timeout=15_000)

    # Con ventana se espera lo que espera el sitio (la persona puede marcar la
    # casilla); sin ventana se corta antes y, si la casilla aparece, de inmediato.
    limit = SITE_TOKEN_WAIT_MS + 15_000 if not headless else HEADLESS_WAIT_MS
    wait_ms = min(timeout_ms, limit)
    elapsed = 0
    while elapsed < wait_ms:
        if "status" in holder:
            return
        if elapsed % 2_000 == 0 and not holder.get("challenge"):
            with suppress(Exception):  # la pagina puede estar navegando
                holder["challenge"] = bool(page.evaluate(CHALLENGE_VISIBLE))
            if holder.get("challenge") and headless:
                break
        page.wait_for_timeout(500)
        elapsed += 500
    holder["captcha"] = "sin respuesta"


def _result_from_holder(plate: str, holder: dict[str, Any]) -> QueryResult:
    if "captcha" in holder:
        if holder.get("challenge"):
            message = (
                "Cloudflare pidio verificacion manual en SUTRAN (casilla de Turnstile). "
                "Suele pasar tras varias consultas seguidas: espera unos minutos o usa "
                "--show-browser y marca la casilla."
            )
        else:
            message = (
                "SUTRAN no respondio a tiempo: el sitio no obtuvo su token de Turnstile. "
                "Prueba de nuevo en unos minutos o con --show-browser."
            )
        return sutran_result(plate, QueryStatus.REQUIRES_INTERACTION, message)
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
    deadline = monotonic() + timeout
    attempts = MAX_SESSIONS if headless else 1
    result: QueryResult | None = None
    for attempt in range(1, attempts + 1):
        remaining_ms = int((deadline - monotonic()) * 1000)
        if attempt > 1 and remaining_ms < MIN_ATTEMPT_MS:
            break
        result = _attempt(
            plate, remaining_ms, headless, real_chrome, profile, proxy, session_factory
        )
        # Solo se reintenta cuando el sitio no obtuvo su token: es lo unico que una
        # sesion nueva puede cambiar.
        if result.status != QueryStatus.REQUIRES_INTERACTION:
            break
    assert result is not None
    return result


def _attempt(
    plate: str,
    timeout_ms: int,
    headless: bool,
    real_chrome: bool,
    profile: str | None,
    proxy: str | None,
    session_factory: Callable[..., Any],
) -> QueryResult:
    browser_timeout = min(max(timeout_ms, 60_000), 180_000)
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
