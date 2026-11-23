# Flujo de Git

Este repositorio usa Git Flow.

## Ramas permanentes

- `main`: código estable listo para publicar.
- `develop`: integración de las próximas versiones.

## Ramas temporales

- `feature/<nombre>`: nuevas funciones; se crean desde `develop`.
- `release/<version>`: preparación de una versión; se crea desde `develop`.
- `hotfix/<nombre>`: corrección urgente; se crea desde `main`.

## Flujo normal

```powershell
git switch develop
git switch -c feature/nueva-fuente
# desarrollo y pruebas
git add <archivos>
git commit -m "feat: implementar nueva fuente"
git switch develop
git merge --no-ff feature/nueva-fuente
git branch -d feature/nueva-fuente
```

## Commits

Usar mensajes claros en español o inglés, por ejemplo:

- `feat: agregar conector SUTRAN`
- `fix: corregir validación de placa`
- `docs: actualizar API local`
- `test: cubrir respuestas vacías`

Antes de integrar una rama:

```powershell
uv run --extra dev python -m unittest discover -s tests -v
uv run python -m compileall -q src tests
```

No incluir `.venv`, `.env`, `.cache`, `artifacts` ni archivos con datos personales.
