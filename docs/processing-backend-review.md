# Revue : déclenchement au `save` + `processing_backend`

Revue du travail ajouté autour de `engine/core/processing.py`, des `save()`
de `ImportRequest` / `ExportRequest`, et de `run_export_with_audit`.
Classé par gravité. Chaque point indique le fichier concerné.

## Risques (à traiter en priorité)

### 1. Perte du type d'exception dans `run_export_with_audit` (régression)
`utils/process.py`

Avant, l'export levait la vraie exception (`ValidationError`, `ValueError`,
`TypeError`, `OSError`, `MemoryError`) et l'admin (`admin/export_definition.py`)
les distinguait pour afficher le bon message.

Maintenant `process_export_request` avale l'exception dans `error_trace`, puis
`run_export_with_audit` la re-lève en devinant le type par **sous-chaîne du
traceback** :

```python
if "ValidationError" in trace or "ValueError" in trace:
    raise ValueError(trace)
raise RuntimeError(trace or "Export failed.")
```

Conséquences :
- `TypeError`, `OSError`, `MemoryError` ne sont plus distingués → l'admin tombe
  dans le `except Exception` générique (« Export failed. »).
- `ValidationError` (que l'admin traite à part) devient un `ValueError`.
- Matching fragile : un message métier contenant « ValueError » fausse le type.

Piste : faire remonter le type réel (stocker l'exception, ou laisser
`process_export_request` propager et n'écrire l'audit qu'autour).

### 2. Ordre `related_object` vs traitement (import)
`engine/core/run.py` (`create_import_request`)

L'enchaînement est :

```python
ask.save()
ask.data_file.save(name, ContentFile(raw), save=True)
if trigger_processing:
    ask.save(trigger_processing=True, asynchronous=asynchronous)   # ← traitement ICI
if related_object is not None:
    ImportRequestRelatedObject.objects.create(...)                  # ← lien APRÈS
```

En mode synchrone, l'import s'exécute **avant** la création du lien
`related_object`. Donc :
- un `processing_backend` custom ne voit pas encore l'objet lié pendant son run ;
- `active_imports_for_object` ne compte pas la requête tant qu'elle tourne.

Piste : créer le lien avant de déclencher (`trigger_processing` en dernier).

### 3. Tout export est désormais persisté sur disque (`output_file`)
`models/export_request.py`, `engine/core/processing.py`

Avant, l'export était streamé en réponse HTTP sans être écrit. Maintenant chaque
export réussi écrit un fichier dans `MEDIA_ROOT/export_outputs/...` (lu ensuite
par `run_export_with_audit`).

Risques :
- **Croissance du stockage** non bornée (aucune purge).
- **Confidentialité** : des données potentiellement sensibles restent dans
  `MEDIA_ROOT`, souvent servi publiquement. Pas de contrôle d'accès sur le
  fichier.

Piste : si la persistance n'est pas un besoin, garder l'export en mémoire pour le
chemin natif. Sinon, prévoir purge + stockage privé + permissions.

### 4. `processing_backend` = exécution de code arbitraire
`engine/core/processing.py`

`import_string(backend)` puis `getattr(model, method_name)` exécutent un callable
désigné par une chaîne éditable en admin. C'est de la config « staff de
confiance » uniquement (même profil de risque que `loaddata`). À documenter
explicitement, et idéalement restreindre (allow-list de préfixes, ou champ non
éditable hors superuser).

### 5. Statut `processing` non visible en `ATOMIC_REQUESTS` (import async)
`models/import_request.py`

La branche async de `save()` diffère tout via `transaction.on_commit`, et
`dispatch_import_request` rajoute lui-même un `on_commit`. En autocommit (tests)
ça s'exécute tout de suite ; mais sous `ATOMIC_REQUESTS` (cas admin courant), le
commit n'a pas eu lieu quand l'admin fait `refresh_from_db()` → le statut est
encore `pending`, donc le message « import en arrière-plan » ne s'affiche pas.
Avant, `dispatch_import_request` passait `processing` de façon synchrone (dans son
`atomic()`) avant de rendre la main.

Piste : laisser `dispatch_import_request` gérer seul le sync/async (cf. §6) au
lieu de redoubler la logique `on_commit` dans le modèle.

## Simplifications (dette / lisibilité)

### 6. Double logique sync/async (modèle ↔ dispatch)
`models/import_request.py` + `task/__init__.py`

`ImportRequest.save()` reproduit le branchement sync/async qui existe déjà dans
`dispatch_import_request` (qui fait son propre `select_for_update` +
`on_commit`). Le `save()` enveloppe ça dans un `on_commit` supplémentaire.

Piste : dans `save()`, appeler directement `dispatch_import_request(self,
asynchronous=...)` et laisser la fonction gérer le reste. Supprime le
`_enqueue` + le `transaction` importé dans le modèle.

### 7. Trois `save()` successifs à la création d'un import
`engine/core/run.py`

`ask.save()` → `data_file.save(save=True)` → `ask.save(trigger_processing=True)`.
Le 1er save est redondant avec le 2e (qui persiste déjà le fichier). On peut
réduire à deux écritures.

### 8. Code mort / paramètres inutilisés
`engine/core/processing.py`

- `_export_format_meta` : défini, jamais appelé.
- `_ensure_custom_processing_finished(request, terminal)` : `terminal` n'est pas
  utilisé.
- `_import_terminal_statuses(request)` / `_export_terminal_statuses(request)` :
  l'argument `request` est ignoré ; ce sont des constantes. Remplaçables par un
  tuple module-level (les statuts sync/échec sont les mêmes pour les deux
  modèles).
- `_invoke_callable` : wrapper d'une seule ligne (`fn(request, **kwargs)`),
  inlinable.

### 9. Helpers de statut quasi identiques
`engine/core/processing.py`

`_import_terminal_statuses` et `_export_terminal_statuses` renvoient
`(SUCCESS, FAILURE)` — valeurs identiques d'enum. Une seule constante
`TERMINAL_STATUSES = ("success", "failure")` (valeurs `TextChoices`) suffit pour
les deux.

### 10. Export rejoué depuis le snapshot, pas depuis le payload live
`engine/core/processing.py` (`process_export_request`)

`run_export_with_audit` snapshot le payload (filtré à `export_format` / `fr_*` /
`mg_*`), le persiste, puis `process_export_request` le reconstruit pour
`run_table_export`. Avant, l'export tournait sur le `cleaned_data` complet.
Comportement OK si seules ces clés comptent, mais c'est un changement subtil à
garder en tête (toute clé hors préfixes est perdue).

## Points mineurs

- `get_export_processing_config` : `except Exception: continue` est large ;
  cibler `ObjectDoesNotExist` (ou `RelatedObjectDoesNotExist`) serait plus net.
- `_try_model_method` appelle `Model.method(request, **kwargs)` : ne marche
  proprement que pour une `@classmethod` / `@staticmethod`. À documenter
  (signature attendue : `def m(cls, request, **kwargs)`).
- `processing_backend_kwargs` : `null=True` sur un `JSONField` est déconseillé
  par Django (préférer `default=dict` seul).

## Suggestion d'ordre de correction

1. §1 (régression export) et §2 (ordre related_object) — bugs fonctionnels.
2. §3 (persistance fichiers) — décision produit (purge / privé / ou pas de
   persistance).
3. §5 + §6 — unifier la logique async, corrige le statut et simplifie.
4. §7–§9 — nettoyage à faible risque.
