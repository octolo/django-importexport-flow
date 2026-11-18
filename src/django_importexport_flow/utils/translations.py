"""Column header translations stored on :class:`ColumnTranslation`."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import models
from django.db.utils import OperationalError, ProgrammingError
from django.utils import translation


def _norm_lang(code: str) -> str:
    return code.replace("_", "-").strip().lower()


def language_candidates(language: str | None = None) -> list[str]:
    raw = language or translation.get_language() or settings.LANGUAGE_CODE or ""
    default = settings.LANGUAGE_CODE or ""
    out: list[str] = []
    for code in (raw, default):
        norm = _norm_lang(code)
        if not norm:
            continue
        if norm not in out:
            out.append(norm)
        primary = norm.split("-", 1)[0]
        if primary and primary not in out:
            out.append(primary)
    return out


def load_column_translations(
    model: type[models.Model],
    paths: set[str],
) -> dict[str, list[tuple[str, str]]]:
    """One query for every stored translation of ``paths`` on ``model``."""
    if not paths:
        return {}
    try:
        from django.contrib.contenttypes.models import ContentType

        from ..models.translation import ColumnTranslation

        content_type = ContentType.objects.get_for_model(model)
        rows = ColumnTranslation.objects.filter(
            content_type=content_type,
            path__in=paths,
        ).values_list("path", "language", "label")
    except (OperationalError, ProgrammingError):
        return {}
    grouped: dict[str, list[tuple[str, str]]] = {}
    for path, language, label in rows:
        grouped.setdefault(path, []).append((str(language), str(label)))
    return grouped


def _best(rows: list[tuple[str, str]], language: str | None) -> str | None:
    wanted = language_candidates(language)
    best: str | None = None
    best_rank = len(wanted)
    for lang, label in rows:
        text = label.strip()
        norm = _norm_lang(lang)
        if not text or norm not in wanted:
            continue
        rank = wanted.index(norm)
        if rank < best_rank:
            best = text
            best_rank = rank
    return best


def all_column_translations(
    model: type[models.Model],
    path: str,
    *,
    catalog: dict[str, list[tuple[str, str]]] | None = None,
) -> list[str]:
    cleaned = path.strip()
    rows = (catalog or load_column_translations(model, {cleaned})).get(cleaned, [])
    found: list[str] = []
    for _lang, label in rows:
        text = label.strip()
        if text and text not in found:
            found.append(text)
    return found


def _related_model_for(model: type[models.Model], relation: str):
    from .helpers import _next_model_for_rel_field, get_field_or_accessor

    field = get_field_or_accessor(model, relation)
    if field is None:
        return None
    return _next_model_for_rel_field(field)


def _leaf_model_path(model: type[models.Model], path: str):
    from django.db.models import JSONField

    from .helpers import get_field_or_accessor

    parts = [part for part in path.strip().split(".") if part]
    if len(parts) < 2:
        return None
    current = model
    for index, part in enumerate(parts):
        field = get_field_or_accessor(current, part)
        if field is None or isinstance(field, JSONField):
            return None
        if index == len(parts) - 1:
            if current is model:
                return None
            return current, part
        related = _related_model_for(current, part)
        if related is None:
            return None
        current = related
    return None


def _translation(
    model: type[models.Model],
    path: str,
    *,
    language: str | None = None,
    catalog: dict[str, list[tuple[str, str]]] | None = None,
) -> str | None:
    cleaned = path.strip()
    rows = (catalog if catalog is not None else load_column_translations(model, {cleaned})).get(
        cleaned, []
    )
    return _best(rows, language)


def resolve_column_header(
    model: type[models.Model],
    path: str,
    *,
    configuration: dict[str, Any] | None = None,
    language: str | None = None,
) -> str:
    from .helpers import (
        column_label_override_from_configuration,
        label_for_slot_path,
        verbose_name_for_field_path,
    )

    override = column_label_override_from_configuration(configuration, path)
    if override:
        return override
    translated = _translation(model, path, language=language)
    if translated:
        return translated
    leaf = _leaf_model_path(model, path)
    if leaf is not None:
        translated = _translation(leaf[0], leaf[1], language=language)
        if translated:
            return translated
    slot = label_for_slot_path(model, path)
    if slot:
        return slot
    verbose = verbose_name_for_field_path(model, path)
    if verbose and str(verbose).strip():
        return str(verbose).strip()
    return path


def _slot_header_aliases(
    model: type[models.Model],
    path: str,
    aliases: set[str],
    catalogs: dict[type[models.Model], dict[str, list[tuple[str, str]]]],
) -> bool:
    from .helpers import M2M_SLOT_PATH_PATTERN, verbose_name_for_field_path

    slot = M2M_SLOT_PATH_PATTERN.match(path.strip())
    if slot is None:
        return False
    rel_name, slot_s, sub = slot.groups()
    index = int(slot_s) + 1
    root = catalogs.get(model)
    bases = all_column_translations(model, f"{rel_name}.{sub}", catalog=root)
    related = _related_model_for(model, rel_name)
    if related is not None:
        verbose = verbose_name_for_field_path(related, sub)
        bases.extend(all_column_translations(related, sub, catalog=catalogs.get(related)))
        if verbose and str(verbose).strip():
            bases.append(str(verbose).strip())
    for base in bases:
        if base:
            aliases.add(base)
            aliases.add(f"{base} {index}")
    return True


def import_header_aliases(
    model: type[models.Model],
    path: str,
    *,
    configuration: dict[str, Any] | None = None,
    catalogs: dict[type[models.Model], dict[str, list[tuple[str, str]]]] | None = None,
) -> set[str]:
    """Header strings that identify ``path``, without resolving the display header."""
    from .helpers import column_label_override_from_configuration, verbose_name_for_field_path

    catalogs = catalogs or {}
    aliases = {path.strip()}
    override = column_label_override_from_configuration(configuration, path)
    if override:
        aliases.add(override)
    for text in all_column_translations(model, path, catalog=catalogs.get(model)):
        aliases.add(text)
    if _slot_header_aliases(model, path, aliases, catalogs):
        return {item for item in aliases if item}
    leaf = _leaf_model_path(model, path)
    if leaf is not None:
        leaf_model, leaf_path = leaf
        for text in all_column_translations(
            leaf_model, leaf_path, catalog=catalogs.get(leaf_model)
        ):
            aliases.add(text)
    verbose = verbose_name_for_field_path(model, path)
    if verbose and str(verbose).strip():
        aliases.add(str(verbose).strip())
    return {item for item in aliases if item}


def catalogs_for_paths(
    model: type[models.Model],
    paths: list[str],
) -> dict[type[models.Model], dict[str, list[tuple[str, str]]]]:
    """Load root and related translations once for a set of import paths."""
    from .helpers import M2M_SLOT_PATH_PATTERN

    root_paths = set(paths)
    related_paths: dict[type[models.Model], set[str]] = {}
    for path in paths:
        slot = M2M_SLOT_PATH_PATTERN.match(path.strip())
        if slot:
            rel_name, _slot_s, sub = slot.groups()
            root_paths.add(f"{rel_name}.{sub}")
            related = _related_model_for(model, rel_name)
            if related is not None:
                related_paths.setdefault(related, set()).add(sub)
            continue
        leaf = _leaf_model_path(model, path)
        if leaf is not None:
            related_paths.setdefault(leaf[0], set()).add(leaf[1])
    catalogs = {model: load_column_translations(model, root_paths)}
    for related, related_set in related_paths.items():
        catalogs[related] = load_column_translations(related, related_set)
    return catalogs
