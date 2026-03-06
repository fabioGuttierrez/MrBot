import uuid
from django.db import models
from django.utils.translation import gettext_lazy as _
from django_extensions.db.models import TimeStampedModel


class Flow(TimeStampedModel):
    """Fluxo de atendimento de um bot."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="flows")
    bot = models.OneToOneField("bots.Bot", on_delete=models.CASCADE, related_name="flow", null=True, blank=True)
    name = models.CharField(_("nome"), max_length=100)
    is_active = models.BooleanField(_("ativo"), default=True)
    definition = models.JSONField(_("definição do fluxo"), default=dict)

    class Meta:
        verbose_name = _("Flow")
        verbose_name_plural = _("Flows")
        ordering = ["tenant", "name"]

    def __str__(self):
        return f"{self.name} ({self.tenant})"
