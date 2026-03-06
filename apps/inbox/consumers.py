import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

logger = logging.getLogger(__name__)


class ChatConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer para o chat em tempo real.
    Usado pela inbox para receber mensagens sem polling.
    """

    async def connect(self):
        self.conversation_id = str(self.scope["url_route"]["kwargs"]["conversation_id"])
        self.room_group_name = f"chat_{self.conversation_id}"

        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.close()
            return

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()
        logger.debug("WS conectado: %s (user=%s)", self.conversation_id, user)

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data):
        """Recebe mensagem enviada pelo agente humano via WebSocket."""
        try:
            data = json.loads(text_data)
            action = data.get("action")

            if action == "send_message":
                text = data.get("text", "").strip()
                if text:
                    await self._handle_agent_message(text)
        except Exception as exc:
            logger.exception("Erro no consumer receive: %s", exc)

    async def chat_message(self, event):
        """Recebe mensagem do channel layer e envia para o browser."""
        await self.send(text_data=json.dumps(event["message"]))

    @database_sync_to_async
    def _handle_agent_message(self, text: str):
        from django.utils import timezone
        from apps.conversations.models import Conversation, Message, MessageDirection
        from apps.channels_wa.uazapi import get_client_for_session

        try:
            conversation = Conversation.objects.select_related(
                "contact", "session", "tenant"
            ).get(id=self.conversation_id)

            msg = Message.objects.create(
                conversation=conversation,
                direction=MessageDirection.OUT,
                content=text,
            )
            conversation.last_message_at = timezone.now()
            conversation.save(update_fields=["last_message_at"])

            try:
                client = get_client_for_session(conversation.session)
                client.send_text(phone=conversation.contact.phone, message=text)
            except Exception as exc:
                logger.error("WS: falha ao enviar via UazAPI: %s", exc)

        except Exception as exc:
            logger.exception("WS: erro ao salvar mensagem do agente: %s", exc)
