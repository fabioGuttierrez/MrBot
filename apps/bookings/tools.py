"""
Ferramentas de agendamento expostas ao GPT-4o via function calling.

Cada ferramenta tem:
  - Um schema OpenAI (BOOKING_TOOLS) declarado aqui
  - Uma função Python correspondente
  - Um dispatcher criado por make_tool_executor (recebe contexto da conversa)
"""
import json
import logging
from datetime import date as date_type

logger = logging.getLogger(__name__)

# ── Schemas OpenAI ────────────────────────────────────────────────────────────

BOOKING_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "check_availability",
            "description": (
                "Verifica se recursos estão disponíveis em uma determinada data. "
                "Use sempre que o cliente informar uma data de evento ou pedir disponibilidade."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Data do evento no formato YYYY-MM-DD",
                    },
                    "category": {
                        "type": "string",
                        "description": (
                            "Categoria do recurso desejado (ex: plataforma_360, espelho_magico). "
                            "Omita para verificar todos os recursos disponíveis."
                        ),
                    },
                    "resource_name": {
                        "type": "string",
                        "description": "Nome exato de um recurso específico. Omita para verificar a categoria inteira.",
                    },
                },
                "required": ["date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_booking",
            "description": (
                "Cria uma reserva pendente após o cliente confirmar interesse e a data estar disponível. "
                "Sempre confirme com o cliente antes de chamar esta função."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "resource_name": {
                        "type": "string",
                        "description": "Nome exato do recurso a reservar",
                    },
                    "date": {
                        "type": "string",
                        "description": "Data do evento no formato YYYY-MM-DD",
                    },
                    "client_name": {
                        "type": "string",
                        "description": "Nome do cliente",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Observações sobre o evento (tipo, local, etc.)",
                    },
                },
                "required": ["resource_name", "date"],
            },
        },
    },
]


# ── Funções Python ─────────────────────────────────────────────────────────────

def check_availability(*, tenant_id, date: str, category: str = None, resource_name: str = None) -> dict:
    """Verifica disponibilidade de recursos para uma data."""
    from .models import Resource, Booking, BookingStatus

    try:
        event_date = date_type.fromisoformat(date)
    except ValueError:
        return {"error": f"Data inválida: '{date}'. Use o formato YYYY-MM-DD."}

    resources = Resource.objects.filter(tenant_id=tenant_id, is_active=True)
    if category:
        resources = resources.filter(category__iexact=category)
    if resource_name:
        resources = resources.filter(name__iexact=resource_name)

    if not resources.exists():
        return {"error": "Nenhum recurso encontrado com esses critérios."}

    results = []
    for resource in resources:
        booked_count = Booking.objects.filter(
            resource=resource,
            event_date=event_date,
            status__in=[BookingStatus.PENDING, BookingStatus.CONFIRMED],
        ).count()
        available_slots = resource.max_bookings_per_day - booked_count
        results.append({
            "resource": resource.name,
            "category": resource.category,
            "available": available_slots > 0,
            "available_slots": available_slots,
            "max_per_day": resource.max_bookings_per_day,
        })

    any_available = any(r["available"] for r in results)
    return {
        "date": event_date.strftime("%d/%m/%Y"),
        "any_available": any_available,
        "resources": results,
    }


def create_booking(
    *,
    tenant_id,
    resource_name: str,
    date: str,
    contact_id=None,
    conversation_id=None,
    client_name: str = "",
    notes: str = "",
) -> dict:
    """Cria uma reserva pendente para um recurso."""
    from .models import Resource, Booking, BookingStatus

    try:
        event_date = date_type.fromisoformat(date)
    except ValueError:
        return {"error": f"Data inválida: '{date}'. Use o formato YYYY-MM-DD."}

    try:
        resource = Resource.objects.get(
            tenant_id=tenant_id, name__iexact=resource_name, is_active=True
        )
    except Resource.DoesNotExist:
        return {"error": f"Recurso '{resource_name}' não encontrado."}
    except Resource.MultipleObjectsReturned:
        resource = Resource.objects.filter(
            tenant_id=tenant_id, name__iexact=resource_name, is_active=True
        ).first()

    booked_count = Booking.objects.filter(
        resource=resource,
        event_date=event_date,
        status__in=[BookingStatus.PENDING, BookingStatus.CONFIRMED],
    ).count()

    if booked_count >= resource.max_bookings_per_day:
        return {
            "error": (
                f"O recurso '{resource.name}' não tem disponibilidade para "
                f"{event_date.strftime('%d/%m/%Y')}."
            )
        }

    booking = Booking.objects.create(
        tenant_id=tenant_id,
        resource=resource,
        contact_id=contact_id,
        conversation_id=conversation_id,
        event_date=event_date,
        status=BookingStatus.PENDING,
        client_name=client_name,
        notes=notes,
    )

    return {
        "success": True,
        "booking_id": str(booking.id),
        "resource": resource.name,
        "date": event_date.strftime("%d/%m/%Y"),
        "status": "pending",
        "message": (
            f"Reserva criada para *{resource.name}* em {event_date.strftime('%d/%m/%Y')}. "
            "Aguardando confirmação da nossa equipe."
        ),
    }


# ── Dispatcher ─────────────────────────────────────────────────────────────────

def make_tool_executor(*, tenant_id, conversation_id=None, contact_id=None):
    """
    Retorna uma função dispatch(tool_name, arguments) com contexto da conversa embutido.
    Usada pelo openai_service para executar ferramentas durante o loop de function calling.
    """
    def execute(tool_name: str, arguments: dict) -> dict:
        logger.info("Tool call | tool=%s args=%s tenant=%s", tool_name, arguments, tenant_id)
        try:
            if tool_name == "check_availability":
                return check_availability(tenant_id=tenant_id, **arguments)
            elif tool_name == "create_booking":
                return create_booking(
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    contact_id=contact_id,
                    **arguments,
                )
            else:
                return {"error": f"Ferramenta desconhecida: '{tool_name}'"}
        except Exception as exc:
            logger.exception("Erro ao executar tool '%s': %s", tool_name, exc)
            return {"error": f"Erro interno ao executar '{tool_name}'."}

    return execute
