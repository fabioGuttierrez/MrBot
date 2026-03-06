"""
Bot Engine — processa mensagens de entrada e gera respostas.

Fluxo de decisão:
  1. Executa o Flow Builder (se o bot tiver flow ativo)
     • "handled"        → flow respondeu, nada mais a fazer
     • "transfer_human" → conversa transferida, para aqui
     • "end"            → conversa encerrada, para aqui
     • "openai"         → flow delegou para IA → segue para passo 2
     • "no_flow"        → bot sem flow → vai direto para passo 2
  2. OpenAI GPT (chat completion com system prompt + histórico)
  3. Detecta intenção de transferência na resposta da IA
  4. Salva e envia resposta, atualiza contexto
"""
import logging
from django.utils import timezone

logger = logging.getLogger(__name__)

TRANSFER_TRIGGERS = [
    "vou te conectar com um especialista",
    "vou te transferir",
    "um especialista irá atendê-lo",
    "transferindo para atendente",
]


def process_message(*, conversation, message) -> None:
    """
    Ponto de entrada do bot engine.
    Chamado pela Celery task após a concatenação das mensagens.
    """
    from apps.conversations.models import ConversationStatus

    bot = conversation.bot
    if not bot or not bot.is_active:
        logger.warning("Conversa %s sem bot ativo — ignorada.", conversation.id)
        return

    try:
        # ── Passo 1: executa o Flow Builder ────────────────────────────────
        from apps.flows.engine import run_flow
        flow_outcome = run_flow(
            conversation=conversation,
            message_text=message.content,
        )

        # Flow resolveu tudo — não precisa chamar o OpenAI
        if flow_outcome in ("handled", "transfer_human", "end"):
            return

        # ── Passo 2: OpenAI (outcome == "openai" ou "no_flow") ─────────────
        _run_openai(conversation, message)

    except Exception as exc:
        logger.exception("Erro no bot engine | conversa=%s", conversation.id)


def _run_openai(conversation, message) -> None:
    """Chama o OpenAI e envia a resposta."""
    from apps.conversations.models import Message, MessageDirection, ConversationStatus
    from apps.channels_wa.uazapi import get_client_for_session
    from .openai_service import chat_completion

    bot = conversation.bot
    tenant = conversation.tenant

    system_prompt = bot.build_system_prompt(company_name=tenant.name)
    history: list[dict] = conversation.context or []

    reply, updated_history = chat_completion(
        system_prompt=system_prompt,
        history=history,
        user_message=message.content,
        model=bot.model,
        temperature=bot.temperature,
        max_tokens=bot.max_tokens,
    )

    wants_transfer = _check_transfer_intent(reply)

    out_message = Message.objects.create(
        conversation=conversation,
        direction=MessageDirection.OUT,
        content=reply,
    )

    try:
        client = get_client_for_session(conversation.session)
        client.send_text_with_delay(
            phone=conversation.contact.phone,
            message=reply,
            delay=1200,
        )
    except Exception as exc:
        logger.error("Falha ao enviar via UazAPI: %s", exc)

    _notify_websocket(conversation, out_message)

    update_fields = ["context", "last_message_at"]
    conversation.context = updated_history
    conversation.last_message_at = timezone.now()

    if wants_transfer:
        logger.info("OpenAI indicou transferência | conversa=%s", conversation.id)
        conversation.status = ConversationStatus.PENDING
        conversation.unread_count += 1
        update_fields += ["status", "unread_count"]

    conversation.save(update_fields=update_fields)


def _check_transfer_intent(reply: str) -> bool:
    """Verifica se a resposta do bot indica transferência para humano."""
    reply_lower = reply.lower()
    return any(trigger in reply_lower for trigger in TRANSFER_TRIGGERS)


def _notify_websocket(conversation, message) -> None:
    """Envia a mensagem de saída do bot para o grupo WebSocket."""
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
                    "timestamp": message.created.isoformat(),
                    "is_concatenated": False,
                },
            },
        )
    except Exception:
        pass
