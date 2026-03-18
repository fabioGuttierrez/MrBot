"""
Flow Engine — máquina de estados para execução de fluxos de atendimento.

Tipos de nó suportados:
  start          → ponto de entrada do flow
  send_message   → envia mensagem estática (suporta variáveis {{nome}})
  send_menu      → envia mensagem interativa com botões
  condition      → avalia a mensagem do contato via regex/keyword e ramifica
  set_variable   → salva um valor no contexto da conversa
  openai         → passa o controle para o OpenAI (modo IA livre)
  transfer_human → transfere para agente humano
  end            → encerra a conversa

Ciclo de execução (por mensagem recebida):
  1. Pega o nó atual da conversa (current_flow_node)
  2. Se for nó de condição → avalia a msg → salta para o próximo nó
  3. Executa o novo nó:
     • Nós imediatos (send_message, send_menu, set_variable) → executa e avança
     • Nós terminais (openai, transfer_human, end) → para o loop
  4. Persiste o nó atual na conversa
"""
import re
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Resultado de execução de um nó
# ---------------------------------------------------------------------------

@dataclass
class NodeResult:
    action: str   # "continue" | "send" | "openai" | "transfer_human" | "end" | "wait"
    next_node: Optional[str] = None
    message: Optional[str] = None
    variables: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------

def _render_template(text: str, context: dict) -> str:
    """Substitui {{variavel}} pelo valor do contexto."""
    for key, value in context.items():
        text = text.replace(f"{{{{{key}}}}}", str(value))
    return text


def _match_condition(branch: dict, message: str) -> bool:
    """
    Avalia se a mensagem bate com o branch.
    Suporta: lista de keywords, regex pattern ou default.
    """
    if branch.get("default"):
        return True

    pattern = branch.get("match", "")
    if not pattern:
        return False

    # Aceita múltiplos padrões separados por "|"
    return bool(re.search(pattern, message, re.IGNORECASE))


def _get_node(flow_definition: dict, node_id: str) -> Optional[dict]:
    """Retorna o nó pelo ID ou None se não encontrar."""
    for node in flow_definition.get("nodes", []):
        if node.get("id") == node_id:
            return node
    return None


# ---------------------------------------------------------------------------
# Executores por tipo de nó
# ---------------------------------------------------------------------------

def _exec_start(node: dict, **_) -> NodeResult:
    return NodeResult(action="continue", next_node=node.get("next"))


def _exec_send_message(node: dict, context: dict, **_) -> NodeResult:
    content = _render_template(node.get("content", ""), context)
    return NodeResult(
        action="send",
        next_node=node.get("next"),
        message=content,
    )


def _exec_condition(node: dict, message: str, **_) -> NodeResult:
    """
    Avalia os branches em ordem. O primeiro que bater vence.
    O branch com 'default: true' é o fallback.
    """
    branches = node.get("branches", [])

    # Separa o default para colocar por último
    ordered = [b for b in branches if not b.get("default")]
    ordered += [b for b in branches if b.get("default")]

    for branch in ordered:
        if _match_condition(branch, message):
            return NodeResult(action="continue", next_node=branch.get("next"))

    # Sem match e sem default → fica no mesmo nó aguardando nova mensagem
    logger.debug("Condition node %s: sem match para '%s'", node.get("id"), message[:80])
    return NodeResult(action="wait", next_node=node.get("id"))


def _exec_send_menu(node: dict, context: dict, **_) -> NodeResult:
    """
    Envia mensagem interativa com botões via WhatsApp.
    Definição do nó:
      {
        "type": "send_menu",
        "title": "Menu Principal",
        "body": "Como posso ajudar, {{contact_name}}?",
        "footer": "Escolha uma opção",       (opcional)
        "buttons": [
          {"id": "1", "text": "Suporte"},
          {"id": "2", "text": "Vendas"},
          {"id": "3", "text": "Falar com humano"}
        ],
        "next": "aguarda_resposta"
      }
    """
    title = _render_template(node.get("title", ""), context)
    body = _render_template(node.get("body", ""), context)
    footer = _render_template(node.get("footer", ""), context)
    buttons = node.get("buttons", [])
    return NodeResult(
        action="send",
        next_node=node.get("next"),
        message={
            "type": "menu",
            "title": title,
            "body": body,
            "footer": footer,
            "buttons": buttons,
        },
    )


def _exec_set_variable(node: dict, **_) -> NodeResult:
    var_name = node.get("variable", "")
    var_value = node.get("value", "")
    return NodeResult(
        action="continue",
        next_node=node.get("next"),
        variables={var_name: var_value} if var_name else {},
    )


def _exec_openai(node: dict, **_) -> NodeResult:
    """Sinaliza que o controle passa para o OpenAI."""
    return NodeResult(action="openai", next_node=node.get("id"))


def _exec_transfer_human(node: dict, **_) -> NodeResult:
    return NodeResult(action="transfer_human", next_node=node.get("id"))


def _exec_end(node: dict, **_) -> NodeResult:
    return NodeResult(action="end", next_node=None)


_EXECUTORS = {
    "start":           _exec_start,
    "send_message":    _exec_send_message,
    "send_menu":       _exec_send_menu,
    "condition":       _exec_condition,
    "set_variable":    _exec_set_variable,
    "openai":          _exec_openai,
    "transfer_human":  _exec_transfer_human,
    "end":             _exec_end,
}


# ---------------------------------------------------------------------------
# Função principal de execução
# ---------------------------------------------------------------------------

def run_flow(*, conversation, message_text: str) -> str:
    """
    Executa o flow da conversa para a mensagem recebida.

    Retorna uma string indicando o desfecho:
      "openai"         → bot engine deve chamar o OpenAI
      "transfer_human" → conversa transferida para humano
      "end"            → conversa encerrada
      "handled"        → flow enviou mensagem(ns) e continua no flow
      "no_flow"        → bot não tem flow configurado (cai no OpenAI)
    """
    from apps.conversations.models import ConversationStatus
    from apps.channels_wa.evolution import get_client_for_session

    bot = conversation.bot
    if not bot:
        return "no_flow"

    try:
        flow = bot.flow
    except Exception:
        return "no_flow"

    if not flow or not flow.is_active:
        return "no_flow"

    definition = flow.definition
    if not definition or not definition.get("nodes"):
        return "no_flow"

    # Contexto de variáveis da conversa (para template de mensagens)
    ctx = {
        "company_name": conversation.tenant.name,
        "contact_name": conversation.contact.display_name,
        "contact_phone": conversation.contact.phone,
    }

    current_node_id = conversation.current_flow_node or "start"
    messages_sent = []
    updated_vars = {}
    outcome = "handled"

    MAX_STEPS = 20  # evita loop infinito em flows mal formados
    steps = 0

    while steps < MAX_STEPS:
        steps += 1
        node = _get_node(definition, current_node_id)

        if not node:
            logger.warning(
                "Flow %s: nó '%s' não encontrado. Caindo no OpenAI.",
                flow.id, current_node_id,
            )
            outcome = "openai"
            break

        node_type = node.get("type", "")
        executor = _EXECUTORS.get(node_type)

        if not executor:
            logger.error("Flow %s: tipo de nó desconhecido '%s'.", flow.id, node_type)
            outcome = "openai"
            break

        result = executor(node=node, message=message_text, context=ctx)
        updated_vars.update(result.variables)
        ctx.update(result.variables)

        if result.action == "send":
            messages_sent.append(result.message)
            if result.next_node:
                current_node_id = result.next_node
            else:
                outcome = "handled"
                break

        elif result.action == "continue":
            if result.next_node:
                current_node_id = result.next_node
            else:
                outcome = "openai"
                break

        elif result.action == "wait":
            # Fica no mesmo nó esperando a próxima mensagem
            current_node_id = result.next_node
            outcome = "handled"
            break

        elif result.action == "openai":
            current_node_id = result.next_node
            outcome = "openai"
            break

        elif result.action == "transfer_human":
            outcome = "transfer_human"
            break

        elif result.action == "end":
            outcome = "end"
            break

    # Persiste o nó atual na conversa
    conversation.current_flow_node = current_node_id
    conversation.save(update_fields=["current_flow_node"])

    # Envia todas as mensagens acumuladas pelo flow
    if messages_sent:
        client = get_client_for_session(conversation.session)
        _save_and_send_messages(conversation, messages_sent, client)

    # Aplica desfechos terminais
    if outcome == "transfer_human":
        _do_transfer_human(conversation)

    elif outcome == "end":
        _do_end_conversation(conversation)

    return outcome


# ---------------------------------------------------------------------------
# Helpers de saída
# ---------------------------------------------------------------------------

def _save_and_send_messages(conversation, messages: list, client):
    """Salva e envia cada mensagem do flow (texto ou menu interativo)."""
    from apps.conversations.models import Message, MessageDirection
    from apps.channels_wa.tasks import _notify_websocket

    for msg_data in messages:
        if isinstance(msg_data, dict) and msg_data.get("type") == "menu":
            # Mensagem interativa com botões
            title = msg_data["title"]
            body = msg_data["body"]
            footer = msg_data.get("footer", "")
            buttons = msg_data["buttons"]
            labels = " | ".join(b.get("text", "") for b in buttons)
            content = f"[Menu] {title}\n{body}\n➤ {labels}"

            msg = Message.objects.create(
                conversation=conversation,
                direction=MessageDirection.OUT,
                content=content,
            )
            try:
                client.send_menu(
                    phone=conversation.contact.phone,
                    title=title,
                    body=body,
                    buttons=buttons,
                    footer=footer,
                )
            except Exception as exc:
                logger.error("Flow: falha ao enviar menu via Evolution API: %s", exc)
        else:
            # Mensagem de texto simples
            text = str(msg_data)
            msg = Message.objects.create(
                conversation=conversation,
                direction=MessageDirection.OUT,
                content=text,
            )
            try:
                client.send_text_with_delay(
                    phone=conversation.contact.phone,
                    message=text,
                    delay=800,
                    track_id=str(msg.id),
                )
            except Exception as exc:
                logger.error("Flow: falha ao enviar msg via Evolution API: %s", exc)

        _notify_websocket(conversation, msg)


def _do_transfer_human(conversation):
    """Marca a conversa como pendente para atendimento humano."""
    from apps.conversations.models import ConversationStatus
    conversation.status = ConversationStatus.PENDING
    conversation.save(update_fields=["status"])
    logger.info("Flow: conversa %s transferida para humano.", conversation.id)


def _do_end_conversation(conversation):
    """Encerra a conversa."""
    from apps.conversations.models import ConversationStatus
    conversation.status = ConversationStatus.CLOSED
    conversation.save(update_fields=["status"])
    logger.info("Flow: conversa %s encerrada pelo flow.", conversation.id)
