"""
Webhook receiver para eventos da uazapiGO v2.0.

Payload recebido (event=messages):
{
  "event": "messages",
  "instance": "instance_id",
  "data": {
    "id": "r1a2b3c",
    "messageid": "3EB0538DA65A59F6D8A251",
    "chatid": "5511999999999@s.whatsapp.net",
    "sender": "5511999999999@s.whatsapp.net",
    "senderName": "Nome Contato",
    "isGroup": false,
    "fromMe": false,
    "messageType": "conversation",
    "text": "Olá!",
    "wasSentByApi": false,
    "messageTimestamp": 1700000000
  }
}
"""
import json
import logging
from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.shortcuts import get_object_or_404
from django.conf import settings

from apps.tenants.models import Tenant
from .models import WhatsAppSession

logger = logging.getLogger(__name__)

# Eventos que processamos — v2.0 usa "messages" (sem sufixo .upsert)
HANDLED_EVENTS = {"messages"}


@csrf_exempt
@require_POST
def webhook_receiver(request, tenant_slug: str, instance_id: str):
    """
    Recebe eventos da uazapiGO v2.0.
    URL: /webhook/<tenant_slug>/<instance_id>/

    O instance_id na URL serve para roteamento e validação.
    O secret é validado via header X-Webhook-Secret.
    """
    # Validação do secret
    secret = request.headers.get("X-Webhook-Secret", "")
    if settings.WEBHOOK_SECRET and secret != settings.WEBHOOK_SECRET:
        logger.warning("Webhook secret inválido para tenant=%s", tenant_slug)
        return HttpResponseForbidden("Invalid secret")

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid json"}, status=400)

    event = payload.get("event", "")

    # Ignora eventos não tratados silenciosamente
    if event not in HANDLED_EVENTS:
        return JsonResponse({"ok": True, "event": event, "handled": False})

    # Valida que o instance_id do payload bate com a URL
    payload_instance = payload.get("instance", "")
    if payload_instance and payload_instance != instance_id:
        logger.warning(
            "instance_id divergente: URL=%s payload=%s",
            instance_id, payload_instance,
        )
        return JsonResponse({"error": "instance mismatch"}, status=400)

    tenant = get_object_or_404(Tenant, slug=tenant_slug, is_active=True)
    session = get_object_or_404(
        WhatsAppSession,
        tenant=tenant,
        instance_id=instance_id,
        is_active=True,
    )

    _handle_message_event(tenant, session, payload)

    return JsonResponse({"ok": True})


def _handle_message_event(tenant, session, payload: dict):
    """Extrai dados do payload v2.0 e aciona a lógica de concatenação."""
    from .tasks import schedule_message_processing

    data = payload.get("data", {})

    # ── Filtros obrigatórios ──────────────────────────────────────────
    # Ignora mensagens enviadas pelo próprio número
    if data.get("fromMe", False):
        return

    # Ignora mensagens enviadas via API (evita loops)
    if data.get("wasSentByApi", False):
        return

    # Ignora mensagens de grupos (chatid termina em @g.us)
    chat_id: str = data.get("chatid", "")
    if chat_id.endswith("@g.us") or data.get("isGroup", False):
        return

    # ── Extração dos campos ──────────────────────────────────────────
    # Extrai número do chatid: "5511999999999@s.whatsapp.net" → "5511999999999"
    phone = chat_id.split("@")[0]
    if not phone or not phone.isdigit():
        logger.debug("chatid inválido ou não numérico: %s", chat_id)
        return

    text: str = data.get("text", "").strip()
    if not text:
        # Tipos sem texto (áudio, imagem, etc.) — ignora por enquanto
        msg_type = data.get("messageType", "desconhecido")
        logger.debug("Mensagem sem texto (%s) de %s, ignorando.", msg_type, phone)
        return

    push_name: str = data.get("senderName", "")
    wa_message_id: str = data.get("messageid", "")

    logger.info(
        "Webhook v2.0 | tenant=%s | phone=%s | tipo=%s | msg=%.80s",
        tenant.slug, phone, data.get("messageType", "?"), text,
    )

    schedule_message_processing(
        tenant_id=str(tenant.id),
        session_id=str(session.id),
        phone=phone,
        text=text,
        push_name=push_name,
        wa_message_id=wa_message_id,
        concat_delay=tenant.message_concat_delay,
    )
