import json
from io import BytesIO, StringIO
from typing import Any

import pandas as pd

from ..models import ImportDefinition, ExportConfigTable
from ..utils import (
    get_expanded_related_value,
    get_value_from_path,
    max_relation_counts,
    normalize_table_column,
    parse_reverse_expand_spec,
    resolve_expand_relation,
    resolve_table_column_label,
    verbose_name_for_field_path,
)
from .core import CoreEngine


def _format_cell_export_value(value: Any) -> Any:
    """Serialize dict/list (e.g. JSONField) for tabular exports when needed."""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


class TableEngine(CoreEngine):
    """Tabular export: CSV, Excel, and JSON via pandas (``to_csv`` / ``to_excel`` / ``to_json``)."""

    def __init__(self, definition, request=None, config=None):
        if config is None:
            if isinstance(definition, ImportDefinition):
                config = definition
            else:
                try:
                    config = definition.config_table
                except ExportConfigTable.DoesNotExist:
                    config = None
        super().__init__(definition, request, config)
        self._flat_columns_cache: list[dict[str, Any]] | None = None
        self._expand_prefetch_relations: list[str] = []

    def _parse_column_pieces(self) -> list[tuple[Any, ...]]:
        if isinstance(self.definition, ImportDefinition):
            from ..utils.import_tabular import effective_import_column_paths

            raw = effective_import_column_paths(self.definition)
        else:
            raw = (self.config.columns or []) if self.config else []
        model = self.get_model()
        pieces: list[tuple[Any, ...]] = []
        for col in raw:
            spec = normalize_table_column(col)
            parsed = parse_reverse_expand_spec(spec)
            if parsed:
                rel, subfields = parsed
                related_model, py_accessor = resolve_expand_relation(model, rel)
                pieces.append(("expand", py_accessor, subfields, related_model))
            else:
                pieces.append(("scalar", spec))
        return pieces

    def _build_flat_columns(self) -> list[dict[str, Any]]:
        pieces = self._parse_column_pieces()
        model = self.get_model()
        expand_rels = [p[1] for p in pieces if p[0] == "expand"]
        self._expand_prefetch_relations = expand_rels

        flat: list[dict[str, Any]] = []
        if not expand_rels:
            for p in pieces:
                data = p[1]
                label = resolve_table_column_label(model, data)
                flat.append({"kind": "scalar", "data": data, "label": label})
            return flat

        qs = self.get_queryset()
        if expand_rels:
            qs = qs.prefetch_related(*expand_rels)
        counts = max_relation_counts(qs, expand_rels)

        for p in pieces:
            if p[0] == "scalar":
                data = p[1]
                label = resolve_table_column_label(model, data)
                flat.append({"kind": "scalar", "data": data, "label": label})
            else:
                py_accessor, subfields, related_model = p[1], p[2], p[3]
                n_slots = counts.get(py_accessor, 0)
                for slot in range(n_slots):
                    for sf in subfields:
                        vn = verbose_name_for_field_path(related_model, sf) or sf
                        label = f"{vn} {slot + 1}"
                        flat.append(
                            {
                                "kind": "expand",
                                "relation": py_accessor,
                                "slot": slot,
                                "field": sf,
                                "label": label,
                            }
                        )
        return flat

    def _get_flat_columns(self) -> list[dict[str, Any]]:
        if self._flat_columns_cache is None:
            self._flat_columns_cache = self._build_flat_columns()
        return self._flat_columns_cache

    def _queryset_for_table(self):
        qs = self.get_queryset()
        if self._expand_prefetch_relations:
            qs = qs.prefetch_related(*self._expand_prefetch_relations)
        return qs

    @classmethod
    def _cell_value(cls, obj: Any, col: dict[str, Any]) -> Any:
        if col["kind"] == "scalar":
            raw = get_value_from_path(obj, col["data"])
            return _format_cell_export_value(raw)
        raw = get_expanded_related_value(
            obj, col["relation"], col["slot"], col["field"]
        )
        return _format_cell_export_value(raw)

    @classmethod
    def _cell_value_native(cls, obj: Any, col: dict[str, Any]) -> Any:
        """Raw values for pandas (dict/list preserved for ``to_json``)."""
        if col["kind"] == "scalar":
            return get_value_from_path(obj, col["data"])
        return get_expanded_related_value(
            obj, col["relation"], col["slot"], col["field"]
        )

    def get_columns(self):
        if not self.config:
            return []
        flat = self._get_flat_columns()
        out = []
        for c in flat:
            if c["kind"] == "scalar":
                out.append({"data": c["data"], "label": c["label"]})
            else:
                out.append(
                    {
                        "data": {
                            "expand": True,
                            "relation": c["relation"],
                            "slot": c["slot"],
                            "field": c["field"],
                        },
                        "label": c["label"],
                    }
                )
        return out

    def get_headers(self):
        return [c["label"] for c in self._get_flat_columns()]

    def get_rows(self):
        cols = self._get_flat_columns()
        return [
            [self._cell_value(obj, c) for c in cols]
            for obj in self._queryset_for_table()
        ]

    def get_dataframe(self) -> pd.DataFrame:
        """Rows as a DataFrame with verbose column labels and native cell values."""
        if not self.config:
            return pd.DataFrame()
        cols = self._get_flat_columns()
        headers = [c["label"] for c in cols]
        records = [
            [self._cell_value_native(obj, c) for c in cols]
            for obj in self._queryset_for_table()
        ]
        return pd.DataFrame.from_records(records, columns=headers)

    def get_configuration(self):
        if not self.config:
            return {}
        return self.config.configuration or {}

    def get_json_payload(self) -> dict[str, Any]:
        """``headers`` and ``records`` (list of row dicts), for APIs or custom wrapping."""
        df = self.get_dataframe()
        return {
            "headers": list(df.columns),
            "records": df.to_dict(orient="records"),
        }

    def get_json(self) -> str:
        """JSON text via :meth:`pandas.DataFrame.to_json` (default ``orient="records"``)."""
        cfg = self.get_configuration() or {}
        opts = (cfg.get("json") or {}).copy()
        if "orient" not in opts:
            opts["orient"] = "records"
        if "force_ascii" not in opts:
            opts["force_ascii"] = False
        return self.get_dataframe().to_json(**opts)

    def get_json_bytes(self) -> bytes:
        return self.get_json().encode("utf-8")

    def get_csv(self) -> bytes:
        """CSV via :meth:`pandas.DataFrame.to_csv` (``index=False``)."""
        cfg = self.get_configuration() or {}
        csv_opts = (cfg.get("csv") or {}).copy()
        sep = csv_opts.pop("delimiter", ",")
        if not isinstance(sep, str) or len(sep) != 1:
            sep = ","
        buffer = StringIO()
        self.get_dataframe().to_csv(buffer, index=False, sep=sep, **csv_opts)
        return buffer.getvalue().encode("utf-8")

    def get_excel(self) -> bytes:
        """Excel via :meth:`pandas.DataFrame.to_excel` (requires ``openpyxl`` for ``.xlsx``)."""
        cfg = self.get_configuration() or {}
        excel_opts = (cfg.get("excel") or {}).copy()
        sheet_name = excel_opts.pop("sheet", excel_opts.pop("sheet_name", "Sheet1"))
        buffer = BytesIO()
        self.get_dataframe().to_excel(
            buffer,
            index=False,
            sheet_name=sheet_name,
            engine="openpyxl",
            **excel_opts,
        )
        return buffer.getvalue()


ExportTableEngine = TableEngine
