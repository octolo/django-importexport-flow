-- Reset django-importexport-flow database objects.
--
-- 1. Deletes all ExportConfigTable rows.
-- 2. Drops every app table if it exists (default Django table names).
-- 3. Removes migration history for app label django_importexport_flow.
--
-- PostgreSQL: run as-is.
-- SQLite: run "PRAGMA foreign_keys = OFF;" before this script, then "PRAGMA foreign_keys = ON;" after.

BEGIN;

-- ---------------------------------------------------------------------------
-- Export table configurations only
-- ---------------------------------------------------------------------------
DELETE FROM django_importexport_flow_exportconfigtable;

-- ---------------------------------------------------------------------------
-- Drop app tables (children first)
-- ---------------------------------------------------------------------------
DROP TABLE IF EXISTS django_importexport_flow_exportrequestrelatedobject;
DROP TABLE IF EXISTS django_importexport_flow_importrequestrelatedobject;

DROP TABLE IF EXISTS django_importexport_flow_exportrequest;
DROP TABLE IF EXISTS django_importexport_flow_exportconfigtable;
DROP TABLE IF EXISTS django_importexport_flow_exportconfigpdf;

DROP TABLE IF EXISTS django_importexport_flow_importrequest;

DROP TABLE IF EXISTS django_importexport_flow_exportdefinition_exclude_relations;
DROP TABLE IF EXISTS django_importexport_flow_importdefinition_exclude_relations;

DROP TABLE IF EXISTS django_importexport_flow_importdefinition;
DROP TABLE IF EXISTS django_importexport_flow_exportdefinition;

-- Legacy table names (pre db_table removal)
DROP TABLE IF EXISTS django_reportimport_reportrequest;
DROP TABLE IF EXISTS django_reportimport_reportconfigtable;
DROP TABLE IF EXISTS django_reportimport_reportconfigpdf;
DROP TABLE IF EXISTS django_reporting_reportimportask;
DROP TABLE IF EXISTS django_reporting_reportimport;
DROP TABLE IF EXISTS django_reportimport_reportdefinition;

-- ---------------------------------------------------------------------------
-- Django migration history for this app
-- ---------------------------------------------------------------------------
DELETE FROM django_migrations
WHERE app = 'django_importexport_flow';

COMMIT;
