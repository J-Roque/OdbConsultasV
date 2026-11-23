"""Consulta asistida del MTC: el captcha de imagen lo resuelve una persona.

Este modulo no lee, descifra ni elude el captcha. Abre el formulario oficial en
un navegador visible, completa la placa y espera a que el usuario escriba el
codigo y pulse Buscar. Luego lee la respuesta JSON o los paneles visibles.
"""
from __future__ import annotations

from datetime import datetime, timezone
import sys
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import Error, TimeoutError, sync_playwright

from obd_consultas.domain.models import QueryResult, QueryStatus, normalize_plate
from obd_consultas.providers.mtc import MTC_INFO, mtc_result, result_from_dom_capture, result_from_response

CAPTURE_SCRIPT = r"""() => {
  const records = [];
  for (let p = 1; p <= 3; p++) {
    const plate = document.getElementById(`Spv${p}_3`);
    if (!plate || !plate.innerText.trim()) continue;
    const get = (n) => document.getElementById(`Spv${p}_${n}`)?.innerText.trim() || '';
    records.push({
      SRAZONSOCENTCER: get(1), DIRECCION: get(2), PLACA: get(3),
      NRO_CERTI: get(4), REVISIONVIGENCIAINICIO: get(5), REVISIONVIGENCIAFINAL: get(6),
      RESULTADO: get(7), ESTADO: get(8), TIPO_AMBITO: get(9),
      TIPO_SERVICIO: get(10), OBSERVACION: get(11), TIPODOCUMENTO: get(12)
    });
  }
  return {format: 'mtc-dom-v1', source_url: location.href, records: records};
}"""


def is_query_response(url: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname in {"rec.mtc.gob.pe", "portal.mtc.gob.pe"}
        and parsed.path.rstrip("/") == "/CITV/JrCITVConsultarFiltro"
    )


def _safe_json(response: Any) -> Any:
    try:
        return response.json()
    except Exception:
        return None


def _result_from_holder(plate: str, holder: dict[str, Any]) -> QueryResult:
    if "status" in holder:
        result = result_from_response(plate, int(holder.get("status") or 0), holder.get("payload"))
        if result.status in {QueryStatus.SUCCESS, QueryStatus.NOT_FOUND}:
            result.data.setdefault(
                "capture",
                {
                    "method": "browser_api",
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        return result
    if "dom" in holder:
        result = result_from_dom_capture(holder["dom"], plate)
        if result.status == QueryStatus.SUCCESS:
            result.data.setdefault("capture", {})["captured_at"] = datetime.now(timezone.utc).isoformat()
        return result
    if "error" in holder and holder["error"].__class__.__name__ == "TimeoutError":
        return mtc_result(
            plate,
            QueryStatus.REQUIRES_INTERACTION,
            "No se recibio el resultado a tiempo. El captcha puede seguir pendiente.",
        )
    if "error" in holder:
        return mtc_result(plate, QueryStatus.UNAVAILABLE, "El navegador no pudo completar la consulta.")
    return mtc_result(
        plate,
        QueryStatus.REQUIRES_INTERACTION,
        "El portal no entrego el resultado. Completa el captcha en el navegador.",
    )


def query_mtc_interactive(
    plate: str, timeout: int = 180, browser_channel: str = "msedge"
) -> QueryResult:
    plate = normalize_plate(plate)
    if not 10 <= timeout <= 600:
        raise ValueError("El tiempo de espera debe estar entre 10 y 600 segundos.")
    holder: dict[str, Any] = {}

    def observe(page: Any) -> None:
        def on_response(response: Any) -> None:
            if is_query_response(str(getattr(response, "url", ""))):
                # Guardar el objeto y leerlo fuera del manejador: response.json()
                # dentro del evento puede fallar si el cuerpo aun no esta listo.
                holder["status"] = getattr(response, "status", None)
                holder["response"] = response

        page.on("response", on_response)
        page.goto(MTC_INFO.url, wait_until="domcontentloaded", timeout=30_000)
        page.locator("#texFiltro").fill(plate, timeout=20_000)
        print(
            "Lee el captcha en el navegador, escribelo en 'Ingresar Captcha' y pulsa Buscar.",
            file=sys.stderr,
            flush=True,
        )
        print(f"Espera maxima del resultado: {timeout} segundos.", file=sys.stderr, flush=True)

        deadline = page.evaluate("Date.now()") + timeout * 1000
        while page.evaluate("Date.now()") < deadline:
            if "response" in holder:
                holder["payload"] = _safe_json(holder.pop("response"))
                return
            if "status" in holder and "payload" in holder:
                return
            if page.locator("#Panel1").is_visible() and page.locator("#Spv1_3").inner_text().strip():
                holder["dom"] = page.evaluate(CAPTURE_SCRIPT)
                return
            page.wait_for_timeout(500)

    try:
        with sync_playwright() as pw:
            options: dict[str, Any] = {"headless": False}
            if browser_channel != "chromium":
                options["channel"] = browser_channel
            browser = pw.chromium.launch(**options)
            try:
                context = browser.new_context()
                try:
                    observe(context.new_page())
                finally:
                    context.close()
            finally:
                browser.close()
    except TimeoutError as exc:
        holder["error"] = exc
    except Error as exc:
        holder["error"] = exc
    return _result_from_holder(plate, holder)
