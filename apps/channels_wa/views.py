"""
Views do app channels_wa.

- webhook_receiver: recebe eventos da uazapiGO v2.0
- sessions_list / session_reconnect / session_status / session_disconnect:
  gerenciamento de sessões WhatsApp pelo painel
"""
import json
import logging
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseForbidden, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.shortcuts import get_object_or_404, render, redirect
from django.conf import settings

from apps.tenants.models import Tenant
from .models import WhatsAppSession, SessionStatus
from .uazapi import UazAPIClient, UazAPIError, create_instance

logger = logging.getLogger(__name__)

# Eventos que processamos
HANDLED_EVENTS = {"messages", "connection"}


def _fix_encoding(text: str) -> str:
    """
    Corrige double-encoding Latin-1/UTF-8 que o UazAPI às vezes envia.

    O Baileys (lib interna) às vezes interpreta os bytes UTF-8 do WhatsApp
    como Latin-1 antes de embutir no JSON, resultando em strings como
    "OlÃ¡" em vez de "Olá".  Revertemos codificando de volta para Latin-1
    (recuperando os bytes UTF-8 originais) e então decodificando como UTF-8.
    Se o texto já estiver correto, o try/except retorna o original.
    """
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text

# Tipos de mensagem que contêm mídia (sem texto)
MEDIA_TYPES = {"image", "video", "audio", "ptt", "document", "sticker"}


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

    if event == "connection":
        _handle_connection_event(session, payload)
    else:
        _handle_message_event(tenant, session, payload)

    return JsonResponse({"ok": True})


def _handle_connection_event(session, payload: dict):
    """
    Trata eventos de conexão/desconexão da instância.
    Quando conectado, dispara sync do histórico em background.
    """
    from .tasks import sync_session_history
    from .models import SessionStatus

    data = payload.get("data", {})
    status = (data.get("status") or data.get("state") or "").lower()

    logger.info("Evento de conexão | session=%s status=%s", session.id, status)

    if status in ("connected", "open"):
        session.status = SessionStatus.CONNECTED
        session.save(update_fields=["status"])
        # Dispara sincronização de histórico em background
        sync_session_history.delay(session_id=str(session.id))
        logger.info("Sync de histórico agendado | session=%s", session.id)

    elif status in ("disconnected", "close", "logout"):
        session.status = SessionStatus.DISCONNECTED
        session.save(update_fields=["status"])

    elif status in ("connecting", "qr"):
        session.status = SessionStatus.CONNECTING
        session.save(update_fields=["status"])


def _handle_message_event(tenant, session, payload: dict):
    """Extrai dados do payload v2.0 e aciona a lógica de processamento."""
    from .tasks import schedule_message_processing, schedule_media_processing

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

    msg_type: str = data.get("messageType", "")
    push_name: str = _fix_encoding(data.get("senderName", ""))
    wa_message_id: str = data.get("messageid", "")
    text: str = _fix_encoding(data.get("text", "").strip())

    # ── Roteamento por tipo ──────────────────────────────────────────
    if text:
        # Mensagem de texto normal → buffer de concatenação
        logger.info(
            "Webhook v2.0 | tenant=%s | phone=%s | tipo=%s | msg=%.80s",
            tenant.slug, phone, msg_type, text,
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

    elif msg_type in MEDIA_TYPES and wa_message_id:
        # Mensagem de mídia sem texto → download assíncrono
        logger.info(
            "Webhook v2.0 | tenant=%s | phone=%s | mídia=%s | id=%s",
            tenant.slug, phone, msg_type, wa_message_id,
        )
        schedule_media_processing(
            tenant_id=str(tenant.id),
            session_id=str(session.id),
            phone=phone,
            push_name=push_name,
            wa_message_id=wa_message_id,
            media_type=msg_type,
        )

    else:
        logger.debug(
            "Mensagem sem texto nem mídia reconhecida (tipo=%s) de %s — ignorando.",
            msg_type, phone,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Gerenciamento de sessões WhatsApp pelo painel
# ──────────────────────────────────────────────────────────────────────────────


@login_required
def sessions_list(request):
    """Página de gerenciamento da sessão WhatsApp do tenant."""
    tenant = request.tenant
    if not tenant:
        return redirect("tenants:onboarding")
    session = tenant.wa_sessions.filter(is_active=True).first()
    return render(request, "channels_wa/sessions.html", {"session": session})


@login_required
def session_reconnect(request):
    """
    HTMX: cria ou reconecta a sessão WhatsApp e retorna o partial com QR code.
    GET — acionado pelo botão 'Conectar' ou 'Reconectar' na página de sessões.
    """
    tenant = request.tenant
    if not tenant:
        return HttpResponseForbidden("Sem tenant.")

    session = tenant.wa_sessions.filter(is_active=True).first()

    if not session:
        instance_name = f"{tenant.slug}-wa"
        try:
            data = create_instance(instance_name)
            session = WhatsAppSession.objects.create(
                tenant=tenant,
                name=f"WhatsApp — {tenant.name}",
                instance_id=data["name"],
                token=data["token"],
            )
            webhook_url = (
                f"{settings.APP_BASE_URL.rstrip('/')}"
                f"/webhook/{tenant.slug}/{session.instance_id}/"
            )
            client = UazAPIClient(session.instance_id, session.token)
            client.set_webhook(webhook_url)
        except UazAPIError as exc:
            return render(request, "channels_wa/_session_qr.html", {
                "status": "error",
                "error": str(exc),
            })

    client = UazAPIClient(session.instance_id, session.token)
    try:
        resp = client.connect()
        instance_data = resp.get("instance", {})
        status = instance_data.get("status", "connecting")
        qr_code = instance_data.get("qrcode", "")
    except UazAPIError as exc:
        return render(request, "channels_wa/_session_qr.html", {
            "status": "error",
            "error": str(exc),
        })

    return render(request, "channels_wa/_session_qr.html", {
        "status": status,
        "qr_code": qr_code,
        "session": session,
    })


@login_required
def session_status(request):
    """HTMX: polling de status da sessão (every 3s)."""
    tenant = request.tenant
    if not tenant:
        return HttpResponse("", status=204)

    session = tenant.wa_sessions.filter(is_active=True).first()
    if not session:
        return render(request, "channels_wa/_session_qr.html", {"status": "no_session"})

    client = UazAPIClient(session.instance_id, session.token)
    try:
        resp = client.get_status()
        instance_data = resp.get("instance", {})
        status = instance_data.get("status", "disconnected")
        qr_code = instance_data.get("qrcode", "")

        if status in ("connected", "open"):
            session.status = SessionStatus.CONNECTED
            session.phone_number = instance_data.get("profileNumber", "")
            session.save(update_fields=["status", "phone_number"])
            status = "connected"
    except UazAPIError:
        status = "error"
        qr_code = ""

    return render(request, "channels_wa/_session_qr.html", {
        "status": status,
        "qr_code": qr_code,
        "session": session,
    })


@login_required
@require_POST
def session_disconnect(request):
    """POST: desconecta a sessão WhatsApp atual."""
    tenant = request.tenant
    if not tenant:
        return redirect("tenants:onboarding")

    session = tenant.wa_sessions.filter(is_active=True).first()
    if session:
        try:
            client = UazAPIClient(session.instance_id, session.token)
            client.disconnect()
        except UazAPIError:
            pass
        session.status = SessionStatus.DISCONNECTED
        session.save(update_fields=["status"])

    return redirect("channels_wa:sessions")
