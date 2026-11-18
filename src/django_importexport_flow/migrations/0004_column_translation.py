import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("django_importexport_flow", "0003_alter_exportrequest_output_file"),
    ]

    operations = [
        migrations.CreateModel(
            name="ColumnTranslation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "path",
                    models.CharField(
                        help_text="Column path on this model, e.g. author.name or tags.name.",
                        max_length=255,
                        verbose_name="Path",
                    ),
                ),
                (
                    "language",
                    models.CharField(
                        help_text="Language code, e.g. fr or en.",
                        max_length=16,
                        verbose_name="Language",
                    ),
                ),
                ("label", models.CharField(max_length=255, verbose_name="Label")),
                (
                    "content_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="column_translations",
                        to="contenttypes.contenttype",
                        verbose_name="Content type",
                    ),
                ),
            ],
            options={
                "verbose_name": "Column translation",
                "verbose_name_plural": "Column translations",
                "ordering": ("content_type", "path", "language"),
                "constraints": [
                    models.UniqueConstraint(
                        fields=("content_type", "path", "language"),
                        name="uniq_column_translation_path_language",
                    )
                ],
            },
        ),
    ]
