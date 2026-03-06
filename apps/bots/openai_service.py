"""
Serviço de integração com OpenAI GPT-4.

Gerencia o histórico de mensagens por conversa e executa
chat completions com o system prompt do bot.
"""
import logging
from openai import OpenAI
from django.conf import settings

logger = logging.getLogger(__name__)

# Limite de mensagens do histórico mantidas em contexto
MAX_HISTORY_MESSAGES = 20


def get_client() -> OpenAI:
    return OpenAI(api_key=settings.OPENAI_API_KEY)


def chat_completion(
    *,
    system_prompt: str,
    history: list[dict],
    user_message: str,
    model: str = "gpt-4o",
    temperature: float = 0.7,
    max_tokens: int = 500,
) -> tuple[str, list[dict]]:
    """
    Executa uma chat completion com histórico.

    Args:
        system_prompt: Instrução do sistema (persona + capabilities + restrictions)
        history:       Lista de mensagens anteriores [{"role": ..., "content": ...}]
        user_message:  Mensagem atual do usuário
        model:         Modelo OpenAI a usar
        temperature:   Criatividade da resposta (0-2)
        max_tokens:    Limite de tokens na resposta

    Returns:
        Tuple (resposta_texto, novo_historico)
    """
    client = get_client()

    # Monta a lista completa de mensagens
    messages = [{"role": "system", "content": system_prompt}]

    # Mantém apenas as últimas N mensagens para não estourar o contexto
    trimmed_history = history[-MAX_HISTORY_MESSAGES:]
    messages.extend(trimmed_history)

    # Adiciona a nova mensagem do usuário
    messages.append({"role": "user", "content": user_message})

    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        reply = response.choices[0].message.content.strip()
        logger.debug(
            "OpenAI | model=%s tokens_used=%d reply=%.80s",
            model,
            response.usage.total_tokens,
            reply,
        )

        # Atualiza o histórico com a nova troca
        updated_history = trimmed_history + [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": reply},
        ]

        return reply, updated_history

    except Exception as exc:
        logger.exception("Erro na chamada OpenAI: %s", exc)
        raise


def build_transfer_prompt() -> str:
    """Retorna frase padrão de transferência para humano."""
    return "Vou te conectar com um especialista agora. Um momento por favor!"
