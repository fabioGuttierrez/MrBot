import logging
from threading import Thread
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.db.models import Q
from django.utils import timezone

from apps.conversations.models import Conversation, Message, MessageDirection, ConversationStatus
from apps.contacts.models import Contact

logger = logging.getLogger(__name__)

FILTERS = [
    ("Todos", "all"),
    ("Bot", "bot"),
    ("Humano", "human"),
    ("Pendente", "pending"),
    ("Encerrado", "closed"),
]


def _get_conversations(tenant, status_filter="all", q=""):
    qs = (
        Conversation.objects
        .filter(tenant=tenant)
        .select_related("contact", "bot", "assigned_to")
        .order_by("-last_message_at")
    )
    if status_filter and status_filter != "all":
        qs = qs.filter(status=status_filter)
    if q:
        qs = qs.filter(
            Q(contact__name__icontains=q) | Q(contact__phone__icontains=q)
        )
    return qs[:60]


@login_required
def index(request):
    """Página principal do inbox."""
    tenant = request.tenant
    if not tenant:
        return redirect("tenants:onboarding")

    status_filter = request.GET.get("status", "all")
    conversations = _get_conversations(tenant, status_filter)

    return render(request, "inbox/index.html", {
        "filters": FILTERS,
        "active_filter": status_filter,
        "conversations": conversations,
        "conversation": None,
    })


@login_required
def conversation_detail(request, conversation_id):
    """Abre a inbox com uma conversa selecionada no painel direito."""
    tenant = request.tenant
    if not tenant:
        return redirect("tenants:onboarding")

    conversation = get_object_or_404(Conversation, id=conversation_id, tenant=tenant)

    # Zera unread ao abrir
    if conversation.unread_count > 0:
        conversation.unread_count = 0
        conversation.save(update_fields=["unread_count"])

    # Marca como lido no WhatsApp (background, não bloqueia a resposta)
    if conversation.session:
        _mark_read_on_whatsapp(conversation.session, conversation.contact.phone)

    messages_qs = (
        conversation.messages
        .order_by("created")
        .only("id", "direction", "content", "created", "is_concatenated", "media_url", "media_type")
    )

    status_filter = request.GET.get("status", "all")
    conversations = _get_conversations(tenant, status_filter)

    is_htmx = request.headers.get("HX-Request")
    if is_htmx:
        return render(request, "inbox/_chat_window.html", {
            "conversation": conversation,
            "messages": messages_qs,
        })

    return render(request, "inbox/index.html", {
        "filters": FILTERS,
        "active_filter": status_filter,
        "conversations": conversations,
        "conversation": conversation,
        "messages": messages_qs,
    })


@login_required
def conversation_list(request):
    """Retorna lista parcial de conversas (HTMX polling)."""
    tenant = request.tenant
    if not tenant:
        return JsonResponse({"error": "no tenant"}, status=400)

    status_filter = request.GET.get("status", "all")
    q = request.GET.get("q", "").strip()
    conversations = _get_conversations(tenant, status_filter, q)

    return render(request, "inbox/_conversation_list.html", {
        "conversations": conversations,
        "active_filter": status_filter,
    })


@login_required
def search(request):
    """Busca conversas por nome/telefone (HTMX)."""
    return conversation_list(request)


@login_required
@require_POST
def send_message(request, conversation_id):
    """Agente humano envia mensagem manualmente."""
    tenant = request.tenant
    conversation = get_object_or_404(Conversation, id=conversation_id, tenant=tenant)

    text = request.POST.get("text", "").strip()
    if not text:
        return JsonResponse({"ok": False, "error": "Mensagem vazia."}, status=400)

    # Salva a mensagem
    msg = Message.objects.create(
        conversation=conversation,
        direction=MessageDirection.OUT,
        content=text,
    )

    conversation.last_message_at = timezone.now()
    conversation.save(update_fields=["last_message_at"])

    # Envia via Evolution API
    try:
        from apps.channels_wa.evolution import get_client_for_session
        client = get_client_for_session(conversation.session)
        client.send_text(
            phone=conversation.contact.phone,
            message=text,
            track_id=str(msg.id),
        )
    except Exception as exc:
        logger.error("Falha ao enviar msg humana via Evolution API: %s", exc)

    # Notifica WebSocket
    _push_ws(conversation, msg)

    if request.headers.get("HX-Request"):
        return render(request, "inbox/_message_bubble.html", {
            "message": msg,
        })
    return JsonResponse({"ok": True, "message_id": str(msg.id)})


@login_required
@require_POST
def takeover(request, conversation_id):
    """Agente assume a conversa do bot."""
    tenant = request.tenant
    conversation = get_object_or_404(Conversation, id=conversation_id, tenant=tenant)
    conversation.status = ConversationStatus.HUMAN
    conversation.assigned_to = request.user
    conversation.save(update_fields=["status", "assigned_to"])

    if request.headers.get("HX-Request"):
        return render(request, "inbox/_conversation_status_badge.html", {"conversation": conversation})
    return JsonResponse({"ok": True, "status": conversation.status})


@login_required
@require_POST
def release(request, conversation_id):
    """Devolve a conversa para o bot."""
    tenant = request.tenant
    conversation = get_object_or_404(Conversation, id=conversation_id, tenant=tenant)
    conversation.status = ConversationStatus.BOT
    conversation.assigned_to = None
    conversation.save(update_fields=["status", "assigned_to"])

    if request.headers.get("HX-Request"):
        return render(request, "inbox/_conversation_status_badge.html", {"conversation": conversation})
    return JsonResponse({"ok": True, "status": conversation.status})


@login_required
@require_POST
def close_conversation(request, conversation_id):
    """Encerra a conversa."""
    tenant = request.tenant
    conversation = get_object_or_404(Conversation, id=conversation_id, tenant=tenant)
    conversation.status = ConversationStatus.CLOSED
    conversation.save(update_fields=["status"])
    return redirect("inbox:index")


def _mark_read_on_whatsapp(session, phone: str) -> None:
    """Marca mensagens como lidas no WhatsApp em background (não bloqueia a view)."""
    def _run():
        try:
            from apps.channels_wa.evolution import get_client_for_session
            client = get_client_for_session(session)
            chatid = f"{phone}@s.whatsapp.net"
            client.mark_messages_read(chatid)
        except Exception as exc:
            logger.debug("Falha ao marcar como lido no WhatsApp: %s", exc)

    Thread(target=_run, daemon=True).start()


def _push_ws(conversation, message):
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        layer = get_channel_layer()
        async_to_sync(layer.group_send)(
            f"chat_{conversation.id}",
            {
                "type": "chat_message",
                "message": {
                    "id": str(message.id),
                    "direction": message.direction,
                    "content": message.content,
                    "media_url": message.media_url or "",
                    "media_type": message.media_type or "",
                    "timestamp": message.created.isoformat(),
                    "is_concatenated": False,
                },
            },
        )
    except Exception:
        pass
