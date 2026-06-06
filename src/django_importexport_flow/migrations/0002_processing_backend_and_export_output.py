# Generated manually for processing_backend and export request workflow.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("django_importexport_flow", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="exportconfigpdf",
            name="processing_backend",
            field=models.CharField(
                blank=True,
                help_text=(
                    "Optional dotted import path (e.g. myapp.tasks.run_import) or a method name "
                    "on the target model. When empty, the built-in import/export engine is used."
                ),
                max_length=255,
                null=True,
                verbose_name="Processing backend",
            ),
        ),
        migrations.AddField(
            model_name="exportconfigpdf",
            name="processing_backend_kwargs",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Keyword arguments passed to the processing backend callable.",
                verbose_name="Processing backend kwargs",
            ),
        ),
        migrations.AddField(
            model_name="exportconfigtable",
            name="processing_backend",
            field=models.CharField(
                blank=True,
                help_text=(
                    "Optional dotted import path (e.g. myapp.tasks.run_import) or a method name "
                    "on the target model. When empty, the built-in import/export engine is used."
                ),
                max_length=255,
                null=True,
                verbose_name="Processing backend",
            ),
        ),
        migrations.AddField(
            model_name="exportconfigtable",
            name="processing_backend_kwargs",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Keyword arguments passed to the processing backend callable.",
                verbose_name="Processing backend kwargs",
            ),
        ),
        migrations.AddField(
            model_name="importdefinition",
            name="processing_backend",
            field=models.CharField(
                blank=True,
                help_text=(
                    "Optional dotted import path (e.g. myapp.tasks.run_import) or a method name "
                    "on the target model. When empty, the built-in import/export engine is used."
                ),
                max_length=255,
                null=True,
                verbose_name="Processing backend",
            ),
        ),
        migrations.AddField(
            model_name="importdefinition",
            name="processing_backend_kwargs",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Keyword arguments passed to the processing backend callable.",
                verbose_name="Processing backend kwargs",
            ),
        ),
        migrations.AddField(
            model_name="exportrequest",
            name="output_file",
            field=models.FileField(
                blank=True,
                help_text="Generated export file when status is success.",
                upload_to="export_outputs/%Y/%m/",
                verbose_name="Output file",
            ),
        ),
        migrations.AlterField(
            model_name="exportrequest",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("processing", "Processing"),
                    ("success", "Success"),
                    ("failure", "Failure"),
                ],
                default="pending",
                max_length=16,
                verbose_name="Status",
            ),
        ),
    ]
