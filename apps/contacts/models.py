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


# ─── Broadcast / Campanhas ───────────────────────────────────────────────────

class CampaignStatus(models.TextChoices):
    DRAFT     = "draft",     _("Rascunho")
    SCHEDULED = "scheduled", _("Agendada")
    RUNNING   = "running",   _("Executando")
    DONE      = "done",      _("Concluída")
    FAILED    = "failed",    _("Falhou")


class Campaign(TimeStampedModel):
    """Disparo em massa para contatos segmentados por tag."""
    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant      = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="campaigns")
    name        = models.CharField(_("nome"), max_length=200)
    message     = models.TextField(_("mensagem"))
    tags_filter = models.JSONField(_("filtro de tags"), default=list, blank=True,
                                   help_text=_("Lista de tags — todos os contatos que possuam TODAS as tags. Vazio = todos."))
    session     = models.ForeignKey("channels_wa.WhatsAppSession", on_delete=models.SET_NULL,
                                    null=True, related_name="campaigns")
    status      = models.CharField(_("status"), max_length=20, choices=CampaignStatus.choices,
                                   default=CampaignStatus.DRAFT)
    scheduled_at = models.DateTimeField(_("agendar para"), null=True, blank=True)
    sent_count  = models.PositiveIntegerField(_("enviados"), default=0)
    total_count = models.PositiveIntegerField(_("total"), default=0)
    created_by  = models.ForeignKey("accounts.User", on_delete=models.SET_NULL,
                                    null=True, related_name="campaigns")

    class Meta:
        verbose_name = _("Campanha")
        verbose_name_plural = _("Campanhas")
        ordering = ["-created"]

    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"


# ─── Follow-ups agendados ────────────────────────────────────────────────────

class FollowUpStatus(models.TextChoices):
    PENDING   = "pending",   _("Pendente")
    SENT      = "sent",      _("Enviado")
    CANCELLED = "cancelled", _("Cancelado")


class FollowUp(TimeStampedModel):
    """Mensagem agendada para envio futuro a um contato."""
    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant       = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="followups")
    contact      = models.ForeignKey("contacts.Contact", on_delete=models.CASCADE, related_name="followups")
    conversation = models.ForeignKey("conversations.Conversation", on_delete=models.SET_NULL,
                                     null=True, blank=True, related_name="followups")
    session      = models.ForeignKey("channels_wa.WhatsAppSession", on_delete=models.SET_NULL,
                                     null=True, related_name="followups")
    message      = models.TextField(_("mensagem"))
    scheduled_at = models.DateTimeField(_("enviar em"))
    status       = models.CharField(_("status"), max_length=20, choices=FollowUpStatus.choices,
                                    default=FollowUpStatus.PENDING)
    created_by   = models.ForeignKey("accounts.User", on_delete=models.SET_NULL,
                                     null=True, related_name="followups")

    class Meta:
        verbose_name = _("Follow-up")
        verbose_name_plural = _("Follow-ups")
        ordering = ["scheduled_at"]

    def __str__(self):
        return f"Follow-up → {self.contact.display_name} em {self.scheduled_at:%d/%m/%Y %H:%M}"
