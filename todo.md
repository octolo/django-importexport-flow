# Backlog — django-importexport-flow

---

## Reste à faire

### CI

- **Pipeline CI** (ex. GitHub Actions) : `pytest`, `ruff`, `mypy`. Pas de `.github/workflows` ni équivalent dans le dépôt. Config locale OK dans `pyproject.toml`.

### Tests manquants

- **Charge / concurrence** (optionnel) : imports ou exports parallèles, gros fichiers — non couvert.

---

## Ordre de travail suggéré

1. CI sur le dépôt.
2. Tests de charge (optionnel).
