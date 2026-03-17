"""
Cliente de integração com uazapiGO v2.0.
Documentação: OpenAPI spec incluída em Uazapi/uazapi-openapi-spec.yaml

Autenticação:
- Endpoints de instância: header 'token' (token da instância)
- Endpoints admin:        header 'admintoken' (token global)

As URLs NÃO incluem instance_id no path — a instância é identificada pelo token.
"""
import logging
import httpx
from django.conf import settings

logger = logging.getLogger(__name__)


class UazAPIError(Exception):
    pass


class UazAPIClient:
    """
    Cliente HTTP para a uazapiGO v2.0.
    Cada instância WhatsApp tem seu próprio token.
    """

    def __init__(self, instance_id: str, token: str):
        self.instance_id = instance_id
        self.token = token
        self.base_url = settings.UAZAPI_BASE_URL.rstrip("/")
        self._headers = {
            "token": self.token,
            "Content-Type": "application/json",
        }

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def _post(self, path: str, payload: dict) -> dict:
        url = self._url(path)
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(url, json=payload, headers=self._headers)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "UazAPI HTTP %s — %s — payload: %s",
                exc.response.status_code,
                exc.response.text,
                payload,
            )
            raise UazAPIError(
                f"UazAPI error {exc.response.status_code}: {exc.response.text}"
            ) from exc
        except httpx.RequestError as exc:
            logger.error("UazAPI request error: %s", exc)
            raise UazAPIError(f"UazAPI request failed: {exc}") from exc

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = self._url(path)
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(url, params=params, headers=self._headers)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as exc:
            logger.error("UazAPI HTTP %s — %s", exc.response.status_code, exc.response.text)
            raise UazAPIError(
                f"UazAPI error {exc.response.status_code}: {exc.response.text}"
            ) from exc
        except httpx.RequestError as exc:
            logger.error("UazAPI request error: %s", exc)
            raise UazAPIError(f"UazAPI request failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Instância
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        """
        Retorna o status atual da instância.
        Quando status='connecting', response.instance.qrcode contém o QR em base64.
        GET /instance/status
        """
        return self._get("instance/status")

    def connect(self, phone: str | None = None) -> dict:
        """
        Inicia conexão.
        - Sem phone: gera QR code (response.instance.qrcode em base64).
        - Com phone: gera código de pareamento (response.instance.paircode).
        POST /instance/connect
        """
        payload = {}
        if phone:
            payload["phone"] = self._normalize_phone(phone)
        return self._post("instance/connect", payload)

    def disconnect(self) -> dict:
        """Desconecta a instância. POST /instance/disconnect"""
        return self._post("instance/disconnect", {})

    # ------------------------------------------------------------------
    # Mensagens de texto
    # ------------------------------------------------------------------

    def send_text(
        self,
        phone: str,
        message: str,
        *,
        delay: int = 0,
        track_id: str = "",
        track_source: str = "mrbot",
    ) -> dict:
        """
        Envia mensagem de texto.
        POST /send/text

        Args:
            phone:        Número destino (ex: '5511999999999') ou chatid (@s.whatsapp.net).
            message:      Texto da mensagem.
            delay:        Ms de simulação de digitação antes do envio.
            track_id:     ID interno (Message.id) para rastreamento posterior.
            track_source: Origem do tracking (padrão: 'mrbot').
        """
        payload: dict = {
            "number": self._normalize_phone(phone),
            "text": message,
            "readchat": True,
        }
        if delay:
            payload["delay"] = delay
        if track_id:
            payload["track_id"] = track_id
            payload["track_source"] = track_source
        return self._post("send/text", payload)

    def send_text_with_delay(
        self,
        phone: str,
        message: str,
        delay: int = 1500,
        *,
        track_id: str = "",
    ) -> dict:
        """Alias conveniente — envia texto simulando 'Digitando...'."""
        return self.send_text(phone, message, delay=delay, track_id=track_id)

    # ------------------------------------------------------------------
    # Mensagens de mídia
    # ------------------------------------------------------------------

    def send_image(self, phone: str, url: str, caption: str = "") -> dict:
        """POST /send/media — image"""
        payload = {
            "number": self._normalize_phone(phone),
            "url": url,
            "mimetype": "image/jpeg",
        }
        if caption:
            payload["caption"] = caption
        return self._post("send/media", payload)

    def send_document(self, phone: str, url: str, filename: str, caption: str = "") -> dict:
        """POST /send/media — document"""
        payload = {
            "number": self._normalize_phone(phone),
            "url": url,
            "filename": filename,
        }
        if caption:
            payload["caption"] = caption
        return self._post("send/media", payload)

    def send_audio(self, phone: str, url: str) -> dict:
        """POST /send/media — audio (ptt)"""
        payload = {
            "number": self._normalize_phone(phone),
            "url": url,
            "mimetype": "audio/ogg; codecs=opus",
        }
        return self._post("send/media", payload)

    def download_message(
        self,
        message_id: str,
        *,
        generate_mp3: bool = True,
        return_link: bool = True,
        transcribe: bool = False,
    ) -> dict:
        """
        Baixa o arquivo de uma mensagem de mídia e retorna URL pública.
        POST /message/download

        Args:
            message_id:  ID da mensagem (wa_message_id).
            generate_mp3: Para áudios, retorna MP3 (True) ou OGG (False).
            return_link:  Retorna URL pública do arquivo.
            transcribe:   Transcreve áudios para texto via OpenAI Whisper.
        """
        return self._post("message/download", {
            "id": message_id,
            "generate_mp3": generate_mp3,
            "return_link": return_link,
            "transcribe": transcribe,
        })

    # ------------------------------------------------------------------
    # Chat / Contatos / Histórico
    # ------------------------------------------------------------------

    def check_phone(self, phone: str) -> dict:
        """
        Verifica se o número tem WhatsApp.
        POST /chat/check
        """
        return self._post("chat/check", {"number": self._normalize_phone(phone)})

    def mark_messages_read(self, chatid: str) -> dict:
        """
        Marca todas as mensagens de um chat como lidas no WhatsApp.
        POST /message/markread

        Args:
            chatid: ID do chat no formato JID (ex: '5511999999999@s.whatsapp.net').
        """
        return self._post("message/markread", {"chatid": chatid, "readall": True})

    def find_chats(
        self,
        *,
        limit: int = 30,
        offset: int = 0,
        wa_isGroup: bool = False,
        sort: str = "-wa_lastMsgTimestamp",
    ) -> dict:
        """
        Lista chats com filtros e paginação.
        POST /chat/find

        Args:
            limit:      Máximo de chats a retornar.
            offset:     Página (paginação).
            wa_isGroup: False = apenas individuais, True = apenas grupos.
            sort:       Campo de ordenação (- = desc).
        """
        return self._post("chat/find", {
            "wa_isGroup": wa_isGroup,
            "sort": sort,
            "limit": limit,
            "offset": offset,
        })

    def find_messages(self, chatid: str, *, limit: int = 50, offset: int = 0) -> dict:
        """
        Busca mensagens de um chat específico com paginação.
        POST /message/find

        Args:
            chatid:  JID do chat (ex: '5511999999999@s.whatsapp.net').
            limit:   Máximo de mensagens a retornar.
            offset:  Deslocamento para paginação.
        """
        return self._post("message/find", {
            "chatid": chatid,
            "limit": limit,
            "offset": offset,
        })

    def get_chat_details(self, chatid: str) -> dict:
        """
        Retorna perfil completo de um contato ou grupo (nome, foto, etc).
        POST /chat/details

        Args:
            chatid: JID do chat (ex: '5511999999999@s.whatsapp.net').
        """
        return self._post("chat/details", {"chatid": chatid})

    def set_chat_labels(self, chatid: str, labels: list[str]) -> dict:
        """
        Define as labels (etiquetas) de um chat no WhatsApp.
        POST /chat/labels

        Args:
            chatid:  JID do chat.
            labels:  Lista de nomes de etiquetas (ex: ['cliente', 'vip']).
        """
        return self._post("chat/labels", {"chatid": chatid, "labels": labels})

    def get_labels(self) -> list:
        """Retorna todas as etiquetas configuradas na instância. GET /labels"""
        return self._get("labels")

    def send_menu(
        self,
        phone: str,
        title: str,
        body: str,
        buttons: list[dict],
        footer: str = "",
    ) -> dict:
        """
        Envia mensagem interativa com botões.
        POST /send/menu

        Args:
            phone:   Número destino.
            title:   Título do menu.
            body:    Corpo/texto principal.
            buttons: Lista de botões: [{"id": "1", "text": "Opção 1"}, ...]
            footer:  Rodapé opcional.
        """
        payload: dict = {
            "number": self._normalize_phone(phone),
            "title": title,
            "body": body,
            "type": "buttons",
            "buttons": buttons,
        }
        if footer:
            payload["footer"] = footer
        return self._post("send/menu", payload)

    def send_campaign(
        self,
        numbers: list[str],
        message: str,
        name: str = "MrBot Campaign",
        delay_min: int = 3000,
        delay_max: int = 8000,
    ) -> dict:
        """
        Cria uma campanha de envio em massa.
        POST /sender/simple

        Args:
            numbers:   Lista de números destino.
            message:   Texto da mensagem.
            name:      Nome da campanha.
            delay_min: Delay mínimo entre msgs (ms).
            delay_max: Delay máximo entre msgs (ms).
        """
        return self._post("sender/simple", {
            "name": name,
            "message": message,
            "numbers": [self._normalize_phone(n) for n in numbers],
            "delayMin": delay_min,
            "delayMax": delay_max,
        })

    # ------------------------------------------------------------------
    # Webhook
    # ------------------------------------------------------------------

    def get_webhook(self) -> list:
        """
        Retorna os webhooks configurados na instância.
        GET /webhook  →  retorna lista de objetos webhook.
        """
        return self._get("webhook")

    def set_webhook(self, webhook_url: str, *, enabled: bool = True) -> list:
        """
        Configura webhook no modo simples (único webhook por instância).
        POST /webhook

        Events monitorados:
          - messages       → novas mensagens recebidas/enviadas
          - messages_update → atualizações de status (lido/entregue)
          - connection     → conexão/desconexão

        excludeMessages:
          - wasSentByApi   → evita loop de mensagens enviadas pela API
          - isGroupYes     → ignora mensagens de grupos (remova se quiser grupos)
        """
        payload = {
            "enabled": enabled,
            "url": webhook_url,
            "events": ["messages", "messages_update", "connection"],
            "excludeMessages": ["wasSentByApi", "isGroupYes"],
        }
        return self._post("webhook", payload)

    # ------------------------------------------------------------------
    # Utils
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_phone(phone: str) -> str:
        """
        Garante que o número esteja apenas com dígitos (E.164 sem '+').
        '5511 99999@s.whatsapp.net' → '5511999999'
        '+55 11 99999-9999'          → '5511999999999'
        '5511999999999@s.whatsapp.net' → '5511999999999'
        """
        # Remove sufixo JID se presente
        phone = phone.split("@")[0]
        return "".join(filter(str.isdigit, phone))


def get_client_for_session(session) -> UazAPIClient:
    """Retorna um UazAPIClient configurado para uma WhatsAppSession."""
    return UazAPIClient(
        instance_id=session.instance_id,
        token=session.token,
    )


def create_instance(instance_name: str) -> dict:
    """
    Cria uma nova instância WhatsApp via endpoint admin da UazAPI.
    POST /instance/init — requer UAZAPI_GLOBAL_TOKEN (admintoken).

    Returns: {'name': str, 'token': str}
    """
    base_url = settings.UAZAPI_BASE_URL.rstrip("/")
    url = f"{base_url}/instance/init"
    headers = {
        "admintoken": settings.UAZAPI_GLOBAL_TOKEN,
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(url, json={"name": instance_name}, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return {"name": data["name"], "token": data["token"]}
    except httpx.HTTPStatusError as exc:
        logger.error(
            "UazAPI create_instance HTTP %s — %s",
            exc.response.status_code,
            exc.response.text,
        )
        raise UazAPIError(f"Erro ao criar instância: {exc.response.text}") from exc
    except httpx.RequestError as exc:
        logger.error("UazAPI create_instance request error: %s", exc)
        raise UazAPIError(f"Erro de conexão com UazAPI: {exc}") from exc
