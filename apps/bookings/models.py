import uuid
from django.db import models
from django.utils.translation import gettext_lazy as _
from django_extensions.db.models import TimeStampedModel


class BookingType(models.TextChoices):
    FULL_DAY = "full_day", _("Dia inteiro")
    TIME_SLOT = "time_slot", _("Horário específico")


class BookingStatus(models.TextChoices):
    PENDING = "pending", _("Pendente")
    CONFIRMED = "confirmed", _("Confirmado")
    CANCELLED = "cancelled", _("Cancelado")


class Resource(TimeStampedModel):
    """
    Recurso reservável de um tenant.

    Exemplos:
      - Empresa de eventos: "Plataforma 360 #1" (full_day, categoria: plataforma_360)
      - Barbearia: "Cadeira do João" (time_slot, 30min, 09h-18h)
      - Locadora: "Espelho Mágico" (full_day, max_bookings_per_day=1)
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.CASCADE, related_name="resources"
    )
    name = models.CharField(_("nome"), max_length=100)
    category = models.CharField(
        _("categoria"),
        max_length=100,
        help_text=_("Slug para agrupar recursos similares (ex: plataforma_360, cadeira)"),
    )
    booking_type = models.CharField(
        _("tipo de reserva"),
        max_length=20,
        choices=BookingType.choices,
        default=BookingType.FULL_DAY,
    )
    max_bookings_per_day = models.PositiveIntegerField(
        _("máx. reservas por dia"),
        default=1,
        help_text=_("Quantos agendamentos simultâneos este recurso aceita no mesmo dia"),
    )
    # Campos exclusivos para time_slot
    slot_duration_minutes = models.PositiveIntegerField(
        _("duração do slot (min)"), null=True, blank=True,
        help_text=_("Apenas para tipo Horário específico"),
    )
    working_hours_start = models.TimeField(
        _("início do expediente"), null=True, blank=True,
    )
    working_hours_end = models.TimeField(
        _("fim do expediente"), null=True, blank=True,
    )
    is_active = models.BooleanField(_("ativo"), default=True)
    description = models.TextField(_("descrição"), blank=True)

    class Meta:
        verbose_name = _("Recurso")
        verbose_name_plural = _("Recursos")
        ordering = ["tenant", "category", "name"]
        unique_together = [("tenant", "name")]

    def __str__(self):
        return f"{self.name} ({self.tenant.name})"


class Booking(TimeStampedModel):
    """Reserva de um recurso por um contato em uma data."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.CASCADE, related_name="bookings"
    )
    resource = models.ForeignKey(
        Resource, on_delete=models.CASCADE, related_name="bookings"
    )
    contact = models.ForeignKey(
        "contacts.Contact",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="bookings",
    )
    conversation = models.ForeignKey(
        "conversations.Conversation",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="bookings",
    )
    event_date = models.DateField(_("data do evento"))
    start_time = models.TimeField(_("horário início"), null=True, blank=True)
    end_time = models.TimeField(_("horário fim"), null=True, blank=True)
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=BookingStatus.choices,
        default=BookingStatus.PENDING,
    )
    client_name = models.CharField(
        _("nome do cliente"), max_length=200, blank=True,
        help_text=_("Preenchido quando não há Contact vinculado"),
    )
    notes = models.TextField(_("observações"), blank=True)

    class Meta:
        verbose_name = _("Reserva")
        verbose_name_plural = _("Reservas")
        ordering = ["-event_date", "resource"]

    def __str__(self):
        name = self.client_name or (self.contact.name if self.contact else "—")
        return f"{self.resource.name} | {self.event_date} | {name}"
