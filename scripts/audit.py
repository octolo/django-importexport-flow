"""Run all local audit checks and report failures at the end."""

import os
import platform
import shlex
import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "src/django_importexport_flow"
MIGRATIONS = "*/migrations/*"


def main() -> int:
    with (ROOT / "pyproject.toml").open("rb") as manifest:
        version = tomllib.load(manifest)["project"]["version"]

    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except OSError as exc:
        commit = f"unavailable ({exc})"
    except subprocess.CalledProcessError as exc:
        commit = f"unavailable ({exc.stderr.strip()})"

    print("# django-importexport-flow audit\n")
    print(f"Generated: {datetime.now(UTC):%Y-%m-%dT%H:%M:%SZ}")
    print(f"Package: {version}")
    print(f"Commit: {commit}")
    print(f"Python: {platform.python_version()} ({sys.executable})")
    print(f"Platform: {platform.platform()}")
    print("\nThis report mirrors the local commands in docs/current-state-audit.md.")
    print("makemigrations is intentionally not run.", flush=True)

    failures: list[str] = []

    def run_check(name: str, *command: str) -> None:
        display = subprocess.list2cmdline(command) if os.name == "nt" else shlex.join(command)
        print(f"\n## {name}\n\n$ {display}\n", flush=True)
        try:
            status = subprocess.run(command, cwd=ROOT, check=False).returncode
        except OSError as exc:
            print(f"Could not start command: {exc}", flush=True)
            failures.append(f"{name} (could not start command)")
            return
        print(f"\nExit status: {status}", flush=True)
        if status:
            failures.append(f"{name} ({status})")

    def run_module(name: str, module: str, *args: str) -> None:
        run_check(name, sys.executable, "-m", module, *args)

    with TemporaryDirectory(prefix="django-importexport-flow-audit-") as build_dir:
        run_check("Django system check", sys.executable, "manage.py", "check")
        run_module("Ruff lint", "ruff", "check", "src", "tests")
        run_module("Ruff format", "ruff", "format", "--check", "src", "tests")
        run_check("Git whitespace check", "git", "diff", "--check")
        run_module(
            "Tests, branch coverage, and strict warnings",
            "pytest",
            "-q",
            "--tb=line",
            "--cov=django_importexport_flow",
            "--cov-branch",
            "--cov-report=term:skip-covered",
            "-W",
            "error::ResourceWarning",
            "-W",
            "error::pytest.PytestUnraisableExceptionWarning",
            "-W",
            "error::django.core.paginator.UnorderedObjectListWarning",
        )
        run_module("Bandit", "bandit", "-r", SOURCE, "-x", f"{SOURCE}/migrations", "-ll", "-ii")
        run_module("Dependency audit", "pip_audit", ".")
        run_module(
            "Dead code", "vulture", SOURCE, "--min-confidence", "90", "--exclude", MIGRATIONS
        )
        run_module(
            "Cyclomatic complexity inventory", "radon", "cc", SOURCE, "-s", "-a", "-e", MIGRATIONS
        )
        run_module("Maintainability index", "radon", "mi", SOURCE, "-s", "-e", MIGRATIONS)
        run_module("Code size metrics", "radon", "raw", SOURCE, "-s", "-e", MIGRATIONS)
        run_module(
            "Complexity thresholds",
            "xenon",
            SOURCE,
            "--exclude",
            MIGRATIONS,
            "--max-absolute",
            "C",
            "--max-modules",
            "B",
            "--max-average",
            "A",
        )
        run_module("Type checking", "mypy", SOURCE)
        run_module("Package build", "build", "--outdir", build_dir)

        distributions = sorted(path for path in Path(build_dir).iterdir() if path.is_file())
        if distributions:
            run_module("Distribution validation", "twine", "check", *map(str, distributions))
        else:
            failures.append("Distribution validation (package build produced no files)")

        wheels = [str(path) for path in distributions if path.suffix == ".whl"]
        if wheels:
            run_check(
                "Wheel contents", sys.executable, ".github/scripts/check-wheel-contents.py", *wheels
            )
        else:
            failures.append("Wheel contents (package build produced no wheel)")

    print("\n## Summary\n")
    if not failures:
        print("All checks passed.")
        return 0
    print(f"{len(failures)} check(s) failed:")
    for failure in failures:
        print(f"- {failure}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
