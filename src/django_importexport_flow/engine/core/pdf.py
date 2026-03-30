from django.template import Template

from .engine import CoreEngine


class PdfEngine(CoreEngine):
    def get_template(self):
        return self.definition.config_pdf.template

    def get_context(self):
        return {"object_list": self.get_queryset()}

    def render(self):
        tpl = Template(self.get_template() or "")
        return tpl.render(self.get_context())

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
