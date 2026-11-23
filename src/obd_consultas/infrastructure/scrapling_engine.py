"""Motor de scraping basado en Scrapling.

Scrapling (BSD-3-Clause, https://github.com/D4Vinci/Scrapling) se usa como
dependencia: aporta el navegador sigiloso que resuelve retos de Cloudflare, el
HTTP con huella TLS de navegador y el motor de seleccion CSS/XPath. Este modulo
concentra su API para que los conectores no dependan de la version concreta.

No se copia codigo de Scrapling. Si se necesita una version distinta, se cambia
aqui y el resto del proyecto sigue igual.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

DEFAULT_LOCALE = "es-PE"
DEFAULT_TIMEZONE = "America/Lima"
PROXY_ENV = "OBD_PROXY_URL"
PROXY_ROTATION_ENV = "OBD_PROXY_ROTATION"


class ScraplingUnavailable(RuntimeError):
    """Falta Scrapling o los navegadores que necesita."""


def _fetchers_module() -> Any:
    try:
        from scrapling import fetchers
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise ScraplingUnavailable(
            "Scrapling no esta instalado. Ejecuta: uv sync"
        ) from exc
    _quiet_logs()
    return fetchers


def _quiet_logs(level: str = "WARNING") -> None:
    """Evita que los INFO de Scrapling se mezclen con el JSON o el Markdown."""
    try:
        from scrapling.core.utils import log

        log.setLevel(level)
    except Exception:  # pragma: no cover - detalle interno de Scrapling
        pass


def _fetcher_class(name: str) -> Any:
    return getattr(_fetchers_module(), name)


def proxy_from_env() -> str | None:
    """Proxy unico opcional, por ejemplo http://usuario:clave@host:puerto."""
    value = os.environ.get(PROXY_ENV, "").strip()
    return value or None


def proxy_rotator_from_env() -> Any | None:
    """Lista opcional de proxies separados por coma en OBD_PROXY_ROTATION."""
    raw = os.environ.get(PROXY_ROTATION_ENV, "")
    urls = [item.strip() for item in raw.split(",") if item.strip()]
    if not urls:
        return None
    return _fetcher_class("ProxyRotator")(urls)


def browser_options(
    *,
    headless: bool = True,
    real_chrome: bool = False,
    solve_cloudflare: bool = True,
    timeout: int = 30_000,
    retries: int = 2,
    locale: str = DEFAULT_LOCALE,
    timezone_id: str = DEFAULT_TIMEZONE,
    proxy: str | None = None,
    proxy_rotator: Any | None = None,
    block_ads: bool = True,
    profile: str | Path | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    """Opciones comunes del navegador sigiloso, con valores conservadores."""
    options: dict[str, Any] = {
        "headless": headless,
        "real_chrome": real_chrome,
        "solve_cloudflare": solve_cloudflare,
        "timeout": int(timeout),
        "retries": max(1, int(retries)),
        "locale": locale,
        "timezone_id": timezone_id,
        "block_ads": block_ads,
        "load_dom": True,
    }
    rotator = proxy_rotator if proxy_rotator is not None else proxy_rotator_from_env()
    selected = proxy if proxy is not None else proxy_from_env()
    if rotator is not None and selected is None:
        options["proxy_rotator"] = rotator
    elif selected:
        options["proxy"] = selected
    if profile:
        options["user_data_dir"] = str(Path(profile).expanduser().resolve())
    options.update(overrides)
    return options


@contextmanager
def stealth_session(**options: Any) -> Iterator[Any]:
    """Sesion de navegador sigilosa de Scrapling, con cierre garantizado."""
    session_class = _fetcher_class("StealthySession")
    with session_class(**browser_options(**options)) as session:
        yield session


@contextmanager
def http_session(**options: Any) -> Iterator[Any]:
    """Sesion HTTP con cookies y huella TLS, para formularios clasicos.

    Util para portales ASP.NET o PHP que mantienen el resultado en la misma
    sesion: se hace el GET inicial y luego el POST con ``session.post``.
    """
    session_class = _fetcher_class("FetcherSession")
    defaults: dict[str, Any] = {
        "impersonate": "chrome",
        "stealthy_headers": True,
        "timeout": 30,
        "retries": 2,
    }
    defaults.update(options)
    with session_class(**defaults) as session:
        yield session


def fetch_page(
    url: str,
    *,
    stealth: bool = True,
    options: dict[str, Any] | None = None,
    http_options: dict[str, Any] | None = None,
    **fetch_options: Any,
) -> Any:
    """Descarga una pagina y devuelve el ``Response`` de Scrapling.

    ``stealth=True`` usa un Chromium parcheado y resuelve Cloudflare.
    ``stealth=False`` usa HTTP con huella TLS de Chrome (mucho mas rapido).
    """
    if stealth:
        with stealth_session(**(options or {})) as session:
            return session.fetch(url, **fetch_options)
    fetcher = _fetcher_class("Fetcher")
    defaults: dict[str, Any] = {
        "impersonate": "chrome",
        "stealthy_headers": True,
        "timeout": 30,
        "retries": 2,
    }
    defaults.update(http_options or {})
    defaults.update(fetch_options)
    return fetcher.get(url, **defaults)


def parse_html(
    content: str | bytes,
    *,
    url: str = "",
    adaptive: bool = False,
    storage_dir: str | Path | None = None,
) -> Any:
    """Crea un ``Selector`` de Scrapling a partir de HTML ya descargado.

    ``adaptive`` guarda la ubicacion de los elementos para intentar reencontrarlos
    si el portal cambia su estructura. Sin ``storage_dir`` usa la base por defecto
    de Scrapling.
    """
    try:
        from scrapling.parser import Selector
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise ScraplingUnavailable(
            "Scrapling no esta instalado. Ejecuta: uv sync"
        ) from exc

    if not adaptive:
        return Selector(content, url=url)

    options: dict[str, Any] = {"adaptive": True}
    if storage_dir:
        directory = Path(storage_dir).expanduser().resolve()
        directory.mkdir(parents=True, exist_ok=True)
        options["storage_args"] = {
            "storage_file": str(directory / "selectors.db"),
            "url": url,
        }
    return Selector(content, url=url, **options)
