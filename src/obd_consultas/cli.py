"""CLI de investigacion, consultas y servidor local."""
import argparse
from dataclasses import asdict
import json
import sys
from pathlib import Path

from obd_consultas.bootstrap import build_service
from obd_consultas.domain.models import InvalidPlate, QueryStatus, Source, normalize_plate


def _format_from_suffix(output: Path | None) -> str:
    suffix = (output.suffix if output else "").lower()
    if suffix in {".html", ".htm"}:
        return "html"
    if suffix in {".txt", ".text"}:
        return "text"
    return "md"


def _extract(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    from obd_consultas.infrastructure.extraction import (
        ExtractionError,
        selector_html,
        to_markdown,
        to_text,
    )
    from obd_consultas.infrastructure.scrapling_engine import (
        ScraplingUnavailable,
        fetch_page,
    )

    if not 5 <= args.timeout <= 600:
        parser.error("--timeout debe estar entre 5 y 600 segundos.")
    if args.no_headless and not args.stealth:
        parser.error("--no-headless solo aplica con --stealth.")
    if args.wait_selector and not args.stealth:
        parser.error("--wait-selector solo aplica con --stealth.")

    options = {
        "headless": not args.no_headless,
        "real_chrome": args.real_chrome,
        "timeout": args.timeout * 1000,
        "retries": 1,
        "profile": args.profile,
        "proxy": args.proxy,
    }
    try:
        if args.stealth:
            page = fetch_page(
                args.url,
                stealth=True,
                options=options,
                timeout=args.timeout * 1000,
                wait_selector=args.wait_selector,
            )
        else:
            page = fetch_page(
                args.url,
                stealth=False,
                http_options={"timeout": args.timeout, "retries": 1},
            )
    except ScraplingUnavailable as exc:
        parser.exit(1, f"{exc}\n")
    except Exception as exc:
        parser.exit(1, f"No se pudo descargar la pagina: {exc}\n")

    status = getattr(page, "status", 0) or 0
    if status >= 400:
        parser.exit(1, f"La pagina devolvio HTTP {status}.\n")

    selector = args.xpath_selector or args.css_selector
    engine = "xpath" if args.xpath_selector else "css"
    output_format = args.format or _format_from_suffix(args.output)
    try:
        if output_format == "html":
            content = selector_html(page, selector, engine=engine)
        elif output_format == "text":
            content = to_text(page, selector, engine=engine)
        else:
            content = to_markdown(
                page,
                selector,
                engine=engine,
                main_content_only=args.main_content,
            )
    except ExtractionError as exc:
        parser.exit(1, f"No se pudo extraer el contenido: {exc}\n")

    if not content.strip():
        parser.exit(1, "La extraccion quedo vacia. Revisa el selector o usa --stealth.\n")

    if args.output is None:
        print(content)
        return
    if args.output.exists() and not args.force:
        parser.exit(1, f"El archivo ya existe: {args.output}. Usa --force para reemplazarlo.\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(content + "\n", encoding="utf-8")
    print(f"Guardado: {args.output}", file=sys.stderr)


def _install_browsers(force: bool) -> None:
    import subprocess

    commands = [
        [sys.executable, "-m", "playwright", "install", "chromium"],
        [sys.executable, "-m", "patchright", "install", "chromium"],
    ]
    if sys.platform.startswith("linux"):
        commands.insert(1, [sys.executable, "-m", "playwright", "install-deps", "chromium"])
    for command in commands:
        if force:
            command.append("--force")
        print("Ejecutando: " + " ".join(command[2:]), file=sys.stderr)
        subprocess.run(command, check=True)


def main() -> None:
    # Windows suele abrir la consola en cp1252; Markdown y nombres traen Unicode.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("sources", help="Lista fuentes y estado de implementacion")
    inspect = commands.add_parser("inspect", help="Abre el portal para investigacion manual")
    inspect.add_argument("source", choices=[s.value for s in Source])
    inspect.add_argument("--list", action="store_true", help="Solo muestra la URL")
    query = commands.add_parser("query", help="Ejecuta un conector y devuelve JSON")
    query.add_argument("source", choices=[s.value for s in Source])
    query.add_argument("plate")
    mode = query.add_mutually_exclusive_group()
    mode.add_argument("--interactive", action="store_true", help="Consulta asistida (SOAT o MTC) en navegador visible")
    mode.add_argument("--stealth", action="store_true", help="Consulta desatendida (SOAT, SUNARP, MTC o SUTRAN)")
    query.add_argument("--timeout", type=int, default=180, help="Espera de consulta: 10 a 600 segundos")
    query.add_argument("--browser", choices=["msedge", "chrome", "chromium"], default="msedge")
    query.add_argument("--show-browser", action="store_true", help="Con --stealth, muestra el navegador")
    query.add_argument("--real-chrome", action="store_true", help="Con --stealth, usa el Chrome instalado")
    query.add_argument("--profile", type=Path, help="Con --stealth, reutiliza un perfil de navegador")
    query.add_argument("--proxy", help="Proxy para --stealth; tambien OBD_PROXY_URL")
    extract = commands.add_parser(
        "extract",
        help="Descarga una pagina y guarda Markdown, texto o HTML",
    )
    extract.add_argument("url")
    extract.add_argument("--output", type=Path, help="Archivo destino; sin el, imprime en consola")
    selectors = extract.add_mutually_exclusive_group()
    selectors.add_argument("--css", dest="css_selector", help="Selector CSS a extraer")
    selectors.add_argument("--xpath", dest="xpath_selector", help="Selector XPath a extraer")
    extract.add_argument("--format", choices=["md", "text", "html"], help="Formato de salida")
    extract.add_argument("--main-content", action="store_true", help="Con Markdown, limita al contenido del body")
    extract.add_argument("--stealth", action="store_true", help="Navegador sigiloso; necesario con Cloudflare o JavaScript")
    extract.add_argument("--no-headless", action="store_true", help="Muestra el navegador")
    extract.add_argument("--real-chrome", action="store_true", help="Usa el Chrome instalado")
    extract.add_argument("--wait-selector", help="Espera este selector CSS antes de extraer")
    extract.add_argument("--timeout", type=int, default=60, help="Espera: 5 a 600 segundos")
    extract.add_argument("--profile", type=Path, help="Reutiliza un perfil de navegador")
    extract.add_argument("--proxy", help="Proxy; tambien OBD_PROXY_URL")
    extract.add_argument("--force", action="store_true", help="Reemplaza el archivo de salida")
    install = commands.add_parser("install-browsers", help="Descarga Chromium para Playwright y Patchright")
    install.add_argument("--force", action="store_true", help="Reinstala aunque ya exista")
    ingest = commands.add_parser("import-soat", help="Procesa una captura DOM guardada, sin consultar el portal")
    ingest.add_argument("file", type=Path)
    ingest.add_argument("--plate", required=True)
    ingest.add_argument("--output", type=Path, help="Guarda el JSON normalizado; falla si el archivo ya existe")
    serve = commands.add_parser("serve", help="Inicia la API local")
    serve.add_argument("--host", default="127.0.0.1", help="Direccion de escucha; 0.0.0.0 expone en LAN")
    serve.add_argument("--port", type=int, default=8000)
    argv = sys.argv[1:]
    # Compatibilidad con el comando inicial: obd-consultas soat --list.
    if argv and argv[0] in {s.value for s in Source}:
        argv = ["inspect", *argv]
    args = parser.parse_args(argv)
    service = build_service()

    if args.command == "sources":
        print(json.dumps([asdict(info) for info in service.sources()], indent=2, ensure_ascii=False))
    elif args.command == "inspect":
        info = service.source_info(Source(args.source))
        print(f"Fuente: {info.name}\nURL: {info.url}")
        if not args.list:
            from playwright.sync_api import Error
            from obd_consultas.infrastructure.browser import inspect_source
            try:
                inspect_source(info)
            except Error as exc:
                parser.exit(1, f"No se pudo inspeccionar la fuente: {exc}\n")
    elif args.command == "query":
        try:
            if args.interactive:
                if args.source not in {"soat", "mtc"}:
                    parser.error("El modo asistido solo esta implementado para SOAT y MTC.")
                if not 10 <= args.timeout <= 600:
                    parser.error("--timeout debe estar entre 10 y 600 segundos.")
                if args.source == "mtc":
                    from obd_consultas.infrastructure.mtc_browser import query_mtc_interactive
                    query = query_mtc_interactive
                else:
                    from obd_consultas.infrastructure.soat_browser import query_soat_interactive
                    query = query_soat_interactive
                result = query(normalize_plate(args.plate), args.timeout, args.browser)
            elif args.stealth:
                if args.source not in {"soat", "sunarp", "mtc", "sutran"}:
                    parser.error("El modo sigiloso solo esta implementado para SOAT, SUNARP, MTC y SUTRAN.")
                if not 10 <= args.timeout <= 600:
                    parser.error("--timeout debe estar entre 10 y 600 segundos.")
                if args.source == "sunarp":
                    from obd_consultas.infrastructure.sunarp_stealth import query_sunarp_stealth
                    query = query_sunarp_stealth
                elif args.source == "mtc":
                    from obd_consultas.infrastructure.mtc_stealth import query_mtc_stealth
                    query = query_mtc_stealth
                elif args.source == "sutran":
                    from obd_consultas.infrastructure.sutran_stealth import query_sutran_stealth
                    query = query_sutran_stealth
                else:
                    from obd_consultas.infrastructure.soat_stealth import query_soat_stealth
                    query = query_soat_stealth
                result = query(
                    normalize_plate(args.plate),
                    args.timeout,
                    headless=not args.show_browser,
                    real_chrome=args.real_chrome,
                    profile=str(args.profile) if args.profile else None,
                    proxy=args.proxy,
                )
            else:
                result = service.query(Source(args.source), args.plate)
        except InvalidPlate as exc:
            parser.error(str(exc))
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        if result.status != QueryStatus.SUCCESS:
            raise SystemExit(1)
    elif args.command == "extract":
        _extract(args, parser)
    elif args.command == "install-browsers":
        try:
            _install_browsers(args.force)
        except Exception as exc:
            parser.exit(1, f"No se pudieron instalar los navegadores: {exc}\n")
    elif args.command == "import-soat":
        from obd_consultas.providers.soat_dom import result_from_dom_capture
        try:
            plate = normalize_plate(args.plate)
            capture = json.loads(args.file.read_text(encoding="utf-8-sig"))
            result = result_from_dom_capture(capture, plate, imported=True)
            encoded = json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
            if args.output and result.status == QueryStatus.SUCCESS:
                with args.output.open("x", encoding="utf-8") as output:
                    output.write(encoded + "\n")
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
        print(encoded)
        if result.status != QueryStatus.SUCCESS:
            raise SystemExit(1)
    elif args.command == "serve":
        import os
        import uvicorn
        loopback = {"127.0.0.1", "localhost", "::1"}
        if args.host not in loopback and not os.environ.get("OBD_API_TOKEN", "").strip():
            parser.exit(
                1,
                "Para exponer la API fuera de esta PC define OBD_API_TOKEN primero.\n"
                "Ejemplo: $env:OBD_API_TOKEN='clave-larga'; obd-consultas serve --host 0.0.0.0\n",
            )
        uvicorn.run("obd_consultas.api.app:create_app", factory=True, host=args.host, port=args.port, access_log=False)


if __name__ == "__main__":
    main()
