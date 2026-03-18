from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import HttpResponse
from django.urls import reverse
from django.utils.text import slugify
from django.conf import settings

from .models import Tenant
from apps.accounts.models import TenantMembership, Role
from apps.channels_wa.models import WhatsAppSession, SessionStatus
from apps.channels_wa.evolution import EvolutionClient, EvolutionError, create_instance, fetch_instance


@login_required
def onboarding(request):
    """Wizard de onboarding — ponto de entrada."""
    tenant = request.tenant

    # Se já tem empresa e não está forçando um step → vai direto para o inbox
    if tenant and "step" not in request.GET:
        return redirect("inbox:index")

    if not tenant:
        default_step = 1
    else:
        default_step = int(request.GET.get("step", 2))

    initial_step = int(request.GET.get("step", default_step))
    return render(request, "onboarding/wizard.html", {"initial_step": initial_step})


@login_required
@require_POST
def onboarding_create_tenant(request):
    """Step 1: Cria Tenant + TenantMembership para o usuário."""
    if request.tenant:
        return redirect("inbox:index")

    company_name = request.POST.get("company_name", "").strip()
    if not company_name:
        return redirect("tenants:onboarding")

    # Gera slug único
    base_slug = slugify(company_name) or "empresa"
    slug = base_slug
    i = 1
    while Tenant.objects.filter(slug=slug).exists():
        slug = f"{base_slug}-{i}"
        i += 1

    tenant = Tenant.objects.create(name=company_name, slug=slug)
    TenantMembership.objects.create(user=request.user, tenant=tenant, role=Role.ADMIN)

    return redirect(reverse("tenants:onboarding") + "?step=2")


@login_required
def onboarding_wa_connect(request):
    """
    Step 2: Cria instância WhatsApp na Evolution API + conecta + retorna QR code (HTMX partial).
    GET/POST — acionado pelo botão 'Conectar WhatsApp' no wizard.
    """
    tenant = request.tenant
    if not tenant:
        return HttpResponse(
            '<p class="text-red-500 text-sm text-center">Crie sua empresa primeiro.</p>',
            status=400,
        )

    # Reutiliza sessão existente se já criada
    session = tenant.wa_sessions.filter(is_active=True).first()

    if not session:
        instance_name = f"{tenant.slug}-wa"
        try:
            data = create_instance(instance_name)
        except EvolutionError as exc:
            if "already in use" in str(exc).lower():
                try:
                    data = fetch_instance(instance_name)
                except EvolutionError as fetch_exc:
                    return render(request, "onboarding/_qr.html", {
                        "status": "error",
                        "error": str(fetch_exc),
                    })
            else:
                return render(request, "onboarding/_qr.html", {
                    "status": "error",
                    "error": str(exc),
                })
        try:
            session = WhatsAppSession.objects.create(
                tenant=tenant,
                name=f"WhatsApp — {tenant.name}",
                instance_id=data["name"],
                token=data["token"],
            )
            # Configura webhook na instância recém-criada
            webhook_url = (
                f"{settings.APP_BASE_URL.rstrip('/')}"
                f"/webhook/{tenant.slug}/{session.instance_id}/"
            )
            client = EvolutionClient(session.instance_id, session.token)
            client.set_webhook(webhook_url)

        except EvolutionError as exc:
            return render(request, "onboarding/_qr.html", {
                "status": "error",
                "error": str(exc),
            })

    # Inicia conexão para gerar QR code
    client = EvolutionClient(session.instance_id, session.token)
    try:
        resp = client.connect()
        instance_data = resp.get("instance", {})
        status = instance_data.get("status", "connecting")
        qr_code = instance_data.get("qrcode", "")
    except EvolutionError as exc:
        return render(request, "onboarding/_qr.html", {
            "status": "error",
            "error": str(exc),
        })

    return render(request, "onboarding/_qr.html", {
        "status": status,
        "qr_code": qr_code,
        "session_id": str(session.id),
    })


@login_required
def onboarding_wa_status(request):
    """
    Polling de status da sessão WhatsApp (HTMX every 3s).
    Retorna o mesmo partial _qr.html com status atualizado.
    """
    tenant = request.tenant
    if not tenant:
        return HttpResponse("", status=204)

    session = tenant.wa_sessions.filter(is_active=True).first()
    if not session:
        return render(request, "onboarding/_qr.html", {"status": "no_session"})

    client = EvolutionClient(session.instance_id, session.token)
    try:
        resp = client.get_status()
        instance_data = resp.get("instance", {})
        status = instance_data.get("status", "disconnected")
        qr_code = instance_data.get("qrcode", "")

        if status in ("connected", "open"):
            session.status = SessionStatus.CONNECTED
            session.phone_number = instance_data.get("profileNumber", "")
            session.save(update_fields=["status", "phone_number"])
            status = "connected"

    except EvolutionError:
        status = "error"
        qr_code = ""

    return render(request, "onboarding/_qr.html", {
        "status": status,
        "qr_code": qr_code,
        "phone_number": session.phone_number,
    })


@login_required
def onboarding_wa_pairing_code(request):
    """
    HTMX: gera código de pareamento para conectar sem câmera.
    GET  — exibe formulário de telefone.
    POST — gera e exibe o código de 8 caracteres.
    """
    tenant = request.tenant
    if not tenant:
        return HttpResponse(
            '<p class="text-red-500 text-sm text-center">Crie sua empresa primeiro.</p>',
            status=400,
        )

    if request.method == "GET":
        return render(request, "onboarding/_pairing.html", {"step": "form"})

    phone = request.POST.get("phone", "").strip()
    if not phone:
        return render(request, "onboarding/_pairing.html", {
            "step": "form",
            "error": "Informe o número de telefone.",
        })

    session = tenant.wa_sessions.filter(is_active=True).first()
    if not session:
        # Tenta criar a sessão primeiro
        return render(request, "onboarding/_pairing.html", {
            "step": "form",
            "error": "Clique em 'Conectar com QR code' para iniciar a instância antes de usar o código.",
        })

    client = EvolutionClient(session.instance_id, session.token)
    try:
        code = client.get_pairing_code(phone)
    except EvolutionError as exc:
        return render(request, "onboarding/_pairing.html", {
            "step": "form",
            "error": str(exc),
        })

    return render(request, "onboarding/_pairing.html", {
        "step": "code",
        "pairing_code": code,
    })
