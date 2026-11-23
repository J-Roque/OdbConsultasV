"""Consulta desatendida de infracciones publicas de SUTRAN."""
from __future__ import annotations

from datetime import datetime, timezone
import sys
from typing import Any, Callable

from obd_consultas.domain.models import QueryResult, QueryStatus, normalize_plate
from obd_consultas.infrastructure.scrapling_engine import (
    ScraplingUnavailable,
    stealth_session,
)
from obd_consultas.providers.sutran import (
    SUTRAN_API_HOST,
    SUTRAN_FORM_URL,
    result_from_response,
    sutran_result,
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
    if not 10 <= timeout <= 600:
        raise ValueError("El tiempo de espera debe estar entre 10 y 600 segundos.")
    holder: dict[str, Any] = {}

    def on_page(page: Any) -> None:
        try:
            def on_response(response: Any) -> None:
                url = str(getattr(response, "url", ""))
                if SUTRAN_API_HOST not in url or "/consultas/placa/" not in url:
                    return
                holder["status"] = getattr(response, "status", None)
                try:
                    holder["payload"] = response.json()
                except Exception:
                    holder["payload"] = None

            page.on("response", on_response)
            page.wait_for_selector('input[name="placa"]', timeout=30_000)
            page.locator('input[name="placa"]').fill(plate, timeout=20_000)

            # El portal exige el token de Turnstile en la cabecera X-Captcha-Token.
            # Si el widget no lo entrega, no tiene sentido enviar el formulario:
            # la API responderia 403 CAPTCHA_INVALID.
            token_wait = min(timeout * 1000, 45_000)
            elapsed = 0
            while elapsed < token_wait:
                token = page.evaluate(
                    "document.querySelector('input[name=cf-turnstile-response]')?.value || ''"
                )
                if token:
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

            deadline = timeout * 1000
            elapsed = 0
            while elapsed < deadline:
                if "status" in holder:
                    return
                page.wait_for_timeout(500)
                elapsed += 500
        except Exception as exc:
            holder["error"] = exc

    options = {
        "headless": headless,
        "real_chrome": real_chrome,
        "solve_cloudflare": headless,
        "timeout": min(max(timeout * 1000, 60_000), 120_000),
        "retries": 1,
        "profile": profile,
        "proxy": proxy,
    }
    try:
        with session_factory(**options) as session:
            session.fetch(
                SUTRAN_FORM_URL,
                page_action=on_page,
                timeout=min(max(timeout * 1000, 60_000), 120_000),
                wait=2_000,
            )
    except ScraplingUnavailable as exc:
        return sutran_result(plate, QueryStatus.UNAVAILABLE, str(exc))
    except Exception as exc:
        message = str(exc).lower()
        if "cloudflare" in message or "turnstile" in message:
            return sutran_result(
                plate,
                QueryStatus.REQUIRES_INTERACTION,
                "SUTRAN exige resolver la verificacion Turnstile.",
            )
        return sutran_result(
            plate,
            QueryStatus.UNAVAILABLE,
            "No se pudo completar la sesion con el portal SUTRAN.",
        )

    if "status" not in holder:
        if holder.get("error") is not None:
            return sutran_result(
                plate,
                QueryStatus.UNAVAILABLE,
                "El navegador no pudo completar el formulario de SUTRAN.",
            )
        return sutran_result(
            plate,
            QueryStatus.REQUIRES_INTERACTION,
            "SUTRAN no entrego el resultado. Puede requerir verificacion manual.",
        )
    try:
        http_status = int(holder["status"])
    except (TypeError, ValueError):
        http_status = 0
    result = result_from_response(plate, http_status, holder.get("payload"))
    if result.status in {QueryStatus.SUCCESS, QueryStatus.NOT_FOUND}:
        result.data.setdefault("capture", {
            "method": "stealth_api",
            "captured_at": datetime.now(timezone.utc).isoformat(),
        })
    return result
