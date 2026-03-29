#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

import os
import sys
from pathlib import Path


def _load_env_file() -> None:
    """Load .env file into os.environ. Uses project root (script dir) or ENVFILE_PATH."""
    project_root = Path(__file__).resolve().parent
    env_path = os.environ.get("ENVFILE_PATH", ".env")
    path = Path(env_path) if Path(env_path).is_absolute() else project_root / env_path
    if not path.exists():
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(path, override=False)
    except ImportError:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    key = key.strip()
                    if key and key not in os.environ:
                        os.environ[key] = val.strip().strip('"').strip("'")


def create_superuser():
    """Creates default superuser if none exists."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    if not User.objects.filter(is_superuser=True).exists():
        print("📦 Creating superuser: admin/admin")
        User.objects.create_superuser("admin", "admin@example.com", "admin")
        print("✅ Superuser created successfully!")
        print("   Username: admin")
        print("   Password: admin")
    else:
        print("✅ Superuser already exists")


def main():
    """Runs administrative tasks."""
    _load_env_file()
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")

    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc

    if len(sys.argv) > 1 and sys.argv[1] == "migrate":
        execute_from_command_line(sys.argv)
        create_superuser()
        return

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
