import uuid
from django.db import models
from django.utils.translation import gettext_lazy as _
from django_extensions.db.models import TimeStampedModel


class ConversationStatus(models.TextChoices):
    BOT = "bot", _("Bot")
    HUMAN = "human", _("Humano")
    PENDING = "pending", _("Pendente")
    CLOSED = "closed", _("Encerrado")


class MessageDirection(models.TextChoices):
    IN = "in", _("Entrada")
    OUT = "out", _("Saída")


class Conversation(TimeStampedModel):
    """Conversa entre um contato e o tenant."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="conversations")
    contact = models.ForeignKey("contacts.Contact", on_delete=models.CASCADE, related_name="conversations")
    session = models.ForeignKey("channels_wa.WhatsAppSession", on_delete=models.SET_NULL, null=True, related_name="conversations")
    bot = models.ForeignKey("bots.Bot", on_delete=models.SET_NULL, null=True, blank=True, related_name="conversations")
    assigned_to = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_conversations")
    status = models.CharField(_("status"), max_length=20, choices=ConversationStatus.choices, default=ConversationStatus.BOT)
    current_flow_node = models.CharField(_("nó atual do flow"), max_length=100, blank=True)
    context = models.JSONField(_("contexto OpenAI"), default=list, blank=True)  # histórico de mensagens OpenAI
    unread_count = models.PositiveIntegerField(_("não lidas"), default=0)
    last_message_at = models.DateTimeField(_("última mensagem"), null=True, blank=True)

    class Meta:
        verbose_name = _("Conversa")
        verbose_name_plural = _("Conversas")
        ordering = ["-last_message_at"]

    def __str__(self):
        return f"{self.contact} [{self.status}]"


class Message(TimeStampedModel):
    """Mensagem trocada em uma conversa."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    direction = models.CharField(_("direção"), max_length=5, choices=MessageDirection.choices)
    content = models.TextField(_("conteúdo"))
    is_concatenated = models.BooleanField(_("concatenada"), default=False)
    wa_message_id = models.CharField(_("ID WhatsApp"), max_length=200, blank=True)
    media_url = models.URLField(_("URL mídia"), blank=True)
    media_type = models.CharField(_("tipo mídia"), max_length=20, blank=True)

    class Meta:
        verbose_name = _("Mensagem")
        verbose_name_plural = _("Mensagens")
        ordering = ["created"]

    def __str__(self):
        return f"[{self.direction}] {self.content[:50]}"
