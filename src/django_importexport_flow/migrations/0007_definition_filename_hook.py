from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("django_importexport_flow", "0006_definition_manager_method_kwargs_request"),
    ]

    operations = [
        migrations.AddField(
            model_name="definition",
            name="filename_hook",
            field=models.CharField(
                blank=True,
                default="",
                help_text=(
                    "Export only. Dotted path to a filename hook. Leave empty for the default names."
                ),
                max_length=255,
                verbose_name="Filename hook",
            ),
        ),
    ]
