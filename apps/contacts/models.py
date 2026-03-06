import uuid
from django.db import models
from django.utils.translation import gettext_lazy as _
from django_extensions.db.models import TimeStampedModel


class ContactStage(models.TextChoices):
    LEAD = "lead", _("Lead")
    PROSPECT = "prospect", _("Prospect")
    CLIENT = "client", _("Cliente")
    INACTIVE = "inactive", _("Inativo")


class Contact(TimeStampedModel):
    """Contato/lead de um tenant."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="contacts")
    phone = models.CharField(_("telefone"), max_length=30)
    name = models.CharField(_("nome"), max_length=200, blank=True)
    email = models.EmailField(_("e-mail"), blank=True)
    avatar_url = models.URLField(_("avatar URL"), blank=True)
    stage = models.CharField(_("estágio"), max_length=20, choices=ContactStage.choices, default=ContactStage.LEAD)
    tags = models.JSONField(_("tags"), default=list, blank=True)
    notes = models.TextField(_("notas"), blank=True)
    extra_data = models.JSONField(_("dados extras"), default=dict, blank=True)

    class Meta:
        verbose_name = _("Contato")
        verbose_name_plural = _("Contatos")
        unique_together = ("tenant", "phone")
        ordering = ["-created"]

    def __str__(self):
        return self.name or self.phone

    @property
    def display_name(self):
        return self.name or self.phone
