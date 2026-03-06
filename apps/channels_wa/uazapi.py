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

    def send_text(self, phone: str, message: str, *, delay: int = 0) -> dict:
        """
        Envia mensagem de texto.
        POST /send/text

        Args:
            phone:   Número destino (ex: '5511999999999') ou chatid (@s.whatsapp.net).
            message: Texto da mensagem.
            delay:   Ms de simulação de digitação antes do envio.
        """
        payload: dict = {
            "number": self._normalize_phone(phone),
            "text": message,
            "readchat": True,
        }
        if delay:
            payload["delay"] = delay
        return self._post("send/text", payload)

    def send_text_with_delay(self, phone: str, message: str, delay: int = 1500) -> dict:
        """Alias conveniente — envia texto simulando 'Digitando...'."""
        return self.send_text(phone, message, delay=delay)

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

    # ------------------------------------------------------------------
    # Chat / Contatos
    # ------------------------------------------------------------------

    def check_phone(self, phone: str) -> dict:
        """
        Verifica se o número tem WhatsApp.
        POST /chat/check
        """
        return self._post("chat/check", {"number": self._normalize_phone(phone)})

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
