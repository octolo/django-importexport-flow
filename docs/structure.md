# Project structure

```
django-importexport-flow/
├── src/django_importexport_flow/
│   ├── engine/
│   │   ├── core.py         # CoreEngine: queryset, filters, order_by
│   │   ├── table.py        # TableEngine (CSV/Excel/JSON rows)
│   │   └── pdf.py          # PdfEngine
│   ├── models/
│   │   ├── report_definition.py   # ExportDefinition
│   │   ├── config_table.py # ExportConfigTable
│   │   ├── config_pdf.py   # ExportConfigPdf
│   │   └── report_import.py
│   ├── admin/              # ExportDefinition admin, generate export, ReportImport
│   ├── export.py           # run_table_export, DefinitionFilterProxy, request helpers
│   ├── forms.py            # Export generate form, JSON import form
│   ├── validation.py       # Filters, columns, order_by, parse_filter_maps
│   ├── serialization.py    # JSON export of configuration
│   ├── http.py             # Content-Disposition helpers
│   ├── utils.py
│   ├── managers.py
│   └── migrations/
├── tests/
├── docs/
├── pyproject.toml
└── README.md
```

- **`ExportConfigTable.columns`**: list of column strings (JSON).
- **Engines** use **`CoreEngine`** for the queryset; table/pdf layers add formatting and export.

See also [filters-and-export.md](filters-and-export.md).
