## Que cambia

<!-- Resumen corto y por que -->

## Tipo

- [ ] feat
- [ ] fix
- [ ] docs
- [ ] test / refactor / chore
- [ ] security

## Checklist

- [ ] La rama sale de `develop` (o de `main` si es `hotfix/*`) y apunta a la rama correcta.
- [ ] `uv run --extra dev python -m unittest discover -s tests -v` pasa.
- [ ] No incluye `.env`, cookies, capturas, `.cache/`, `artifacts/` ni datos reales de personas o placas.
- [ ] Los tests usan solo datos sinteticos.
- [ ] Si toca la API: las rutas nuevas usan `dependencies=protected` y tienen test de 401.
- [ ] Documentacion actualizada (`README.md`, `docs/`, `CHANGELOG.md`).
