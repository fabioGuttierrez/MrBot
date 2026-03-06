from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.utils import timezone
from datetime import timedelta

from apps.conversations.models import Conversation, Message, ConversationStatus
from apps.bots.models import Bot
from apps.contacts.models import Contact


@login_required
def index(request):
    tenant = request.tenant
    if not tenant:
        return redirect("account_login")

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
    })
