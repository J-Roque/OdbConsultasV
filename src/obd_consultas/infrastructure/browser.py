"""Herramienta de investigacion manual, separada del flujo HTTP."""
from playwright.sync_api import sync_playwright

from obd_consultas.domain.models import SourceInfo


def inspect_source(info: SourceInfo) -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        try:
            context = browser.new_context()
            try:
                page = context.new_page()
                page.goto(info.url, wait_until="domcontentloaded", timeout=60_000)
                print("Completa el formulario y cualquier verificacion en el navegador.")
                print("Pulsa Resume en Playwright Inspector para terminar.")
                page.pause()
            finally:
                context.close()
        finally:
            browser.close()
