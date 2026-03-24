"""
Serviço de integração com xAI Grok.

Usa a biblioteca openai com base_url apontando para api.x.ai — a API do Grok
é totalmente compatível com o protocolo OpenAI (mesmos objetos de resposta,
function calling idêntico, etc.).
"""
import logging
from openai import OpenAI
from django.conf import settings
from .openai_service import _chat_completion_with_client

logger = logging.getLogger(__name__)

XAI_BASE_URL = "https://api.x.ai/v1"


def get_client(api_key: str | None = None) -> OpenAI:
    return OpenAI(
        api_key=api_key or settings.XAI_API_KEY,
        base_url=XAI_BASE_URL,
    )


def chat_completion(
    *,
    system_prompt: str,
    history: list[dict],
    user_message: str,
    model: str = "grok-2",
    temperature: float = 0.7,
    max_tokens: int = 500,
    tools: list[dict] | None = None,
    tool_executor=None,
    api_key: str | None = None,
) -> tuple[str, list[dict]]:
    client = get_client(api_key)
    return _chat_completion_with_client(
        client,
        system_prompt=system_prompt,
        history=history,
        user_message=user_message,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        tools=tools,
        tool_executor=tool_executor,
    )
