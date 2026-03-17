import json
import logging
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib import messages

from apps.bots.models import Bot
from .models import Flow

logger = logging.getLogger(__name__)


@login_required
def index(request):
    """Lista todos os flows do tenant."""
    tenant = request.tenant
    if not tenant:
        return redirect("tenants:onboarding")
    flows = Flow.objects.filter(tenant=tenant).select_related("bot").order_by("name")
    return render(request, "flows/index.html", {"flows": flows})


@login_required
def builder(request, flow_id=None):
    """Editor visual do flow. Abre existente ou cria novo."""
    tenant = request.tenant
    if not tenant:
        return redirect("tenants:onboarding")

    if flow_id:
        flow = get_object_or_404(Flow, id=flow_id, tenant=tenant)
    else:
        bot_id = request.GET.get("bot")
        bot = get_object_or_404(Bot, id=bot_id, tenant=tenant) if bot_id else None
        flow = Flow.objects.create(
            tenant=tenant,
            bot=bot,
            name=f"Flow de {bot.name}" if bot else "Novo Flow",
            definition=_default_flow(),
        )
        return redirect("flows:builder", flow_id=flow.id)

    bots = Bot.objects.filter(tenant=tenant, is_active=True)
    return render(request, "flows/builder.html", {
        "flow": flow,
        "bots": bots,
        "definition_json": json.dumps(flow.definition),
        "node_types": _NODE_TYPES,
    })


@login_required
@require_POST
def save_flow(request, flow_id):
    """Salva a definicao JSON do flow (chamado pelo builder via fetch)."""
    tenant = request.tenant
    flow = get_object_or_404(Flow, id=flow_id, tenant=tenant)

    try:
        if request.content_type == "application/json":
            payload = json.loads(request.body)
        else:
            payload = json.loads(request.POST.get("definition", "{}"))

        if "nodes" not in payload:
            return JsonResponse({"ok": False, "error": "Campo 'nodes' ausente."}, status=400)

        flow.definition = payload
        flow.name = payload.get("name", flow.name)
        flow.is_active = payload.get("is_active", flow.is_active)
        flow.save(update_fields=["definition", "name", "is_active"])

        logger.info("Flow %s salvo | nodes=%d", flow.id, len(payload["nodes"]))
        return JsonResponse({"ok": True, "flow_id": str(flow.id)})

    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "JSON invalido."}, status=400)
    except Exception as exc:
        logger.exception("Erro ao salvar flow %s", flow_id)
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)


@login_required
@require_POST
def toggle_active(request, flow_id):
    tenant = request.tenant
    flow = get_object_or_404(Flow, id=flow_id, tenant=tenant)
    flow.is_active = not flow.is_active
    flow.save(update_fields=["is_active"])
    status_str = "ativado" if flow.is_active else "desativado"
    messages.success(request, f'Flow "{flow.name}" {status_str}.')
    return redirect("flows:index")


@login_required
@require_POST
def delete_flow(request, flow_id):
    tenant = request.tenant
    flow = get_object_or_404(Flow, id=flow_id, tenant=tenant)
    name = flow.name
    flow.delete()
    messages.success(request, f'Flow "{name}" removido.')
    return redirect("flows:index")


_NODE_TYPES = [
    {"type": "send_message",   "label": "Enviar Mensagem",        "icon": "chat",    "color": "blue"},
    {"type": "condition",      "label": "Condicao",                "icon": "split",   "color": "yellow"},
    {"type": "set_variable",   "label": "Definir Variavel",        "icon": "tag",     "color": "purple"},
    {"type": "openai",         "label": "IA (OpenAI)",             "icon": "cpu",     "color": "green"},
    {"type": "transfer_human", "label": "Transferir p/ Humano",    "icon": "person",  "color": "orange"},
    {"type": "end",            "label": "Encerrar",                "icon": "stop",    "color": "red"},
]


def _default_flow() -> dict:
    return {
        "nodes": [
            {"id": "start",      "type": "start",       "label": "Inicio",   "position": {"x": 60,  "y": 180}, "next": "greeting"},
            {"id": "greeting",   "type": "send_message", "label": "Saudacao", "position": {"x": 260, "y": 180},
             "content": "Ola, {{contact_name}}! Como posso ajudar?", "next": "menu"},
            {"id": "menu",       "type": "condition",    "label": "Menu",     "position": {"x": 500, "y": 180},
             "branches": [
                 {"label": "Vendas",  "match": "venda|comprar|preco",    "next": "ia_vendas"},
                 {"label": "Suporte", "match": "suporte|problema|ajuda", "next": "ia_suporte"},
                 {"label": "Outros",  "default": True,                    "next": "ia_geral"},
             ]},
            {"id": "ia_vendas",  "type": "openai", "label": "IA Vendas",  "position": {"x": 760, "y": 80},  "next": None},
            {"id": "ia_suporte", "type": "openai", "label": "IA Suporte", "position": {"x": 760, "y": 200}, "next": None},
            {"id": "ia_geral",   "type": "openai", "label": "IA Geral",   "position": {"x": 760, "y": 320}, "next": None},
        ]
    }
