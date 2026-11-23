"""Consulta asistida: lee el resultado visible aunque no se capture la respuesta JSON."""
from datetime import UTC, datetime
import sys
from typing import Any
from urllib.parse import unquote, urlparse

from playwright.sync_api import Error, TimeoutError, sync_playwright

from obd_consultas.domain.models import QueryResult, QueryStatus, normalize_plate
from obd_consultas.infrastructure.connector_common import validate_timeout
from obd_consultas.providers.soat import SOAT_INFO, soat_result
from obd_consultas.providers.soat_dom import CAPTURE_SCRIPT, result_from_dom_capture


def is_query_response(url: str, plate: str) -> bool:
    parsed = urlparse(url)
    return (parsed.scheme == "https" and parsed.hostname == "www.apeseg.org.pe"
            and unquote(parsed.path).rstrip("/") == f"/wp-json/apeseg-soat/v1/placa/{plate}")


def capture_result(page) -> dict:
    root = page.locator(".soat-resultado")
    toggle = root.locator(".soat-historial__toggle")
    if toggle.count() and toggle.get_attribute("aria-expanded") != "true":
        toggle.click(timeout=5_000)
    if toggle.count():
        root.locator(".soat-timeline__item").first.wait_for(timeout=5_000)
    capture = root.evaluate(CAPTURE_SCRIPT)
    capture["captured_at"] = datetime.now(UTC).isoformat()
    return capture


def query_soat_interactive(plate: str, timeout: int = 180, browser_channel: str = "msedge") -> QueryResult:
    plate = normalize_plate(plate)
    validate_timeout(timeout)
    try:
        with sync_playwright() as pw:
            options: dict[str, Any] = {"headless": False}
            if browser_channel != "chromium":
                options["channel"] = browser_channel
            browser = pw.chromium.launch(**options)
            try:
                context = browser.new_context()
                try:
                    page = context.new_page()
                    response = page.goto(SOAT_INFO.url, wait_until="domcontentloaded", timeout=30_000)
                    if response is None or response.status != 200:
                        return soat_result(plate, QueryStatus.UNAVAILABLE, "No se pudo cargar el formulario oficial.")
                    page.locator(".soat-placa__input").fill(plate, timeout=20_000)
                    page.get_by_role("button", name="Consultar", exact=True).click(timeout=10_000)
                    print("Consulta enviada. Si el portal pide verificacion, completala en el navegador.", file=sys.stderr, flush=True)
                    print(f"Espera maxima del resultado: {timeout} segundos.", file=sys.stderr, flush=True)
                    outcome = page.locator(".soat-resultado, .soat-aviso").first
                    outcome.wait_for(state="visible", timeout=timeout * 1000)
                    if page.locator(".soat-resultado").count():
                        return result_from_dom_capture(capture_result(page), plate)
                    notice = outcome.inner_text()
                    if f"No encontramos certificados SOAT para la placa {plate}" in notice:
                        return soat_result(plate, QueryStatus.NOT_FOUND, "La fuente no encontro certificados para esta placa.",
                                           {"encontrado": False, "vigente": False, "soat_vigente": None, "certificados": []})
                    return soat_result(plate, QueryStatus.UNAVAILABLE, "El portal mostro un error y no entrego datos del vehiculo.")
                finally:
                    context.close()
            finally:
                browser.close()
    except TimeoutError:
        return soat_result(plate, QueryStatus.REQUIRES_INTERACTION, "No se recibio el resultado a tiempo. La verificacion puede seguir pendiente.")
    except Error:
        return soat_result(plate, QueryStatus.UNAVAILABLE, "No se pudo completar la sesion. Comprueba el navegador y la conexion.")
