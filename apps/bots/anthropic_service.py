"""
Serviço de integração com Anthropic Claude.

Converte internamente o formato OpenAI de histórico/ferramentas para o formato
Anthropic. A assinatura chat_completion() é idêntica aos demais serviços.

Diferenças-chave vs. OpenAI:
  - System prompt é passado como parâmetro top-level `system=`, não em `messages`
  - Tools: `parameters` → `input_schema`; wrapper `type/function` removido
  - Tool calls: stop_reason == "tool_use" + content blocks do tipo "tool_use"
  - Tool results: enviados como mensagem `user` com type "tool_result" (não role "tool")
  - Histórico user/assistant é compatível 1:1 (não precisa converter)
"""
import json
import logging

import anthropic
from django.conf import settings

logger = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 20
MAX_TOOL_ITERATIONS = 5


def get_client(api_key: str | None = None) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=api_key or settings.ANTHROPIC_API_KEY)


def _convert_tools_to_anthropic(tools: list[dict]) -> list[dict]:
    """Converte schemas OpenAI para o formato Anthropic."""
    result = []
    for tool in tools:
        fn = tool["function"]
        result.append({
            "name": fn["name"],
            "description": fn.get("description", ""),
            "input_schema": fn["parameters"],   # JSON Schema idêntico, só muda o nome
        })
    return result


def _content_block_to_dict(block) -> dict:
    """Converte um content block Anthropic em dict serializável."""
    if block.type == "text":
        return {"type": "text", "text": block.text}
    if block.type == "tool_use":
        return {
            "type": "tool_use",
            "id": block.id,
            "name": block.name,
            "input": block.input,   # já é dict Python
        }
    return {}


def chat_completion(
    *,
    system_prompt: str,
    history: list[dict],
    user_message: str,
    model: str = "claude-opus-4-5",
    temperature: float = 0.7,
    max_tokens: int = 500,
    tools: list[dict] | None = None,
    tool_executor=None,
    api_key: str | None = None,
) -> tuple[str, list[dict]]:
    client = get_client(api_key)

    trimmed_history = history[-MAX_HISTORY_MESSAGES:]

    # Histórico user/assistant já é compatível com Anthropic (roles idênticos)
    # Nota: system prompt NÃO entra no array de messages — vai como parâmetro top-level
    messages = [
        {"role": msg["role"], "content": msg["content"]}
        for msg in trimmed_history
    ]
    messages.append({"role": "user", "content": user_message})

    anthropic_tools = _convert_tools_to_anthropic(tools) if tools else []

    call_kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system_prompt,
        "temperature": temperature,
    }
    if anthropic_tools:
        call_kwargs["tools"] = anthropic_tools

    try:
        response = client.messages.create(**call_kwargs, messages=messages)

        # ── Loop de function calling ──────────────────────────────────────────
        iterations = 0
        while (
            tools
            and tool_executor
            and response.stop_reason == "tool_use"
            and iterations < MAX_TOOL_ITERATIONS
        ):
            iterations += 1

            # Adiciona mensagem do assistente (pode conter text + tool_use blocks)
            messages.append({
                "role": "assistant",
                "content": [_content_block_to_dict(b) for b in response.content],
            })

            # Executa cada tool_use e coleta resultados
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                result = tool_executor(block.name, block.input)
                logger.debug("Anthropic tool | %s -> %s", block.name, result)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })

            # Tool results voltam como mensagem do usuário (requisito Anthropic)
            messages.append({"role": "user", "content": tool_results})

            response = client.messages.create(**call_kwargs, messages=messages)

        # Extrai texto da resposta final (pode haver blocos text + tool_use misturados)
        reply = "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()

        logger.debug(
            "Anthropic | model=%s input=%d output=%d reply=%.80s",
            model,
            response.usage.input_tokens,
            response.usage.output_tokens,
            reply,
        )

        # Salva apenas user + assistant no histórico persistido (formato OpenAI)
        updated_history = trimmed_history + [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": reply},
        ]
        return reply, updated_history

    except Exception as exc:
        logger.exception("Erro na chamada Anthropic: %s", exc)
        raise
