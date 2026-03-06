"""
Tasks Celery do app channels_wa.

Fluxo de concatenação de mensagens:
─────────────────────────────────────────────────────────────
1. Webhook recebe msg → chama schedule_message_processing()
2. schedule_message_processing():
   a. Appenda o texto no buffer Redis  (lista: concat_buf:{tid}:{phone})
   b. Revoga task anterior se existir   (chave: concat_tid:{tid}:{phone})
   c. Agenda nova task com countdown = concat_delay (segundos)
   d. Salva o novo task_id no Redis
3. Se nova msg chegar dentro do delay → volta para o passo 2
4. Após o delay sem novas msgs → process_concatenated_message() executa:
   a. Lê e apaga o buffer do Redis
   b. Concatena os textos com "\n" (quebra de linha)
   c. Resolve Contact (get_or_create)
   d. Resolve Conversation (get_or_create)
   e. Persiste Message no banco
   f. Aciona o bot engine
─────────────────────────────────────────────────────────────
"""
import logging
import redis as redis_lib
from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)

# Prefixos de chave Redis
_BUF_KEY = "concat_buf:{tid}:{phone}"   # lista de textos pendentes (tipo List)
_TASK_KEY = "concat_tid:{tid}:{phone}"  # task_id da task agendada  (tipo String)
_TTL = 600  # TTL das chaves Redis (10 min) — segurança contra vazamentos


def _redis() -> redis_lib.Redis:
    """Retorna conexão direta ao Redis (decode_responses para strings Python)."""
    return redis_lib.from_url(settings.REDIS_URL, decode_responses=True)


# ---------------------------------------------------------------------------
# Função pública chamada pelo webhook (síncrona, roda no processo Django)
# ---------------------------------------------------------------------------

def schedule_message_processing(
    *,
    tenant_id: str,
    session_id: str,
    phone: str,
    text: str,
    push_name: str,
    wa_message_id: str,
    concat_delay: int,
):
    """
    Registra a mensagem no buffer e (re)agenda a task de processamento.
    Chamada diretamente pelo webhook — NÃO é uma Celery task.
    """
    buf_key = _BUF_KEY.format(tid=tenant_id, phone=phone)
    task_key = _TASK_KEY.format(tid=tenant_id, phone=phone)

    r = _redis()

    # 1. Adiciona atomicamente o texto ao buffer Redis (rpush = atômico)
    buf_size = r.rpush(buf_key, text)
    r.expire(buf_key, _TTL)

    # 2. Revoga task anterior para este contato (Fix 2: via celery_app.control)
    old_task_id = r.get(task_key)
    if old_task_id:
        try:
            from config.celery import app as celery_app
            celery_app.control.revoke(old_task_id, terminate=False)
        except Exception:
            pass  # não bloqueia se falhar

    # 3. Agenda nova task com countdown = concat_delay
    task = process_concatenated_message.apply_async(
        kwargs={
            "tenant_id": tenant_id,
            "session_id": session_id,
            "phone": phone,
            "push_name": push_name,
            "wa_message_id": wa_message_id,
            "buf_key": buf_key,
            "task_key": task_key,
        },
        countdown=concat_delay,
    )

    # 4. Persiste o novo task_id no Redis (sobrescreve o anterior)
    r.set(task_key, task.id, ex=_TTL)

    logger.debug(
        "Msg registrada no buffer | tenant=%s phone=%s delay=%ss task=%s buf_size=%d",
        tenant_id, phone, concat_delay, task.id, buf_size,
    )


# ---------------------------------------------------------------------------
# Task Celery: executada após o delay de concatenação
# ---------------------------------------------------------------------------

@shared_task(bind=True, name="channels_wa.process_concatenated_message", max_retries=3)
def process_concatenated_message(
    self,
    *,
    tenant_id: str,
    session_id: str,
    phone: str,
    push_name: str,
    wa_message_id: str,
    buf_key: str,
    task_key: str,
):
    """
    Processa as mensagens concatenadas de um contato.
    Executada pelo Celery após o delay configurado no tenant.
    """
    try:
        r = _redis()

        # 1. Lê e apaga o buffer atomicamente via pipeline (Fix 3: sem race condition)
        with r.pipeline() as pipe:
            pipe.lrange(buf_key, 0, -1)
            pipe.delete(buf_key, task_key)
            results = pipe.execute()

        buf: list[str] = results[0]

        if not buf:
            logger.warning(
                "Buffer vazio para phone=%s tenant=%s — task ignorada.", phone, tenant_id
            )
            return

        # 2. Concatena mensagens com quebra de linha
        concatenated_text = "\n".join(buf)
        is_concatenated = len(buf) > 1

        logger.info(
            "Processando %d msg(s) de phone=%s tenant=%s: %.100s",
            len(buf), phone, tenant_id, concatenated_text,
        )

        # 3. Resolve entidades do banco de dados
        from apps.tenants.models import Tenant
        from apps.channels_wa.models import WhatsAppSession
        from apps.contacts.models import Contact
        from apps.conversations.models import (
            Conversation,
            ConversationStatus,
            Message,
            MessageDirection,
        )
        from django.utils import timezone

        tenant = Tenant.objects.get(id=tenant_id)
        session = WhatsAppSession.objects.get(id=session_id)

        # 4. Get or create Contact
        contact, _ = Contact.objects.get_or_create(
            tenant=tenant,
            phone=phone,
            defaults={"name": push_name},
        )
        # Atualiza nome se ainda não tinha
        if push_name and not contact.name:
            contact.name = push_name
            contact.save(update_fields=["name"])

        # 5. Get or create Conversation ativa (bot ou humano)
        conversation = (
            Conversation.objects.filter(
                tenant=tenant,
                contact=contact,
                session=session,
            )
            .exclude(status=ConversationStatus.CLOSED)
            .order_by("-created")
            .first()
        )

        if not conversation:
            # Acha o bot padrão do tenant (primeiro ativo)
            from apps.bots.models import Bot
            default_bot = Bot.objects.filter(tenant=tenant, is_active=True).first()

            conversation = Conversation.objects.create(
                tenant=tenant,
                contact=contact,
                session=session,
                bot=default_bot,
                status=ConversationStatus.BOT,
            )

        # 6. Salva mensagem no banco
        message = Message.objects.create(
            conversation=conversation,
            direction=MessageDirection.IN,
            content=concatenated_text,
            is_concatenated=is_concatenated,
            wa_message_id=wa_message_id,
        )

        # Atualiza timestamp e contador da conversa
        conversation.last_message_at = timezone.now()
        conversation.unread_count += 1
        conversation.save(update_fields=["last_message_at", "unread_count"])

        # 7. Notifica o WebSocket (inbox em tempo real)
        _notify_websocket(conversation, message)

        # 8. Aciona o bot engine (somente se a conversa ainda está no bot)
        if conversation.status == ConversationStatus.BOT and conversation.bot:
            from apps.bots.engine import process_message
            process_message(conversation=conversation, message=message)

    except Exception as exc:
        logger.exception(
            "Erro ao processar mensagens concatenadas | phone=%s tenant=%s",
            phone, tenant_id,
        )
        raise self.retry(exc=exc, countdown=5)


def _notify_websocket(conversation, message):
    """Envia update para o grupo WebSocket da conversa (não bloqueia)."""
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync

        layer = get_channel_layer()
        group_name = f"chat_{conversation.id}"

        async_to_sync(layer.group_send)(
            group_name,
            {
                "type": "chat_message",
                "message": {
                    "id": str(message.id),
                    "direction": message.direction,
                    "content": message.content,
                    "timestamp": message.created.isoformat(),
                    "is_concatenated": message.is_concatenated,
                },
            },
        )
    except Exception:
        pass  # WebSocket é best-effort; não quebra o fluxo se falhar
