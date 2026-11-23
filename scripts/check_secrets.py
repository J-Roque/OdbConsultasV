"""Bloquea commits con secretos, datos personales o archivos locales.

Uso:
    python scripts/check_secrets.py            # revisa lo que esta en staging
    python scripts/check_secrets.py --all      # revisa todos los archivos versionados

Se ejecuta solo desde ``.githooks/pre-commit``. En CI se complementa con gitleaks.
Solo usa la biblioteca estandar para no depender de herramientas externas.

Para permitir una linea concreta (por ejemplo un valor sintetico en un test)
agrega el comentario ``secret-scan: allow`` en esa misma linea.
"""
from __future__ import annotations

import fnmatch
from pathlib import PurePosixPath
import re
import subprocess
import sys

ALLOW_MARK = "secret-scan: allow"

# Archivos que nunca deben versionarse, aunque alguien fuerce `git add -f`.
FORBIDDEN_PATHS = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.pkl",
    "*.pickle",
    "*cookies*",
    "*.sqlite",
    "*.db",
    ".cache/*",
    "artifacts/*",
    "*.har",
)
ALLOWED_PATHS = (".env.example",)

SECRET_PATTERNS = (
    ("clave privada", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("token de GitHub", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("token de Slack", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("API key de Google", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("API key estilo sk-", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
    ("credenciales en URL", re.compile(r"[a-z][a-z0-9+.\-]*://[^\s/:@'\"]+:[^\s/@'\"]{3,}@[^\s'\"]+", re.I)),
    (
        "asignacion de secreto",
        re.compile(
            r"(?i)\b(OBD_API_TOKEN|OBD_PROXY_URL|[A-Z_]*(?:SECRET|PASSWORD|PASSWD|API_KEY|PRIVATE_KEY))"
            r"\s*[:=]\s*['\"]?([^\s'\"#]{8,})"
        ),
    ),
)

# Valores de ejemplo que no son secretos reales.
PLACEHOLDERS = re.compile(
    r"(?i)(cambia|change|example|ejemplo|placeholder|xxxx|<[^>]+>|\$\{?[A-Z_]+\}?|usuario:clave|user:pass|sintetic)"
)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True, encoding="utf-8").stdout


def _forbidden(path: str) -> bool:
    name = PurePosixPath(path).name
    if path in ALLOWED_PATHS or name in ALLOWED_PATHS:
        return False
    return any(fnmatch.fnmatch(path, p) or fnmatch.fnmatch(name, p) for p in FORBIDDEN_PATHS)


def scan_text(path: str, text: str) -> list[str]:
    problems = []
    for number, line in enumerate(text.splitlines(), start=1):
        if ALLOW_MARK in line:
            continue
        for label, pattern in SECRET_PATTERNS:
            match = pattern.search(line)
            if match and not PLACEHOLDERS.search(match.group(0)):
                problems.append(f"{path}:{number}: posible {label}")
                break
    return problems


def _staged_files() -> list[str]:
    out = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
    return [p for p in out.split("\0") if p]


def _content(path: str, staged: bool) -> str | None:
    ref = f":{path}" if staged else f"HEAD:{path}"
    try:
        raw = subprocess.run(["git", "show", ref], check=True, capture_output=True).stdout
    except subprocess.CalledProcessError:
        return None
    if b"\0" in raw[:8000]:
        return None  # binario
    return raw.decode("utf-8", errors="replace")


def main(argv: list[str]) -> int:
    staged = "--all" not in argv
    files = _staged_files() if staged else [p for p in _git("ls-files", "-z").split("\0") if p]
    problems = []
    for path in files:
        if _forbidden(path):
            problems.append(f"{path}: archivo local o sensible, no debe versionarse")
            continue
        if path == "uv.lock":
            continue
        text = _content(path, staged)
        if text is not None:
            problems.extend(scan_text(path, text))
    if problems:
        print("Revision de secretos: commit bloqueado.", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "Quita el valor (usa .env, que esta ignorado) o, si es un dato sintetico, "
            f"marca la linea con '# {ALLOW_MARK}'.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
