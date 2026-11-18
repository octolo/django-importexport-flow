from django.core.exceptions import ObjectDoesNotExist
from django.template import Context, Template

from .engine import CoreEngine


class PdfEngine(CoreEngine):
    def __init__(self, definition, request=None, config=None, *, template_override: str = ""):
        super().__init__(definition, request=request, config=config)
        self.template_override = template_override or ""

    def _pdf_config(self):
        if self.config is not None and hasattr(self.config, "template"):
            return self.config
        from .formats import get_export_config

        try:
            return get_export_config(self.definition, "pdf")
        except (ObjectDoesNotExist, ValueError):
            return None

    def get_template(self):
        if str(self.template_override or "").strip():
            return self.template_override
        config = self._pdf_config()
        if config is None:
            return ""
        return config.template or ""

    def get_context(self):
        return {"object_list": self.get_queryset()}

    def render(self):
        tpl = Template(self.get_template() or "")
        return tpl.render(Context(self.get_context()))

    def get_report(self):
        try:
            from weasyprint import HTML
        except ImportError as exc:
            raise ImportError(
                "PDF export requires WeasyPrint. Install with: "
                "pip install 'django-importexport-flow[pdf]' or pip install weasyprint"
            ) from exc

        return HTML(string=self.render()).write_pdf()


ExportPdfEngine = PdfEngine
