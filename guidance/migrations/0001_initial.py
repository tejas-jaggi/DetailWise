from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(
            name="ExplanationQuota",
            fields=[
                ("user", models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE, primary_key=True,
                    related_name="explanation_quota", serialize=False,
                    to=settings.AUTH_USER_MODEL,
                )),
                ("timestamps", models.JSONField(default=list)),
            ],
        ),
    ]
