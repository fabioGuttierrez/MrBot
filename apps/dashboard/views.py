from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Avg
from django.db.models.functions import TruncDay, ExtractHour
from django.utils import timezone
from datetime import timedelta

from apps.conversations.models import Conversation, Message, ConversationStatus, MessageDirection
from apps.bots.models import Bot
from apps.contacts.models import Contact


@login_required
def index(request):
    tenant = request.tenant
    if not tenant:
        return redirect("tenants:onboarding")

    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)
    month_start = now - timedelta(days=30)

    convs = Conversation.objects.filter(tenant=tenant)

    today_count = convs.filter(created__gte=today_start).count()
    week_count = convs.filter(created__gte=week_start).count()
    month_count = convs.filter(created__gte=month_start).count()
    total_count = convs.count()

    by_status = {
        "bot": convs.filter(status=ConversationStatus.BOT).count(),
        "human": convs.filter(status=ConversationStatus.HUMAN).count(),
        "pending": convs.filter(status=ConversationStatus.PENDING).count(),
        "closed": convs.filter(status=ConversationStatus.CLOSED).count(),
    }

    messages_month = Message.objects.filter(
        conversation__tenant=tenant,
        created__gte=month_start,
    ).count()

    bots_active = Bot.objects.filter(tenant=tenant, is_active=True).count()
    bots_total = Bot.objects.filter(tenant=tenant).count()
    contacts_total = Contact.objects.filter(tenant=tenant).count()

    top_bots = (
        Bot.objects.filter(tenant=tenant)
        .annotate(conv_count=Count(
            "conversations",
            filter=Q(conversations__created__gte=month_start)
        ))
        .order_by("-conv_count")[:5]
    )

    recent_convs = (
        convs.select_related("contact", "bot")
        .order_by("-last_message_at")[:5]
    )

    # ── Gráfico: conversas por dia (30 dias) ────────────────────────────────
    daily_qs = (
        convs.filter(created__gte=month_start)
        .annotate(day=TruncDay("created"))
        .values("day")
        .annotate(count=Count("id"))
        .order_by("day")
    )
    daily_map = {entry["day"].date(): entry["count"] for entry in daily_qs}
    chart_labels = []
    chart_data = []
    for i in range(30):
        day = (month_start + timedelta(days=i)).date()
        chart_labels.append(day.strftime("%d/%m"))
        chart_data.append(daily_map.get(day, 0))

    # ── Tempo médio de resposta (min) ────────────────────────────────────────
    avg_response_min = None
    closed_sample = (
        convs.filter(status=ConversationStatus.CLOSED, created__gte=month_start)
        .prefetch_related("messages")[:100]
    )
    response_times = []
    for conv in closed_sample:
        msgs = conv.messages.order_by("created")
        first_in = next((m.created for m in msgs if m.direction == MessageDirection.IN), None)
        first_out = next((m.created for m in msgs if m.direction == MessageDirection.OUT), None)
        if first_in and first_out and first_out > first_in:
            response_times.append((first_out - first_in).total_seconds() / 60)
    if response_times:
        avg_response_min = round(sum(response_times) / len(response_times), 1)

    # ── Taxa de resolução ─────────────────────────────────────────────────────
    closed_month = by_status["closed"]
    resolution_rate = round(closed_month / month_count * 100, 1) if month_count else 0

    # ── Por agente ────────────────────────────────────────────────────────────
    by_agent = (
        convs.filter(created__gte=month_start)
        .exclude(assigned_to=None)
        .values("assigned_to__first_name", "assigned_to__last_name", "assigned_to__email")
        .annotate(count=Count("id"))
        .order_by("-count")[:10]
    )

    # ── Horários de pico ──────────────────────────────────────────────────────
    peak_qs = (
        Message.objects.filter(
            conversation__tenant=tenant,
            created__gte=month_start,
            direction=MessageDirection.IN,
        )
        .annotate(hour=ExtractHour("created"))
        .values("hour")
        .annotate(count=Count("id"))
        .order_by("hour")
    )
    peak_map = {entry["hour"]: entry["count"] for entry in peak_qs}
    peak_labels = [f"{h:02d}h" for h in range(24)]
    peak_data = [peak_map.get(h, 0) for h in range(24)]

    return render(request, "dashboard/index.html", {
        "today_count": today_count,
        "week_count": week_count,
        "month_count": month_count,
        "total_count": total_count,
        "by_status": by_status,
        "messages_month": messages_month,
        "bots_active": bots_active,
        "bots_total": bots_total,
        "contacts_total": contacts_total,
        "top_bots": top_bots,
        "recent_convs": recent_convs,
        # Novos
        "chart_labels": chart_labels,
        "chart_data": chart_data,
        "avg_response_min": avg_response_min,
        "resolution_rate": resolution_rate,
        "by_agent": by_agent,
        "peak_labels": peak_labels,
        "peak_data": peak_data,
    })

