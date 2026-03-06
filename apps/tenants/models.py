import uuid
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils.translation import gettext_lazy as _
from django_extensions.db.models import TimeStampedModel


class Plan(models.TextChoices):
    FREE = "free", _("Free")
    STARTER = "starter", _("Starter")
    PROFESSIONAL = "professional", _("Professional")
    ENTERPRISE = "enterprise", _("Enterprise")


class Tenant(TimeStampedModel):
    """
    Representa uma empresa cliente do MrBot SaaS.
    Todos os dados do sistema são isolados por Tenant.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_("nome da empresa"), max_length=200)
    slug = models.SlugField(_("slug"), max_length=100, unique=True)
    logo = models.ImageField(_("logo"), upload_to="tenants/logos/", blank=True, null=True)
    plan = models.CharField(_("plano"), max_length=20, choices=Plan.choices, default=Plan.FREE)
    is_active = models.BooleanField(_("ativo"), default=True)

    # Limites conforme plano
    max_bots = models.PositiveIntegerField(_("máx. bots"), default=2)
    max_sessions = models.PositiveIntegerField(_("máx. sessões WhatsApp"), default=1)
    max_messages_month = models.PositiveIntegerField(_("máx. mensagens/mês"), default=500)

    # Configurações globais do tenant
    business_hours_start = models.TimeField(_("início atendimento"), default="08:00")
    business_hours_end = models.TimeField(_("fim atendimento"), default="18:00")
    out_of_hours_message = models.TextField(
        _("mensagem fora do horário"),
        default="Olá! Estamos fora do horário de atendimento. Retornaremos em breve.",
        blank=True,
    )

    # Concatenação de mensagens fragmentadas
    message_concat_delay = models.PositiveIntegerField(
        _("delay de concatenação (segundos)"),
        default=10,
        validators=[MinValueValidator(5), MaxValueValidator(60)],
        help_text=_(
            "Tempo em segundos que o sistema aguarda novas mensagens do mesmo "
            "contato antes de processar. Útil para clientes que enviam mensagens "
            "em partes. Mínimo: 5s — Máximo: 60s."
        ),
    )

    class Meta:
        verbose_name = _("Tenant")
        verbose_name_plural = _("Tenants")
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.slug})"
