## À réfléchir

### 2. ~~Logique d'export natif dupliquée~~ **Fait**
Extrait dans `_finalize_native_export(er, content, ext)` dans
`engine/core/processing.py`. Les deux appelants (`process_export_request` et
`run_export_with_audit`) l'utilisent.

### 3. ~~Reconstruction divergente du payload d'export~~ **Fait**
Extrait dans `_build_er_filter_payload(er)` dans `engine/core/processing.py`.
Les deux appelants (`process_export_request` et `run_export_with_audit`) utilisent
maintenant la même fonction pour construire le payload passé à `run_table_export`.

### 4. ~~Asymétrie async entre import et export~~ **Fait**
Export aligné sur import :
- `execute_export_request_by_uuid` + `run_export_request_task` ajoutés à `tasks.py`.
- `enqueue_export` ajouté aux quatre backends (sync, thread, celery, rq).
- `dispatch_export_request` supporte `asynchronous=` avec lock + `on_commit`.
- `ExportRequest.save()` accepte `asynchronous=`.
- `ExportRequestAddForm` + case à cocher admin, piloté par
  `EXPORT_ADMIN_OFFER_ASYNC` / `EXPORT_ADMIN_ASYNC_DEFAULT`.

### 5. ~~`output_file` pas réellement « source unique » pour le natif~~ **Acté**

Design retenu : `run_export_with_audit` (chemin HTTP synchrone) produit les bytes
en mémoire, écrit `output_file` comme artefact persistant, et retourne les bytes
directement — **sans relecture disque**.

Raisonnement : relire `output_file` immédiatement après l'avoir écrit serait un
aller-disque inutile (les bytes sont déjà en mémoire). `output_file` est garanti
rempli sur tous les exports réussis (natif et custom), ce qui satisfait les
besoins d'audit, re-téléchargement et async. La « source unique » tient pour tous
les usages non-HTTP ; le chemin HTTP retourne simplement les bytes sans passer par
le fichier.
