import uuid
from django.db import models
from django.utils.translation import gettext_lazy as _
from django_extensions.db.models import TimeStampedModel


class SessionStatus(models.TextChoices):
    DISCONNECTED = "disconnected", _("Desconectado")
    CONNECTING = "connecting", _("Conectando")
    CONNECTED = "connected", _("Conectado")
    ERROR = "error", _("Erro")


class WhatsAppSession(TimeStampedModel):
    """Sessão WhatsApp via Evolution API por tenant."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="wa_sessions")
    name = models.CharField(_("nome da sessão"), max_length=100)
    instance_id = models.CharField(_("instance ID Evolution"), max_length=200, unique=True)
    token = models.CharField(_("token Evolution"), max_length=500)
    status = models.CharField(_("status"), max_length=20, choices=SessionStatus.choices, default=SessionStatus.DISCONNECTED)
    phone_number = models.CharField(_("número WhatsApp"), max_length=30, blank=True)
    is_active = models.BooleanField(_("ativa"), default=True)

    class Meta:
        verbose_name = _("Sessão WhatsApp")
        verbose_name_plural = _("Sessões WhatsApp")
        ordering = ["tenant", "name"]

    def __str__(self):
        return f"{self.name} ({self.phone_number or self.instance_id})"
