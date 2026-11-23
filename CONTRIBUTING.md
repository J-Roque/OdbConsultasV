# Contribuir

## Preparar el clon

```powershell
uv sync --extra dev
git config core.hooksPath .githooks   # activa pre-commit (secretos) y commit-msg
Copy-Item .env.example .env           # completa valores; .env nunca se sube
```

## Git Flow

```text
main      ──●────────────●──────────●──   solo versiones publicadas (tags vX.Y.Z)
             \          / \        /
release/*     \      ●─●   \      /
               \    /       \    /
develop   ──●───●──●─────────●──●──────   integracion
             \    /           \
feature/*     ●──●             hotfix/* ──●  (sale de main, vuelve a main y develop)
```

| Rama | Sale de | Se integra en | Para |
|---|---|---|---|
| `main` | - | - | Codigo publicado. Cada merge lleva tag `vX.Y.Z`. |
| `develop` | `main` | - | Integracion de la proxima version. |
| `feature/<nombre>` | `develop` | `develop` | Funciones nuevas, conectores, docs. |
| `release/<X.Y.Z>` | `develop` | `main` y `develop` | Congelar version: CHANGELOG, numero de version, ultimos fixes. |
| `hotfix/<nombre>` | `main` | `main` y `develop` | Correccion urgente de lo publicado. |

### Reglas

1. **Nunca commits directos en `main` ni `develop`.** Todo entra por Pull Request.
2. Un PR por tema; ramas cortas. Nombres en minusculas con guiones:
   `feature/conector-atu`, `hotfix/placa-con-guion`.
3. El PR necesita CI en verde (tests + escaneo de secretos).
4. `feature/*` -> `develop`: **squash merge**. `release/*` y `hotfix/*` -> `main`: **merge commit** (`--no-ff`) y tag.
5. Borra la rama al integrarla.

### Ciclo de una feature

```powershell
git switch develop
git pull
git switch -c feature/conector-atu
# ... cambios + tests ...
git push -u origin feature/conector-atu
# abrir PR feature/conector-atu -> develop en GitHub
```

### Publicar una version

```powershell
git switch develop; git pull
git switch -c release/0.2.0
# actualizar version en pyproject.toml y src/obd_consultas/api/app.py, mover "Sin publicar" en CHANGELOG.md
git push -u origin release/0.2.0
# PR release/0.2.0 -> main; tras el merge:
git switch main; git pull
git tag -a v0.2.0 -m "v0.2.0"
git push origin v0.2.0
# integrar main de vuelta en develop (PR main -> develop)
```

### Proteccion de ramas en GitHub

En *Settings > Branches > Add rule* (o *Rulesets*) para `main` y `develop`:

- Require a pull request before merging.
- Require status checks to pass: `Secretos`, `Tests`.
- Block force pushes y deletions.
- (`main`) Require linear history desactivado, para permitir merge commits de release.

En *Settings > Code security*: activar **Secret scanning** y **Push protection**
(bloquea en el servidor pushes con tokens conocidos) y **Dependabot alerts**.

## Commits

[Conventional Commits](https://www.conventionalcommits.org/es/). El hook
`commit-msg` lo valida:

```text
tipo(alcance opcional): descripcion en imperativo
```

Tipos: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `chore`, `ci`, `build`, `security`.
Ejemplos: `feat(sunarp): leer placa anterior`, `fix(api): rechazar timeout negativo`,
`security(api): ocultar openapi por defecto`. `!` tras el tipo marca un cambio
incompatible: `feat(api)!: exigir token siempre`.

## Antes de abrir el PR

```powershell
uv run --extra dev python -m unittest discover -s tests -v
uv run python -m compileall -q src tests scripts
python scripts/check_secrets.py --all
```

- Tests solo con datos sinteticos.
- Rutas nuevas de la API con `dependencies=protected`.
- Actualiza `README.md`, `docs/` y la seccion *Sin publicar* de `CHANGELOG.md`.
- No incluir `.venv`, `.env`, `.cache`, `artifacts`, cookies, capturas ni datos personales.
  Ver [SECURITY.md](SECURITY.md).

## Documentacion

| Archivo | Contenido |
|---|---|
| `README.md` | Que es, estado, como instalar y usar |
| `docs/ARQUITECTURA.md` | Capas, decisiones y como agregar un conector |
| `docs/API.md` | Contrato HTTP, seguridad y uso desde la APK |
| `docs/<FUENTE>.md` | Evidencia, flujo y contrato de cada portal |
| `docs/PLAN.md` | Inventario de fuentes y orden sugerido |
| `SECURITY.md` | Secretos, datos personales, controles de la API |
| `CHANGELOG.md` | Cambios por version ([Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)) |

Un conector nuevo agrega su `docs/<FUENTE>.md` y su fila en `docs/PLAN.md` y en el README.
