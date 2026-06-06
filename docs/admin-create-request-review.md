# Revue : création de requêtes import/export depuis l'admin

Revue de l'ajout de la création (`Add`) d'`ImportRequest` / `ExportRequest`
dans l'admin. Ce document ne liste plus que **ce qui reste à faire ou à
corriger**. Les points §1 (inlines non sauvegardés au déclenchement), §2 (double
`save()`), §3 (persistance fichier unifiée), §4 (feedback d'erreur admin) et §7
(message `relaunch_selected`) ont été traités.

Tous les points ont été traités. Il ne reste que les prérequis de déploiement
liés à la persistance unifiée des fichiers d'export (§3).

## Prérequis de déploiement

### D. Stockage privé et rétention pour `ExportRequest.output_file`
`models/export_request.py`, `apps.py`, `management/commands/purge_export_requests.py`

`ExportRequest.output_file` est désormais toujours écrit (natif et custom).
Deux points à cadrer côté projet hôte :

- **Stockage privé** : configurer le setting `EXPORT_OUTPUT_STORAGE` (dans
  `DJANGO_IMPORTEXPORT_FLOW`) vers un backend hors `MEDIA_ROOT` public, sans
  accès direct par URL (ex. `storages.backends.s3boto3.S3Boto3Storage` avec
  bucket privé).
- **Rétention** : planifier la commande `purge_export_requests --days N` via
  cron / Celery beat pour éviter l'accumulation de fichiers.
