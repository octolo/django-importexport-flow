"""Verify that built wheels contain the admin templates and static files."""

from __future__ import annotations

import sys
from pathlib import Path
from zipfile import ZipFile

EXPECTED = (
    "django_importexport_flow/templates/django_importexport_flow/admin/report_import_import_confirm.html",
    "django_importexport_flow/templates/django_importexport_flow/admin/report_import_import_data.html",
)
MIGRATIONS = "django_importexport_flow/migrations/"


def main() -> None:
    wheels = [Path(arg) for arg in sys.argv[1:]]
    if not wheels:
        raise SystemExit("pass at least one wheel")
    for wheel in wheels:
        with ZipFile(wheel) as archive:
            names = set(archive.namelist())
        missing = [name for name in EXPECTED if name not in names]
        if not any(name.startswith(MIGRATIONS) and name.endswith(".py") for name in names):
            missing.append(MIGRATIONS)
        if missing:
            raise SystemExit(f"{wheel} is missing packaged content: {', '.join(missing)}")
        print(f"{wheel}: package data verified")


if __name__ == "__main__":
    main()
