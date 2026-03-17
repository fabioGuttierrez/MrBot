from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required

PLANS = [
    {
        "id": "starter",
        "name": "Starter",
        "price": "R$ 97",
        "period": "/mês",
        "description": "Ideal para pequenos negócios começando com atendimento automatizado.",
        "features": [
            "1 número WhatsApp",
            "2 bots",
            "500 conversas/mês",
            "Flow Builder",
            "Suporte por e-mail",
        ],
        "cta": "Começar grátis",
        "highlighted": False,
    },
    {
        "id": "pro",
        "name": "Pro",
        "price": "R$ 247",
        "period": "/mês",
        "description": "Para equipes que precisam de múltiplos canais e bots.",
        "features": [
            "3 números WhatsApp",
            "10 bots",
            "3.000 conversas/mês",
            "Flow Builder avançado",
            "IA com GPT-4o",
            "Inbox multiagente",
            "Suporte prioritário",
        ],
        "cta": "Assinar Pro",
        "highlighted": True,
    },
    {
        "id": "enterprise",
        "name": "Enterprise",
        "price": "Sob consulta",
        "period": "",
        "description": "Para grandes empresas com volume alto e necessidades customizadas.",
        "features": [
            "Números ilimitados",
            "Bots ilimitados",
            "Conversas ilimitadas",
            "SLA garantido",
            "Integração customizada",
            "Suporte dedicado",
        ],
        "cta": "Falar com vendas",
        "highlighted": False,
    },
]


@login_required
def index(request):
    tenant = request.tenant
    if not tenant:
        return redirect("tenants:onboarding")
    subscription = getattr(tenant, "subscription", None)
    return render(request, "billing/index.html", {
        "plans": PLANS,
        "subscription": subscription,
    })
