import logging
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.db.models import Q
from django.utils import timezone

from .models import Contact, ContactStage, Campaign, CampaignStatus, FollowUp, FollowUpStatus

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


# ─── Broadcast (Campaign model) ───────────────────────────────────────────────

@login_required
def broadcast_list(request):
    tenant = request.tenant
    if not tenant:
        return redirect("tenants:onboarding")
    campaigns = Campaign.objects.filter(tenant=tenant).select_related("session", "created_by")
    return render(request, "contacts/broadcast_list.html", {"campaigns": campaigns})


@login_required
def broadcast_create(request):
    tenant = request.tenant
    if not tenant:
        return redirect("tenants:onboarding")

    from apps.channels_wa.models import WhatsAppSession, SessionStatus

    sessions = WhatsAppSession.objects.filter(tenant=tenant, is_active=True, status=SessionStatus.CONNECTED)

    # Coleta todas as tags únicas do tenant
    all_tags: set = set()
    for c in Contact.objects.filter(tenant=tenant).only("tags"):
        all_tags.update(c.tags or [])

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        message = request.POST.get("message", "").strip()
        session_id = request.POST.get("session_id", "")
        tags_filter_raw = request.POST.getlist("tags_filter")
        scheduled_at_raw = request.POST.get("scheduled_at", "").strip()

        errors = []
        if not name:
            errors.append("Nome é obrigatório.")
        if not message:
            errors.append("Mensagem é obrigatória.")
        if not session_id:
            errors.append("Selecione uma sessão WhatsApp.")

        session = sessions.filter(id=session_id).first() if session_id else None
        if session_id and not session:
            errors.append("Sessão inválida.")

        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            from apps.channels_wa.tasks import send_broadcast_task

            scheduled_at = None
            if scheduled_at_raw:
                from django.utils.dateparse import parse_datetime
                scheduled_at = timezone.make_aware(parse_datetime(scheduled_at_raw)) if parse_datetime(scheduled_at_raw) and timezone.is_naive(parse_datetime(scheduled_at_raw)) else parse_datetime(scheduled_at_raw)

            status = CampaignStatus.SCHEDULED if scheduled_at else CampaignStatus.DRAFT
            campaign = Campaign.objects.create(
                tenant=tenant,
                name=name,
                message=message,
                session=session,
                tags_filter=tags_filter_raw,
                status=status,
                scheduled_at=scheduled_at,
                created_by=request.user,
            )

            if scheduled_at and scheduled_at > timezone.now():
                send_broadcast_task.apply_async(args=[str(campaign.id)], eta=scheduled_at)
            else:
                send_broadcast_task.delay(str(campaign.id))

            messages.success(request, f"Campanha '{name}' iniciada com sucesso.")
            return redirect("contacts:broadcast_list")

    return render(request, "contacts/broadcast_create.html", {
        "sessions": sessions,
        "all_tags": sorted(all_tags),
    })


# ─── Pipeline Kanban ──────────────────────────────────────────────────────────

@login_required
def pipeline(request):
    tenant = request.tenant
    if not tenant:
        return redirect("tenants:onboarding")

    from django.db.models import OuterRef, Subquery
    from apps.conversations.models import Conversation

    # Subquery: last_message_at da conversa mais recente de cada contato
    latest_conv = (
        Conversation.objects
        .filter(contact=OuterRef("pk"), tenant=tenant)
        .order_by("-last_message_at")
        .values("last_message_at")[:1]
    )

    contacts = (
        Contact.objects
        .filter(tenant=tenant)
        .annotate(last_activity=Subquery(latest_conv))
        .order_by("name")
    )

    return render(request, "contacts/pipeline.html", {
        "lead_contacts":     contacts.filter(stage=ContactStage.LEAD),
        "prospect_contacts": contacts.filter(stage=ContactStage.PROSPECT),
        "client_contacts":   contacts.filter(stage=ContactStage.CLIENT),
        "inactive_contacts": contacts.filter(stage=ContactStage.INACTIVE),
    })


@login_required
@require_POST
def update_stage(request, contact_id):
    tenant = request.tenant
    contact = get_object_or_404(Contact, id=contact_id, tenant=tenant)
    new_stage = request.POST.get("stage", "")
    if new_stage in ContactStage.values:
        contact.stage = new_stage
        contact.save(update_fields=["stage"])

    if request.headers.get("HX-Request"):
        return render(request, "contacts/_pipeline_card.html", {"contact": contact})
    return redirect("contacts:pipeline")


# ─── Follow-ups ───────────────────────────────────────────────────────────────

@login_required
def followup_list(request):
    tenant = request.tenant
    if not tenant:
        return redirect("tenants:onboarding")

    status_filter = request.GET.get("status", "pending")
    followups = FollowUp.objects.filter(tenant=tenant).select_related("contact", "session", "created_by")
    if status_filter and status_filter != "all":
        followups = followups.filter(status=status_filter)

    return render(request, "contacts/followup_list.html", {
        "followups": followups,
        "status_filter": status_filter,
        "FollowUpStatus": FollowUpStatus,
    })


@login_required
def followup_create(request):
    tenant = request.tenant
    if not tenant:
        return HttpResponse("", status=400)

    from apps.channels_wa.models import WhatsAppSession, SessionStatus

    sessions = WhatsAppSession.objects.filter(tenant=tenant, is_active=True, status=SessionStatus.CONNECTED)
    contacts = Contact.objects.filter(tenant=tenant).order_by("name")

    # Pré-seleciona contato se passado via query string (ex: do botão no inbox)
    contact_id = request.GET.get("contact_id") or request.POST.get("contact_id")
    conversation_id = request.GET.get("conversation_id") or request.POST.get("conversation_id")

    preselected_contact = None
    if contact_id:
        preselected_contact = contacts.filter(id=contact_id).first()

    if request.method == "POST":
        cid = request.POST.get("contact_id", "")
        session_id = request.POST.get("session_id", "")
        message = request.POST.get("message", "").strip()
        scheduled_at_raw = request.POST.get("scheduled_at", "").strip()

        contact = contacts.filter(id=cid).first()
        session = sessions.filter(id=session_id).first()

        errors = []
        if not contact:
            errors.append("Contato inválido.")
        if not session:
            errors.append("Sessão WhatsApp inválida.")
        if not message:
            errors.append("Mensagem é obrigatória.")
        if not scheduled_at_raw:
            errors.append("Selecione data e hora.")

        if not errors:
            from django.utils.dateparse import parse_datetime
            from apps.channels_wa.tasks import send_followup_task

            dt = parse_datetime(scheduled_at_raw)
            if dt and timezone.is_naive(dt):
                dt = timezone.make_aware(dt)

            followup = FollowUp.objects.create(
                tenant=tenant,
                contact=contact,
                session=session,
                message=message,
                scheduled_at=dt,
                created_by=request.user,
            )

            if dt and dt > timezone.now():
                send_followup_task.apply_async(args=[str(followup.id)], eta=dt)
            else:
                send_followup_task.delay(str(followup.id))

            if request.headers.get("HX-Request"):
                return HttpResponse(
                    '<p class="text-green-600 text-sm font-medium text-center py-2">Follow-up agendado!</p>'
                )
            messages.success(request, "Follow-up agendado com sucesso.")
            return redirect("contacts:followup_list")

        if errors and request.headers.get("HX-Request"):
            error_html = "".join(f'<p class="text-red-500 text-sm">{e}</p>' for e in errors)
            return HttpResponse(error_html, status=422)
        for e in errors:
            messages.error(request, e)

    context = {
        "sessions": sessions,
        "contacts": contacts,
        "preselected_contact": preselected_contact,
        "conversation_id": conversation_id,
    }
    if request.headers.get("HX-Request"):
        return render(request, "contacts/_followup_form.html", context)
    return render(request, "contacts/followup_list.html", {**context, "show_form": True})


@login_required
@require_POST
def followup_cancel(request, followup_id):
    tenant = request.tenant
    fu = get_object_or_404(FollowUp, id=followup_id, tenant=tenant)
    if fu.status == FollowUpStatus.PENDING:
        fu.status = FollowUpStatus.CANCELLED
        fu.save(update_fields=["status"])
        messages.success(request, "Follow-up cancelado.")
    if request.headers.get("HX-Request"):
        return render(request, "contacts/_followup_row.html", {"fu": fu})
    return redirect("contacts:followup_list")

