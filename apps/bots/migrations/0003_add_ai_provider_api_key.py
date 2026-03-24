from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bots", "0002_add_tools_enabled"),
    ]

    operations = [
        migrations.AddField(
            model_name="bot",
            name="ai_provider",
            field=models.CharField(
                choices=[
                    ("openai", "OpenAI"),
                    ("anthropic", "Anthropic (Claude)"),
                    ("google", "Google (Gemini)"),
                    ("xai", "xAI (Grok)"),
                ],
                default="openai",
                max_length=20,
                verbose_name="provedor de IA",
            ),
        ),
        migrations.AddField(
            model_name="bot",
            name="api_key",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Deixe em branco para usar a chave global da plataforma",
                max_length=200,
                verbose_name="chave de API",
            ),
        ),
        migrations.AlterField(
            model_name="bot",
            name="model",
            field=models.CharField(
                default="gpt-4o",
                max_length=50,
                verbose_name="modelo",
            ),
        ),
    ]
