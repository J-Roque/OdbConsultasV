"""Consulta desatendida de infracciones de la ATU (Lima y Callao).

La pasarela es una SPA: al pulsar BUSCAR la propia pagina pide su token de
reCAPTCHA v3 (invisible) y consulta su API, cuyas respuestas van cifradas. El
conector no toca el token ni la API: elige "Por Placa", escribe la placa, pulsa
BUSCAR y lee lo que la pagina muestra (la tabla o el aviso).
"""
from __future__ import annotations

from collections.abc import Callable
from time import monotonic
from typing import Any

from obd_consultas.domain.models import QueryResult, QueryStatus, normalize_plate
from obd_consultas.infrastructure.connector_common import (
    guarded,
    result_from_error,
    session_failure,
    stamp_capture,
    stealth_options,
    validate_timeout,
)
from obd_consultas.infrastructure.scrapling_engine import stealth_session
from obd_consultas.providers.atu import ATU_FORM_URL, atu_result, result_from_snapshot

MENU_ITEM = "Consulta y Pago de Infracciones"
SEARCH_TYPE = "#TipoBusquedaselectElemento"
SEARCH_BY_PLATE = "2"
PLATE_INPUT = "#PlacaBusquedainputElemento"
RESULT_WAIT_MS = 45_000
MAX_SESSIONS = 2
MIN_ATTEMPT_MS = 40_000

# El select es de Materialize: se cambia el <select> nativo y se avisa con
# "change", que es lo que escucha el componente de la pagina.
SELECT_PLATE = f"""() => {{
  const select = document.querySelector('{SEARCH_TYPE}');
  select.value = '{SEARCH_BY_PLATE}';
  select.dispatchEvent(new Event('change', {{bubbles: true}}));
}}"""

# Foto de lo que ve el usuario: aviso visible (SweetAlert2) y tabla visible.
SNAPSHOT = """() => {
  const visible = el => el && el.offsetWidth > 0 && el.offsetHeight > 0;
  const popup = [...document.querySelectorAll('.swal2-popup')].find(visible);
  const icon = popup ? ['info', 'error', 'warning', 'success', 'question']
      .find(name => popup.classList.contains('swal2-icon-' + name)) || null : null;
  const text = popup && popup.querySelector('.swal2-html-container, .swal2-content');
  const table = [...document.querySelectorAll('table')].find(visible);
  const head = table ? [...table.querySelectorAll('thead th')].map(th => th.innerText) : [];
  const rows = table ? [...table.querySelectorAll('tbody tr')]
      .map(tr => [...tr.querySelectorAll('td')].map(td => td.innerText)) : [];
  const counter = [...document.querySelectorAll('div, span')]
      .map(el => el.childElementCount === 0 ? el.innerText : '')
      .find(t => /^Registros\\s+\\d+\\s*-\\s*\\d+\\s+de\\s+\\d+/.test((t || '').trim())) || null;
  return {modal: popup ? (text ? text.innerText : popup.innerText) : null, icon, head, rows, counter};
}"""


def _has_result(snapshot: dict[str, Any]) -> bool:
    if snapshot.get("modal"):
        return True
    rows = snapshot.get("rows") or []
    return any(len(row) > 1 for row in rows if isinstance(row, list))


def _observe(page: Any, plate: str, timeout_ms: int, holder: dict[str, Any]) -> None:
    page.wait_for_timeout(2_000)
    page.keyboard.press("Escape")  # cierra el comunicado que aparece al entrar
    page.get_by_text(MENU_ITEM, exact=True).first.dispatch_event("click")
    page.wait_for_selector(SEARCH_TYPE, state="attached", timeout=20_000)
    page.evaluate(SELECT_PLATE)
    page.locator(PLATE_INPUT).fill(plate, timeout=15_000)
    page.get_by_role("button", name="BUSCAR").click(timeout=15_000)

    wait_ms = min(timeout_ms, RESULT_WAIT_MS)
    elapsed = 0
    while elapsed < wait_ms:
        page.wait_for_timeout(500)
        elapsed += 500
        snapshot = page.evaluate(SNAPSHOT)
        if isinstance(snapshot, dict) and _has_result(snapshot):
            holder["snapshot"] = snapshot
            return


def _result_from_holder(plate: str, holder: dict[str, Any]) -> QueryResult:
    snapshot = holder.get("snapshot")
    if isinstance(snapshot, dict):
        return stamp_capture(result_from_snapshot(plate, snapshot), "stealth_dom")
    return result_from_error(
        plate,
        {"error": holder["error"]} if holder.get("error") is not None else {},
        atu_result,
        failure_message="El navegador no pudo completar el formulario de la ATU.",
        empty_message="La ATU no mostro resultado a tiempo. Prueba de nuevo en unos minutos.",
    )


def query_atu_stealth(
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
    result: QueryResult | None = None
    for attempt in range(1, MAX_SESSIONS + 1):
        remaining_ms = int((deadline - monotonic()) * 1000)
        if attempt > 1 and remaining_ms < MIN_ATTEMPT_MS:
            break
        result = _attempt(plate, remaining_ms, headless, real_chrome, profile, proxy, session_factory)
        # Una sesion nueva solo ayuda si la pagina no llego a mostrar resultado.
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
        solve_cloudflare=False,
        timeout_ms=browser_timeout,
        profile=profile,
        proxy=proxy,
    )
    try:
        with session_factory(**options) as session:
            session.fetch(
                ATU_FORM_URL,
                page_action=guarded(lambda page: _observe(page, plate, timeout_ms, holder), holder),
                timeout=browser_timeout,
                wait=1_000,
            )
    except Exception as exc:
        return session_failure(
            plate,
            exc,
            atu_result,
            challenge_words=("recaptcha",),
            challenge_message="La ATU exige resolver la verificacion reCAPTCHA.",
            failure_message="No se pudo completar la sesion con la pasarela ATU.",
        )
    return _result_from_holder(plate, holder)
