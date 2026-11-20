from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("django_importexport_flow", "0005_export_import_categories"),
    ]

    operations = [
        migrations.AddField(
            model_name="definition",
            name="manager_method_kwargs_request",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text=("Export only. {query_param: method_argument} read from mm_get_<param>."),
                null=True,
                verbose_name="Manager method request arguments",
            ),
        ),
        migrations.AlterField(
            model_name="exportrequest",
            name="manager_kwargs_payload",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text=(
                    "mg_* manager filters and mm_* manager method arguments from the export form."
                ),
                verbose_name="Manager request payload",
            ),
        ),
    ]
