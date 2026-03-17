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
        contact, contact_created = Contact.objects.get_or_create(
            tenant=tenant,
            phone=phone,
            defaults={"name": push_name},
        )
        # Atualiza nome se ainda não tinha
        if push_name and not contact.name:
            contact.name = push_name
            contact.save(update_fields=["name"])

        # Auto-enrich: busca foto e nome do WhatsApp ao criar novo contato
        if contact_created:
            enrich_contact_from_whatsapp.apply_async(
                kwargs={"session_id": str(session.id), "contact_id": str(contact.id)},
                countdown=5,
            )

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
                    "media_url": message.media_url,
                    "media_type": message.media_type,
                    "timestamp": message.created.isoformat(),
                    "is_concatenated": message.is_concatenated,
                },
            },
        )
    except Exception:
        pass  # WebSocket é best-effort; não quebra o fluxo se falhar


# ---------------------------------------------------------------------------
# Mídia: agendamento + processamento
# ---------------------------------------------------------------------------

def schedule_media_processing(
    *,
    tenant_id: str,
    session_id: str,
    phone: str,
    push_name: str,
    wa_message_id: str,
    media_type: str,
):
    """Agenda o download e processamento de uma mensagem de mídia."""
    process_media_message.apply_async(
        kwargs={
            "tenant_id": tenant_id,
            "session_id": session_id,
            "phone": phone,
            "push_name": push_name,
            "wa_message_id": wa_message_id,
            "media_type": media_type,
        },
    )


@shared_task(bind=True, name="channels_wa.process_media_message", max_retries=3)
def process_media_message(
    self,
    *,
    tenant_id: str,
    session_id: str,
    phone: str,
    push_name: str,
    wa_message_id: str,
    media_type: str,
):
    """
    Baixa a mídia de uma mensagem recebida e persiste no banco.
    Suporta image, video, audio, ptt, document, sticker.
    """
    try:
        from apps.tenants.models import Tenant
        from apps.channels_wa.models import WhatsAppSession
        from apps.channels_wa.uazapi import get_client_for_session
        from apps.contacts.models import Contact
        from apps.conversations.models import (
            Conversation, ConversationStatus, Message, MessageDirection,
        )
        from apps.bots.models import Bot
        from django.utils import timezone

        tenant = Tenant.objects.get(id=tenant_id)
        session = WhatsAppSession.objects.get(id=session_id)
        client = get_client_for_session(session)

        # Download da mídia — retorna URL pública
        transcribe = media_type in ("audio", "ptt")
        try:
            result = client.download_message(
                wa_message_id,
                return_link=True,
                generate_mp3=True,
                transcribe=transcribe,
            )
            media_url = result.get("link") or result.get("url") or result.get("mediaUrl", "")
            transcription = result.get("transcription", "") if transcribe else ""
        except Exception as exc:
            logger.warning("Falha ao baixar mídia %s: %s", wa_message_id, exc)
            media_url = ""
            transcription = ""

        # Resolve Contact
        contact, _ = Contact.objects.get_or_create(
            tenant=tenant,
            phone=phone,
            defaults={"name": push_name},
        )
        if push_name and not contact.name:
            contact.name = push_name
            contact.save(update_fields=["name"])

        # Resolve Conversation ativa
        conversation = (
            Conversation.objects.filter(
                tenant=tenant, contact=contact, session=session,
            )
            .exclude(status=ConversationStatus.CLOSED)
            .order_by("-created")
            .first()
        )
        if not conversation:
            default_bot = Bot.objects.filter(tenant=tenant, is_active=True).first()
            conversation = Conversation.objects.create(
                tenant=tenant,
                contact=contact,
                session=session,
                bot=default_bot,
                status=ConversationStatus.BOT,
            )

        # Conteúdo: transcrição (se áudio) ou label do tipo
        LABELS = {
            "image": "📷 Imagem recebida",
            "video": "🎥 Vídeo recebido",
            "audio": "🎵 Áudio recebido",
            "ptt": "🎤 Áudio recebido",
            "document": "📄 Documento recebido",
            "sticker": "🎉 Figurinha recebida",
        }
        content = transcription or LABELS.get(media_type, "📎 Mídia recebida")

        message = Message.objects.create(
            conversation=conversation,
            direction=MessageDirection.IN,
            content=content,
            wa_message_id=wa_message_id,
            media_url=media_url,
            media_type=media_type,
        )

        conversation.last_message_at = timezone.now()
        conversation.unread_count += 1
        conversation.save(update_fields=["last_message_at", "unread_count"])

        _notify_websocket(conversation, message)

        # Aciona bot apenas para áudios transcritos (tem conteúdo de texto)
        if transcription and conversation.status == ConversationStatus.BOT and conversation.bot:
            from apps.bots.engine import process_message
            process_message(conversation=conversation, message=message)

    except Exception as exc:
        logger.exception("Erro ao processar mídia | wa_id=%s phone=%s", wa_message_id, phone)
        raise self.retry(exc=exc, countdown=10)


# ---------------------------------------------------------------------------
# Sincronização de histórico
# ---------------------------------------------------------------------------

@shared_task(bind=True, name="channels_wa.sync_session_history", max_retries=2)
def sync_session_history(self, *, session_id: str, max_chats: int = 30, messages_per_chat: int = 50):
    """
    Importa histórico de conversas ao conectar uma sessão WhatsApp.
    Busca os últimos N chats e suas mensagens via API do UazAPI.
    Evita duplicatas via wa_message_id.
    """
    import datetime
    try:
        from apps.channels_wa.models import WhatsAppSession
        from apps.channels_wa.uazapi import get_client_for_session
        from apps.tenants.models import Tenant
        from apps.contacts.models import Contact
        from apps.conversations.models import (
            Conversation, ConversationStatus, Message, MessageDirection,
        )
        from apps.bots.models import Bot
        from django.utils import timezone

        session = WhatsAppSession.objects.select_related("tenant").get(id=session_id)
        tenant = session.tenant
        client = get_client_for_session(session)

        logger.info("Iniciando sync de histórico | session=%s tenant=%s", session_id, tenant.slug)

        # 1. Busca lista de chats
        result = client.find_chats(limit=max_chats, wa_isGroup=False)
        chats = (
            result.get("chats") or result.get("data") or result
            if isinstance(result, dict) else result
        )
        if not isinstance(chats, list):
            logger.warning("sync_session_history: resposta inesperada: %s", type(result))
            return

        default_bot = Bot.objects.filter(tenant=tenant, is_active=True).first()
        total_imported = 0

        for chat in chats:
            chatid = chat.get("wa_chatid") or chat.get("chatid", "")
            if not chatid or chatid.endswith("@g.us"):
                continue

            phone = chatid.split("@")[0]
            if not phone or not phone.isdigit():
                continue

            name = chat.get("wa_contactName") or chat.get("wa_name") or ""

            contact, _ = Contact.objects.get_or_create(
                tenant=tenant,
                phone=phone,
                defaults={"name": name},
            )
            if name and not contact.name:
                contact.name = name
                contact.save(update_fields=["name"])

            # Pega ou cria conversa ativa
            conversation = (
                Conversation.objects.filter(tenant=tenant, contact=contact, session=session)
                .exclude(status=ConversationStatus.CLOSED)
                .order_by("-created")
                .first()
            )
            if not conversation:
                conversation = Conversation.objects.create(
                    tenant=tenant,
                    contact=contact,
                    session=session,
                    bot=default_bot,
                    status=ConversationStatus.BOT,
                )

            # 2. Busca mensagens do chat
            try:
                msg_result = client.find_messages(chatid, limit=messages_per_chat)
                messages = (
                    msg_result.get("messages", [])
                    if isinstance(msg_result, dict) else []
                )
            except Exception as exc:
                logger.warning("Falha ao buscar msgs de %s: %s", chatid, exc)
                continue

            last_dt = None

            for msg_data in reversed(messages):  # mais antigas primeiro
                wa_id = msg_data.get("messageid") or msg_data.get("id", "")
                if not wa_id:
                    continue

                # Evita duplicatas
                if Message.objects.filter(wa_message_id=wa_id).exists():
                    continue

                text = (msg_data.get("text") or "").strip()
                msg_type = msg_data.get("messageType", "")
                if not text and msg_type not in ("conversation", "extendedTextMessage"):
                    # Mídia sem texto — registra placeholder, URL será vazia
                    LABELS = {
                        "image": "📷 Imagem",
                        "video": "🎥 Vídeo",
                        "audio": "🎵 Áudio",
                        "ptt": "🎤 Áudio",
                        "document": "📄 Documento",
                        "sticker": "🎉 Figurinha",
                    }
                    text = LABELS.get(msg_type, "📎 Mídia")

                if not text:
                    continue

                from_me = msg_data.get("fromMe", False)
                direction = MessageDirection.OUT if from_me else MessageDirection.IN

                ts = msg_data.get("messageTimestamp")
                msg_dt = (
                    datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
                    if ts else timezone.now()
                )

                msg = Message.objects.create(
                    conversation=conversation,
                    direction=direction,
                    content=text,
                    wa_message_id=wa_id,
                    media_type=msg_type if msg_type in ("image", "video", "audio", "ptt", "document", "sticker") else "",
                )
                # Ajusta o timestamp para o da mensagem original
                Message.objects.filter(id=msg.id).update(created=msg_dt, modified=msg_dt)

                last_dt = msg_dt
                total_imported += 1

            if last_dt:
                Conversation.objects.filter(id=conversation.id).update(last_message_at=last_dt)

        logger.info(
            "Sync concluído | session=%s | %d mensagens importadas de %d chats",
            session_id, total_imported, len(chats),
        )

    except Exception as exc:
        logger.exception("Erro em sync_session_history | session=%s", session_id)
        raise self.retry(exc=exc, countdown=30)


# ---------------------------------------------------------------------------
# Enriquecimento automático de contatos
# ---------------------------------------------------------------------------

@shared_task(bind=True, name="channels_wa.enrich_contact_from_whatsapp", max_retries=2)
def enrich_contact_from_whatsapp(self, *, session_id: str, contact_id: str):
    """
    Busca nome e foto de perfil do WhatsApp e atualiza o Contact no banco.
    Chamada automaticamente ao criar novo contato via webhook.
    """
    try:
        from apps.channels_wa.models import WhatsAppSession
        from apps.channels_wa.uazapi import get_client_for_session
        from apps.contacts.models import Contact

        session = WhatsAppSession.objects.get(id=session_id)
        contact = Contact.objects.get(id=contact_id)
        client = get_client_for_session(session)

        chatid = f"{contact.phone}@s.whatsapp.net"
        data = client.get_chat_details(chatid)

        updated = []
        name = (
            data.get("name") or data.get("pushName")
            or data.get("wa_contactName") or data.get("wa_name", "")
        )
        avatar_url = (
            data.get("profilePicUrl") or data.get("avatar")
            or data.get("wa_profilePicUrl", "")
        )

        if name and not contact.name:
            contact.name = name
            updated.append("name")
        if avatar_url and not contact.avatar_url:
            contact.avatar_url = avatar_url
            updated.append("avatar_url")
        if updated:
            contact.save(update_fields=updated)
            logger.info("Contato %s enriquecido: %s", contact.phone, updated)

    except Exception as exc:
        logger.warning("Erro ao enriquecer contato %s: %s", contact_id, exc)
        raise self.retry(exc=exc, countdown=15)


# ---------------------------------------------------------------------------
# Campanhas em massa
# ---------------------------------------------------------------------------

@shared_task(bind=True, name="channels_wa.send_campaign_task", max_retries=1)
def send_campaign_task(
    self,
    *,
    session_id: str,
    phones: list[str],
    message: str,
    campaign_name: str = "MrBot Campaign",
):
    """
    Envia mensagem em massa via UazAPI /sender/simple.
    Fallback: envia individualmente com delay se a API de campanha falhar.
    """
    try:
        from apps.channels_wa.models import WhatsAppSession
        from apps.channels_wa.uazapi import get_client_for_session, UazAPIError

        session = WhatsAppSession.objects.get(id=session_id)
        client = get_client_for_session(session)

        logger.info(
            "Campanha '%s' iniciada | session=%s | %d destinatários",
            campaign_name, session_id, len(phones),
        )

        try:
            # Tenta usar o endpoint nativo de campanha
            client.send_campaign(numbers=phones, message=message, name=campaign_name)
            logger.info("Campanha '%s' enviada via /sender/simple.", campaign_name)
        except UazAPIError:
            # Fallback: envia um por um com delay
            import time
            logger.warning("Fallback: enviando campanha individualmente para %d números.", len(phones))
            for phone in phones:
                try:
                    client.send_text(phone=phone, message=message, delay=2000)
                    time.sleep(3)
                except Exception as exc:
                    logger.error("Falha ao enviar para %s: %s", phone, exc)

    except Exception as exc:
        logger.exception("Erro na campanha '%s' | session=%s", campaign_name, session_id)
        raise self.retry(exc=exc, countdown=60)
