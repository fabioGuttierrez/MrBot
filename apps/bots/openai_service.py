"""
Serviço de integração com OpenAI GPT.

Gerencia o histórico de mensagens por conversa e executa
chat completions com o system prompt do bot.
Suporta function calling (tools) com loop automático de execução.
"""
import json
import logging
from openai import OpenAI
from django.conf import settings

logger = logging.getLogger(__name__)

# Limite de mensagens do histórico mantidas em contexto
MAX_HISTORY_MESSAGES = 20
# Limite de iterações de tool calls por turno (evita loops infinitos)
MAX_TOOL_ITERATIONS = 5


def get_client(api_key: str | None = None) -> OpenAI:
    """Cria cliente OpenAI usando chave do bot ou fallback para settings."""
    return OpenAI(api_key=api_key or settings.OPENAI_API_KEY)


def chat_completion(
    *,
    system_prompt: str,
    history: list[dict],
    user_message: str,
    model: str = "gpt-4o",
    temperature: float = 0.7,
    max_tokens: int = 500,
    tools: list[dict] | None = None,
    tool_executor=None,
    api_key: str | None = None,
) -> tuple[str, list[dict]]:
    """
    Executa uma chat completion com histórico.

    Args:
        system_prompt:  Instrução do sistema (persona + capabilities + restrictions)
        history:        Lista de mensagens anteriores [{"role": ..., "content": ...}]
        user_message:   Mensagem atual do usuário
        model:          Modelo OpenAI a usar
        temperature:    Criatividade da resposta (0-2)
        max_tokens:     Limite de tokens na resposta
        tools:          Lista de tool schemas OpenAI (function calling). None = desativado.
        tool_executor:  Callable(tool_name, arguments) -> dict. Executa as ferramentas.
        api_key:        Chave de API do bot (sobrescreve settings.OPENAI_API_KEY se fornecida).

    Returns:
        Tuple (resposta_texto, novo_historico)
    """
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


def _chat_completion_with_client(
    client: OpenAI,
    *,
    system_prompt: str,
    history: list[dict],
    user_message: str,
    model: str,
    temperature: float,
    max_tokens: int,
    tools: list[dict] | None,
    tool_executor,
) -> tuple[str, list[dict]]:
    """
    Executa chat completion contra qualquer cliente OpenAI-compatível.
    Reutilizado pelo xai_service (mesma interface de wire, base_url diferente).
    """
    # Monta a lista completa de mensagens
    messages = [{"role": "system", "content": system_prompt}]

    # Mantém apenas as últimas N mensagens para não estourar o contexto
    trimmed_history = history[-MAX_HISTORY_MESSAGES:]
    messages.extend(trimmed_history)

    # Adiciona a nova mensagem do usuário
    messages.append({"role": "user", "content": user_message})

    extra_kwargs = {}
    if tools:
        extra_kwargs["tools"] = tools
        extra_kwargs["tool_choice"] = "auto"

    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **extra_kwargs,
        )

        # ── Loop de function calling ──────────────────────────────────────────
        iterations = 0
        while (
            tools
            and tool_executor
            and response.choices[0].finish_reason == "tool_calls"
            and iterations < MAX_TOOL_ITERATIONS
        ):
            iterations += 1
            assistant_msg = response.choices[0].message

            # Converte o objeto para dict e appenda ao histórico de chamada
            messages.append(assistant_msg)

            for tc in assistant_msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, ValueError):
                    args = {}

                result = tool_executor(tc.function.name, args)
                logger.debug("Tool result | %s -> %s", tc.function.name, result)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })

            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
            )

        reply = response.choices[0].message.content.strip()
        logger.debug(
            "OpenAI | model=%s tokens_used=%d reply=%.80s",
            model,
            response.usage.total_tokens,
            reply,
        )

        # Salva apenas user + assistant no histórico persistido
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
