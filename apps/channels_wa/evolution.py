"""
Evolution API client — integração com Evolution API v2.x
Documentação: https://doc.evolution-api.com

Autenticação:
- Todos os endpoints: header 'apikey' (global ou por instância)
- Endpoints admin:   header 'apikey' com a chave global EVOLUTION_API_KEY

Diferenças em relação ao protocolo anterior:
- Instance name vai no PATH, não no corpo da requisição
- Header de auth é 'apikey' (não 'token')
- Eventos webhook diferem (MESSAGES_UPSERT, CONNECTION_UPDATE, QRCODE_UPDATED)
- QR code vem como raw string ('code'), não como base64 PNG
  → geramos o PNG localmente com a lib 'qrcode'
- Sem endpoint de bulk/campaign (/sender/simple)
"""
import io
import logging
import httpx
import qrcode
import base64
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

# TTL do QR code em cache (segundos) — QR codes do WhatsApp expiram em ~60s
QR_CACHE_TTL = 90


class EvolutionError(Exception):
    pass


def _qr_cache_key(instance_id: str) -> str:
    return f"wa_qr:{instance_id}"


def _build_qr_base64(code: str) -> str:
    """
    Converte a raw string do QR code (formato Baileys) em data URL base64 PNG.
    'code' é a string entregue pelo campo 'code' do endpoint connect.
    """
    try:
        qr = qrcode.QRCode(version=1, box_size=6, border=2)
        qr.add_data(code)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        return f"data:image/png;base64,{b64}"
    except Exception as exc:
        logger.error("Erro ao gerar QR code PNG: %s", exc)
        return ""


class EvolutionClient:
    """
    Cliente HTTP para a Evolution API v2.
    """

    def __init__(self, instance_id: str, token: str):
        """
        instance_id: nome da instância (instance_name no Evolution)
        token:       apikey por instância (hash.apikey retornado em create_instance)
        """
        self.instance_id = instance_id
        self.token = token
        self.base_url = settings.EVOLUTION_API_URL.rstrip("/")
        self._headers = {
            "apikey": self.token,
            "Content-Type": "application/json",
        }

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def _post(self, path: str, payload: dict) -> dict | list:
        url = self._url(path)
        try:
            with httpx.Client(timeout=20.0) as client:
                resp = client.post(url, json=payload, headers=self._headers)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Evolution API HTTP %s — %s — payload: %s",
                exc.response.status_code, exc.response.text, payload,
            )
            raise EvolutionError(
                f"Evolution API error {exc.response.status_code}: {exc.response.text}"
            ) from exc
        except httpx.RequestError as exc:
            logger.error("Evolution API request error: %s", exc)
            raise EvolutionError(f"Evolution API request failed: {exc}") from exc

    def _get(self, path: str, params: dict | None = None) -> dict | list:
        url = self._url(path)
        try:
            with httpx.Client(timeout=20.0) as client:
                resp = client.get(url, params=params, headers=self._headers)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as exc:
            logger.error("Evolution API HTTP %s — %s", exc.response.status_code, exc.response.text)
            raise EvolutionError(
                f"Evolution API error {exc.response.status_code}: {exc.response.text}"
            ) from exc
        except httpx.RequestError as exc:
            logger.error("Evolution API request error: %s", exc)
            raise EvolutionError(f"Evolution API request failed: {exc}") from exc

    def _delete(self, path: str) -> dict:
        url = self._url(path)
        try:
            with httpx.Client(timeout=20.0) as client:
                resp = client.delete(url, headers=self._headers)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as exc:
            raise EvolutionError(
                f"Evolution API error {exc.response.status_code}: {exc.response.text}"
            ) from exc
        except httpx.RequestError as exc:
            raise EvolutionError(f"Evolution API request failed: {exc}") from exc

    def _put(self, path: str, payload: dict | None = None) -> dict:
        url = self._url(path)
        try:
            with httpx.Client(timeout=20.0) as client:
                resp = client.put(url, json=payload or {}, headers=self._headers)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as exc:
            raise EvolutionError(
                f"Evolution API error {exc.response.status_code}: {exc.response.text}"
            ) from exc
        except httpx.RequestError as exc:
            raise EvolutionError(f"Evolution API request failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Instância
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        """
        Retorna o status atual da instância normalizado para a interface anterior:
        {"instance": {"status": "connected"|"connecting"|"disconnected", "qrcode": "data:image/...", "profileNumber": ""}}

        GET /instance/connectionState/{instance}
        """
        resp = self._get(f"instance/connectionState/{self.instance_id}")
        raw_state = resp.get("instance", {}).get("state", "close")

        if raw_state == "open":
            status = "connected"
        elif raw_state == "connecting":
            status = "connecting"
        else:
            status = "disconnected"

        # QR code: lê do cache Redis (foi salvo pelo webhook QRCODE_UPDATED)
        qr_code = cache.get(_qr_cache_key(self.instance_id), "")

        return {
            "instance": {
                "status": status,
                "qrcode": qr_code,
                "profileNumber": "",
            }
        }

    def connect(self, phone: str | None = None) -> dict:
        """
        Inicia conexão e retorna QR code (ou pairing code se phone fornecido).

        - Sem phone: gera QR code, armazena em cache, retorna data URL PNG.
        - Com phone: retorna pairing code de 8 dígitos (--> use get_pairing_code).

        Normalizado para interface anterior:
        {"instance": {"status": "connecting", "qrcode": "data:image/..."}}

        GET /instance/connect/{instance}
        """
        resp = self._get(
            f"instance/connect/{self.instance_id}",
            params={"pairingCode": "false"},
        )

        # Tenta obter base64 da resposta (quando Evolution já envia)
        qr_base64 = resp.get("base64", "")

        # Fallback: gera PNG a partir do raw code string
        if not qr_base64:
            raw_code = resp.get("code", "")
            if raw_code:
                qr_base64 = _build_qr_base64(raw_code)

        # Persiste no cache para que o polling encontre
        if qr_base64:
            cache.set(_qr_cache_key(self.instance_id), qr_base64, QR_CACHE_TTL)

        return {
            "instance": {
                "status": "connecting",
                "qrcode": qr_base64,
            }
        }

    def get_pairing_code(self, phone: str) -> str:
        """
        Obtém código de pareamento por número de telefone (sem câmera).
        Retorna string de 8 dígitos, ex: "ABCD-1234".

        GET /instance/pairingCode/{instance}?number={phone}
        """
        normalized = self._normalize_phone(phone)
        resp = self._get(
            f"instance/pairingCode/{self.instance_id}",
            params={"number": normalized},
        )
        return resp.get("pairingCode", resp.get("code", ""))

    def restart(self) -> dict:
        """
        Reinicia o socket WhatsApp sem fazer logout (reconecta sem novo QR).
        PUT /instance/restart/{instance}
        """
        return self._put(f"instance/restart/{self.instance_id}")

    def disconnect(self) -> dict:
        """
        Desconecta a instância (logout do WhatsApp).
        DELETE /instance/logout/{instance}
        """
        cache.delete(_qr_cache_key(self.instance_id))
        return self._delete(f"instance/logout/{self.instance_id}")

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
        POST /message/sendText/{instance}
        """
        payload: dict = {
            "number": self._normalize_phone(phone),
            "options": {
                "delay": delay,
                "presence": "composing" if delay else "available",
            },
            "textMessage": {"text": message},
        }
        return self._post(f"message/sendText/{self.instance_id}", payload)

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
        """POST /message/sendMedia/{instance} — image"""
        payload = {
            "number": self._normalize_phone(phone),
            "mediaMessage": {
                "mediaType": "image",
                "media": url,
                "mimetype": "image/jpeg",
                "caption": caption,
            },
        }
        return self._post(f"message/sendMedia/{self.instance_id}", payload)

    def send_document(self, phone: str, url: str, filename: str, caption: str = "") -> dict:
        """POST /message/sendMedia/{instance} — document"""
        payload = {
            "number": self._normalize_phone(phone),
            "mediaMessage": {
                "mediaType": "document",
                "media": url,
                "fileName": filename,
                "caption": caption,
            },
        }
        return self._post(f"message/sendMedia/{self.instance_id}", payload)

    def send_audio(self, phone: str, url: str) -> dict:
        """POST /message/sendMedia/{instance} — audio ptt"""
        payload = {
            "number": self._normalize_phone(phone),
            "mediaMessage": {
                "mediaType": "audio",
                "media": url,
                "mimetype": "audio/ogg; codecs=opus",
            },
        }
        return self._post(f"message/sendMedia/{self.instance_id}", payload)

    def download_message(
        self,
        message_id: str,
        *,
        generate_mp3: bool = True,
        return_link: bool = True,
        transcribe: bool = False,
    ) -> dict:
        """
        Obtém mídia de uma mensagem como base64.
        POST /chat/getBase64FromMediaMessage/{instance}

        Normaliza resposta para interface anterior:
        retorna {'mediaUrl': url, 'text': transcription}
        """
        payload = {
            "message": {"key": {"id": message_id}},
            "convertToMp3": generate_mp3,
        }
        resp = self._post(f"chat/getBase64FromMediaMessage/{self.instance_id}", payload)

        # Evolution retorna {base64: "...", mimetype: "..."} — não URL direta
        # Normaliza para que tasks.py encontre as chaves esperadas
        return {
            "base64": resp.get("base64", ""),
            "mimetype": resp.get("mimetype", ""),
            "link": resp.get("url", resp.get("mediaUrl", "")),
            "url": resp.get("url", resp.get("mediaUrl", "")),
            "mediaUrl": resp.get("url", resp.get("mediaUrl", "")),
            "text": resp.get("transcription", resp.get("text", "")),
        }

    # ------------------------------------------------------------------
    # Chat / Contatos / Histórico
    # ------------------------------------------------------------------

    def check_phone(self, phone: str) -> dict:
        """
        Verifica se número tem WhatsApp.
        POST /chat/whatsappNumbers/{instance}
        """
        resp = self._post(
            f"chat/whatsappNumbers/{self.instance_id}",
            {"numbers": [self._normalize_phone(phone)]},
        )
        # Evolution retorna lista; normalizamos para dict
        if isinstance(resp, list) and resp:
            item = resp[0]
            return {"exists": item.get("exists", False), "jid": item.get("jid", "")}
        return {"exists": False}

    def mark_messages_read(self, chatid: str) -> dict:
        """
        Marca mensagens de um chat como lidas.
        POST /message/readMessages/{instance}
        """
        return self._post(
            f"message/readMessages/{self.instance_id}",
            {"readMessages": [{"key": {"remoteJid": chatid}}]},
        )

    def find_chats(
        self,
        *,
        limit: int = 30,
        offset: int = 0,
        wa_isGroup: bool = False,
        sort: str = "-wa_lastMsgTimestamp",
    ) -> dict:
        """
        Lista chats.
        POST /chat/findChats/{instance}

        Normaliza resposta para que sync_session_history encontre os campos esperados.
        """
        resp = self._post(f"chat/findChats/{self.instance_id}", {})
        chats = resp if isinstance(resp, list) else resp.get("chats", [])

        # Filtra grupos se necessário
        if not wa_isGroup:
            chats = [c for c in chats if not c.get("id", "").endswith("@g.us")]

        # Normaliza campos para interface anterior
        normalized = []
        for chat in chats[:limit]:
            jid = chat.get("id", chat.get("remoteJid", ""))
            name = chat.get("name", chat.get("pushName", ""))
            normalized.append({
                "wa_chatid": jid,
                "chatid": jid,
                "wa_contactName": name,
                "wa_name": name,
                "wa_lastMsgTimestamp": chat.get("conversationTimestamp", 0),
            })
        return {"chats": normalized}

    def find_messages(self, chatid: str, *, limit: int = 50, offset: int = 0) -> dict:
        """
        Busca mensagens de um chat.
        POST /chat/findMessages/{instance}

        Normaliza resposta para interface anterior.
        """
        payload = {
            "where": {"key": {"remoteJid": chatid}},
            "limit": limit,
            "offset": offset,
        }
        resp = self._post(f"chat/findMessages/{self.instance_id}", payload)
        messages_raw = resp if isinstance(resp, list) else resp.get("messages", resp.get("records", []))

        normalized = []
        for msg in messages_raw:
            key = msg.get("key", {})
            message_content = msg.get("message", {})
            text = (
                message_content.get("conversation", "")
                or message_content.get("extendedTextMessage", {}).get("text", "")
            )
            msg_type = msg.get("messageType", "conversation")
            # Normaliza tipo para interface anterior (ex: imageMessage -> image)
            normalized_type = _normalize_message_type(msg_type)
            normalized.append({
                "messageid": key.get("id", ""),
                "id": key.get("id", ""),
                "fromMe": key.get("fromMe", False),
                "chatid": key.get("remoteJid", chatid),
                "text": text,
                "messageType": normalized_type,
                "messageTimestamp": msg.get("messageTimestamp", 0),
            })
        return {"messages": normalized}

    def get_chat_details(self, chatid: str) -> dict:
        """
        Retorna perfil de um contato.
        GET /chat/fetchProfile/{instance}?number={phone}

        Normaliza para interface anterior.
        """
        phone = chatid.split("@")[0]
        try:
            resp = self._get(
                f"chat/fetchProfile/{self.instance_id}",
                params={"number": phone},
            )
            name = resp.get("name", resp.get("pushName", ""))
            return {
                "name": name,
                "pushName": resp.get("pushName", name),
                "wa_contactName": name,
                "wa_name": name,
                "profilePicUrl": resp.get("profilePictureUrl", resp.get("profilePicUrl", "")),
                "avatar": resp.get("profilePictureUrl", resp.get("profilePicUrl", "")),
                "wa_profilePicUrl": resp.get("profilePictureUrl", ""),
            }
        except EvolutionError:
            return {}

    def set_chat_labels(self, chatid: str, labels: list[str]) -> dict:
        """
        Define labels de um chat.
        POST /label/handleLabel/{instance}
        """
        try:
            return self._post(
                f"label/handleLabel/{self.instance_id}",
                {"number": chatid, "labelId": labels[0] if labels else ""},
            )
        except EvolutionError:
            return {}

    def get_labels(self) -> list:
        """
        Lista labels configuradas.
        GET /label/findLabels/{instance}
        """
        try:
            resp = self._get(f"label/findLabels/{self.instance_id}")
            return resp if isinstance(resp, list) else []
        except EvolutionError:
            return []

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
        POST /message/sendButtons/{instance}
        """
        evo_buttons = [
            {"buttonId": str(b.get("id", i)), "buttonText": {"displayText": b.get("text", "")}}
            for i, b in enumerate(buttons)
        ]
        payload: dict = {
            "number": self._normalize_phone(phone),
            "buttonMessage": {
                "title": title,
                "description": body,
                "footer": footer,
                "buttons": evo_buttons,
            },
        }
        return self._post(f"message/sendButtons/{self.instance_id}", payload)

    def send_campaign(
        self,
        numbers: list[str],
        message: str,
        name: str = "MrBot Campaign",
        delay_min: int = 3000,
        delay_max: int = 8000,
    ) -> dict:
        """
        Evolution API não possui endpoint de bulk send.
        Lança EvolutionError para que o caller use o fallback de loop individual.
        (tasks.py já possui esse fallback implementado)
        """
        raise EvolutionError("Evolution API não suporta bulk send nativo. Use o loop individual.")

    # ------------------------------------------------------------------
    # Webhook
    # ------------------------------------------------------------------

    def set_webhook(self, webhook_url: str, *, enabled: bool = True) -> dict:
        """
        Configura webhook na instância.
        POST /webhook/set/{instance}

        Inclui cabeçalho X-Webhook-Secret se configurado
        (Evolution v2.2+ suporta headers personalizados).
        """
        payload: dict = {
            "enabled": enabled,
            "url": webhook_url,
            "webhookByEvents": False,
            "webhookBase64": False,
            "events": [
                "MESSAGES_UPSERT",
                "MESSAGES_UPDATE",
                "CONNECTION_UPDATE",
                "QRCODE_UPDATED",
                "SEND_MESSAGE",
            ],
        }
        try:
            from django.conf import settings as dj_settings
            secret = dj_settings.WEBHOOK_SECRET
            if secret and secret != "changeme":
                payload["headers"] = {"X-Webhook-Secret": secret}
        except Exception:
            pass

        return self._post(f"webhook/set/{self.instance_id}", payload)

    def get_webhook(self) -> dict:
        """GET /webhook/find/{instance}"""
        return self._get(f"webhook/find/{self.instance_id}")

    # ------------------------------------------------------------------
    # Utils
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_phone(phone: str) -> str:
        phone = phone.split("@")[0]
        return "".join(filter(str.isdigit, phone))


def _normalize_message_type(msg_type: str) -> str:
    """
    Converte tipos de mensagem do Evolution para o formato legado esperado pelo sistema.
    Evolution: 'imageMessage', 'audioMessage', etc.
    Legado: 'image', 'audio', etc.
    """
    TYPE_MAP = {
        "imageMessage":    "image",
        "videoMessage":    "video",
        "audioMessage":    "audio",
        "pttMessage":      "ptt",
        "documentMessage": "document",
        "stickerMessage":  "sticker",
        "ptvMessage":      "video",
        "conversation":    "conversation",
        "extendedTextMessage": "conversation",
    }
    return TYPE_MAP.get(msg_type, msg_type)


def get_client_for_session(session) -> EvolutionClient:
    """Retorna um cliente Evolution configurado para uma WhatsAppSession."""
    return EvolutionClient(
        instance_id=session.instance_id,
        token=session.token,
    )


def fetch_instance(instance_name: str) -> dict:
    """
    Busca uma instância existente na Evolution API pelo nome.
    GET /instance/fetchInstances?instanceName={name}

    Returns: {'name': str, 'token': str}  — mesmo formato de create_instance.
    Raises EvolutionError se não encontrada.
    """
    base_url = settings.EVOLUTION_API_URL.rstrip("/")
    url = f"{base_url}/instance/fetchInstances"
    headers = {
        "apikey": settings.EVOLUTION_API_KEY,
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.get(url, params={"instanceName": instance_name}, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            items = data if isinstance(data, list) else [data]
            for item in items:
                inst = item.get("instance", item)
                name = inst.get("instanceName", "")
                if name == instance_name:
                    token = item.get("hash", {}).get("apikey", "")
                    return {"name": name, "token": token}
            raise EvolutionError(f"Instância '{instance_name}' não encontrada na Evolution API.")
    except httpx.HTTPStatusError as exc:
        raise EvolutionError(f"Erro ao buscar instância: {exc.response.text}") from exc
    except httpx.RequestError as exc:
        raise EvolutionError(f"Erro de conexão com Evolution API: {exc}") from exc


def create_instance(instance_name: str) -> dict:
    """
    Cria uma nova instância WhatsApp via endpoint admin da Evolution API.
    POST /instance/create — requer EVOLUTION_API_KEY (global admin key).

    Returns: {'name': str, 'token': str}
    """
    base_url = settings.EVOLUTION_API_URL.rstrip("/")
    url = f"{base_url}/instance/create"
    headers = {
        "apikey": settings.EVOLUTION_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "instanceName": instance_name,
        "qrcode": True,
        "integration": "WHATSAPP-BAILEYS",
    }
    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            instance_data = data.get("instance", data)
            hash_data = data.get("hash", {})
            # Normaliza para interface anterior: {name, token}
            return {
                "name": instance_data.get("instanceName", instance_name),
                "token": hash_data.get("apikey", ""),
            }
    except httpx.HTTPStatusError as exc:
        logger.error(
            "Evolution API create_instance HTTP %s — %s",
            exc.response.status_code, exc.response.text,
        )
        raise EvolutionError(f"Erro ao criar instância: {exc.response.text}") from exc
    except httpx.RequestError as exc:
        logger.error("Evolution API create_instance request error: %s", exc)
        raise EvolutionError(f"Erro de conexão com Evolution API: {exc}") from exc
