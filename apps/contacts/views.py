import logging
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Q

from .models import Contact

logger = logging.getLogger(__name__)


def _get_connected_session(tenant):
    """Retorna a primeira sessão WhatsApp conectada do tenant, ou None."""
    from apps.channels_wa.models import WhatsAppSession, SessionStatus
    return (
        WhatsAppSession.objects
        .filter(tenant=tenant, is_active=True, status=SessionStatus.CONNECTED)
        .first()
    )


@login_required
def index(request):
    tenant = request.tenant
    if not tenant:
        return redirect("tenants:onboarding")
    q = request.GET.get("q", "").strip()
    contacts = Contact.objects.filter(tenant=tenant).order_by("name")
    if q:
        contacts = contacts.filter(
            Q(name__icontains=q) | Q(phone__icontains=q) | Q(email__icontains=q)
        )
    return render(request, "contacts/index.html", {
        "contacts": contacts,
        "q": q,
    })


@login_required
def detail(request, contact_id):
    tenant = request.tenant
    contact = get_object_or_404(Contact, id=contact_id, tenant=tenant)
    conversations = contact.conversations.select_related("bot").order_by("-last_message_at")[:10]
    session = _get_connected_session(tenant)
    return render(request, "contacts/detail.html", {
        "contact": contact,
        "conversations": conversations,
        "has_session": session is not None,
    })


@login_required
@require_POST
def enrich_contact(request, contact_id):
    """Busca dados do perfil no WhatsApp e atualiza o contato."""
    tenant = request.tenant
    contact = get_object_or_404(Contact, id=contact_id, tenant=tenant)
    session = _get_connected_session(tenant)

    if not session:
        messages.error(request, "Nenhuma sessão WhatsApp conectada.")
        return redirect("contacts:detail", contact_id=contact_id)

    try:
        from apps.channels_wa.uazapi import get_client_for_session
        client = get_client_for_session(session)
        chatid = f"{contact.phone}@s.whatsapp.net"
        data = client.get_chat_details(chatid)

        updated = []
        name = (
            data.get("name") or data.get("pushName")
            or data.get("wa_contactName") or data.get("wa_name", "")
        )
        avatar_url = (
            data.get("profilePicUrl") or data.get("avatar")
            or data.get("wa_profilePicUrl", "")
        )

        if name and not contact.name:
            contact.name = name
            updated.append("name")
        if avatar_url:
            contact.avatar_url = avatar_url
            updated.append("avatar_url")
        if updated:
            contact.save(update_fields=updated)

        messages.success(request, "Dados atualizados a partir do WhatsApp.")
    except Exception as exc:
        logger.error("Erro ao enriquecer contato %s: %s", contact_id, exc)
        messages.error(request, f"Erro ao buscar dados do WhatsApp: {exc}")

    return redirect("contacts:detail", contact_id=contact_id)


@login_required
def verify_number(request, contact_id):
    """Verifica se o número do contato tem WhatsApp (retorna JSON)."""
    tenant = request.tenant
    contact = get_object_or_404(Contact, id=contact_id, tenant=tenant)
    session = _get_connected_session(tenant)

    if not session:
        return JsonResponse({"ok": False, "error": "Nenhuma sessão WhatsApp conectada."})

    try:
        from apps.channels_wa.uazapi import get_client_for_session
        client = get_client_for_session(session)
        result = client.check_phone(contact.phone)
        has_wa = result.get("exists") or result.get("hasWhatsapp") or result.get("onWhatsApp", False)
        return JsonResponse({"ok": True, "has_whatsapp": bool(has_wa)})
    except Exception as exc:
        logger.error("Erro ao verificar número %s: %s", contact.phone, exc)
        return JsonResponse({"ok": False, "error": str(exc)})


@login_required
@require_POST
def sync_labels(request, contact_id):
    """Sincroniza as tags do contato com as labels do WhatsApp."""
    tenant = request.tenant
    contact = get_object_or_404(Contact, id=contact_id, tenant=tenant)
    session = _get_connected_session(tenant)

    if not session:
        messages.error(request, "Nenhuma sessão WhatsApp conectada.")
        return redirect("contacts:detail", contact_id=contact_id)

    try:
        from apps.channels_wa.uazapi import get_client_for_session
        client = get_client_for_session(session)
        chatid = f"{contact.phone}@s.whatsapp.net"
        client.set_chat_labels(chatid, contact.tags or [])
        label_str = ", ".join(contact.tags) if contact.tags else "nenhuma"
        messages.success(request, f"Labels sincronizados: {label_str}.")
    except Exception as exc:
        logger.error("Erro ao sincronizar labels de %s: %s", contact_id, exc)
        messages.error(request, f"Erro ao sincronizar labels: {exc}")

    return redirect("contacts:detail", contact_id=contact_id)


@login_required
def campaign(request):
    """Envia mensagem em massa para contatos do tenant."""
    tenant = request.tenant
    if not tenant:
        return redirect("tenants:onboarding")

    session = _get_connected_session(tenant)
    contacts = Contact.objects.filter(tenant=tenant).order_by("name")

    # Coleta todas as tags únicas do tenant para o filtro
    all_tags: set = set()
    for c in contacts:
        all_tags.update(c.tags or [])

    if request.method == "POST":
        text = request.POST.get("text", "").strip()
        tag_filter = request.POST.get("tag_filter", "").strip()
        selected_ids = request.POST.getlist("contact_ids")

        if not text:
            messages.error(request, "A mensagem não pode estar vazia.")
        elif not session:
            messages.error(request, "Nenhuma sessão WhatsApp conectada.")
        else:
            if selected_ids:
                target = Contact.objects.filter(tenant=tenant, id__in=selected_ids)
            elif tag_filter:
                target = Contact.objects.filter(tenant=tenant, tags__contains=[tag_filter])
            else:
                target = contacts

            phones = list(target.values_list("phone", flat=True))
            if phones:
                from apps.channels_wa.tasks import send_campaign_task
                send_campaign_task.delay(
                    session_id=str(session.id),
                    phones=phones,
                    message=text,
                    campaign_name=f"Campanha {tenant.name}",
                )
                messages.success(request, f"Campanha iniciada para {len(phones)} contatos.")
            else:
                messages.warning(request, "Nenhum contato selecionado.")

        return redirect("contacts:campaign")

    return render(request, "contacts/campaign.html", {
        "contacts": contacts,
        "all_tags": sorted(all_tags),
        "has_session": session is not None,
    })
