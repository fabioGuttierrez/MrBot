"""
Serviço de integração com Google Gemini.

Converte internamente o formato OpenAI de histórico/ferramentas para o formato
Gemini (google-generativeai SDK). A assinatura chat_completion() é idêntica
aos demais serviços.

Diferenças-chave vs. OpenAI:
  - genai.configure() é process-global (seguro com Celery prefork; revisar se mudar para gevent)
  - Role "assistant" → "model"; content string → parts list
  - Tools: FunctionDeclaration aceita o mesmo JSON Schema do OpenAI
  - Tool calls: response.parts com atributo function_call
  - Tool results: {"function_response": {"name": ..., "response": {"result": ...}}}
"""
import logging

import google.generativeai as genai
from google.generativeai.types import FunctionDeclaration, Tool
from django.conf import settings

logger = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 20
MAX_TOOL_ITERATIONS = 5


def _convert_history_to_gemini(history: list[dict]) -> list[dict]:
    """Converte histórico formato OpenAI para o formato Gemini (contents)."""
    result = []
    for msg in history:
        role = "model" if msg["role"] == "assistant" else "user"
        result.append({"role": role, "parts": [{"text": msg["content"]}]})
    return result


def _convert_tools_to_gemini(tools: list[dict]) -> list:
    """Converte schemas OpenAI para Tool objects do Gemini SDK."""
    declarations = []
    for tool in tools:
        fn = tool["function"]
        declarations.append(
            FunctionDeclaration(
                name=fn["name"],
                description=fn.get("description", ""),
                parameters=fn["parameters"],    # JSON Schema é aceito diretamente
            )
        )
    return [Tool(function_declarations=declarations)]


def _has_function_call(response) -> bool:
    return any(
        hasattr(p, "function_call") and p.function_call
        for p in response.parts
    )


def _gemini_part_to_dict(part) -> dict:
    if hasattr(part, "function_call") and part.function_call:
        return {
            "function_call": {
                "name": part.function_call.name,
                "args": dict(part.function_call.args),
            }
        }
    return {"text": getattr(part, "text", "")}


def chat_completion(
    *,
    system_prompt: str,
    history: list[dict],
    user_message: str,
    model: str = "gemini-1.5-pro",
    temperature: float = 0.7,
    max_tokens: int = 500,
    tools: list[dict] | None = None,
    tool_executor=None,
    api_key: str | None = None,
) -> tuple[str, list[dict]]:
    key = api_key or settings.GOOGLE_API_KEY
    genai.configure(api_key=key)

    trimmed_history = history[-MAX_HISTORY_MESSAGES:]
    contents = _convert_history_to_gemini(trimmed_history)
    contents.append({"role": "user", "parts": [{"text": user_message}]})

    generation_config = genai.GenerationConfig(
        temperature=temperature,
        max_output_tokens=max_tokens,
    )
    gemini_tools = _convert_tools_to_gemini(tools) if tools else None

    model_obj = genai.GenerativeModel(
        model_name=model,
        system_instruction=system_prompt,
        generation_config=generation_config,
        tools=gemini_tools,
    )

    try:
        response = model_obj.generate_content(contents)

        # ── Loop de function calling ──────────────────────────────────────────
        iterations = 0
        while (
            tools
            and tool_executor
            and _has_function_call(response)
            and iterations < MAX_TOOL_ITERATIONS
        ):
            iterations += 1

            # Adiciona resposta do modelo (com function_call parts)
            contents.append({
                "role": "model",
                "parts": [_gemini_part_to_dict(p) for p in response.parts],
            })

            # Executa cada function_call e coleta resultados
            tool_response_parts = []
            for part in response.parts:
                if not (hasattr(part, "function_call") and part.function_call):
                    continue
                args = dict(part.function_call.args)
                result = tool_executor(part.function_call.name, args)
                logger.debug("Gemini tool | %s -> %s", part.function_call.name, result)
                tool_response_parts.append({
                    "function_response": {
                        "name": part.function_call.name,
                        "response": {"result": result},
                    }
                })

            contents.append({"role": "user", "parts": tool_response_parts})
            response = model_obj.generate_content(contents)

        reply = response.text.strip()
        logger.debug("Gemini | model=%s reply=%.80s", model, reply)

        # Salva apenas user + assistant no histórico persistido (formato OpenAI)
        updated_history = trimmed_history + [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": reply},
        ]
        return reply, updated_history

    except Exception as exc:
        logger.exception("Erro na chamada Gemini: %s", exc)
        raise
