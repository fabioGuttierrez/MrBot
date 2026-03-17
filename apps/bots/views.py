import logging
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.contrib import messages

from .models import Bot, Department

logger = logging.getLogger(__name__)


@login_required
def index(request):
    tenant = request.tenant
    if not tenant:
        return redirect("tenants:onboarding")
    bots = Bot.objects.filter(tenant=tenant).order_by("department", "name")
    return render(request, "bots/index.html", {"bots": bots})


@login_required
def create(request):
    tenant = request.tenant
    if not tenant:
        return redirect("tenants:onboarding")
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        department = request.POST.get("department", Department.GENERAL)
        persona = request.POST.get("persona", "").strip()
        if name:
            bot = Bot.objects.create(
                tenant=tenant,
                name=name,
                department=department,
                persona=persona,
            )
            messages.success(request, f'Bot "{bot.name}" criado com sucesso.')
            return redirect("bots:detail", bot_id=bot.id)
    return render(request, "bots/form.html", {
        "departments": Department.choices,
        "action": "create",
    })


@login_required
def detail(request, bot_id):
    tenant = request.tenant
    bot = get_object_or_404(Bot, id=bot_id, tenant=tenant)
    if request.method == "POST":
        bot.name = request.POST.get("name", bot.name).strip()
        bot.department = request.POST.get("department", bot.department)
        bot.persona = request.POST.get("persona", bot.persona).strip()
        bot.extra_instructions = request.POST.get("extra_instructions", bot.extra_instructions).strip()
        bot.model = request.POST.get("model", bot.model)
        raw_caps = request.POST.get("capabilities", "")
        raw_rests = request.POST.get("restrictions", "")
        bot.capabilities = [c.strip() for c in raw_caps.splitlines() if c.strip()]
        bot.restrictions = [r.strip() for r in raw_rests.splitlines() if r.strip()]
        bot.save()
        messages.success(request, "Bot atualizado.")
        return redirect("bots:detail", bot_id=bot.id)
    return render(request, "bots/form.html", {
        "bot": bot,
        "departments": Department.choices,
        "action": "edit",
    })


@login_required
@require_POST
def toggle(request, bot_id):
    tenant = request.tenant
    bot = get_object_or_404(Bot, id=bot_id, tenant=tenant)
    bot.is_active = not bot.is_active
    bot.save(update_fields=["is_active"])
    status_str = "ativado" if bot.is_active else "desativado"
    messages.success(request, f'Bot "{bot.name}" {status_str}.')
    return redirect("bots:index")


@login_required
@require_POST
def delete(request, bot_id):
    tenant = request.tenant
    bot = get_object_or_404(Bot, id=bot_id, tenant=tenant)
    name = bot.name
    bot.delete()
    messages.success(request, f'Bot "{name}" removido.')
    return redirect("bots:index")
