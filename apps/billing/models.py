import uuid
from django.db import models
from django.utils.translation import gettext_lazy as _
from django_extensions.db.models import TimeStampedModel


class Subscription(TimeStampedModel):
    """Assinatura de um tenant."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.OneToOneField("tenants.Tenant", on_delete=models.CASCADE, related_name="subscription")
    plan = models.CharField(_("plano"), max_length=20)
    started_at = models.DateTimeField(_("início"))
    expires_at = models.DateTimeField(_("expiração"), null=True, blank=True)
    is_active = models.BooleanField(_("ativa"), default=True)

    class Meta:
        verbose_name = _("Assinatura")
        verbose_name_plural = _("Assinaturas")

    def __str__(self):
        return f"{self.tenant} — {self.plan}"
