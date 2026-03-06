import logging
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.db.models import Q

from .models import Contact

logger = logging.getLogger(__name__)


@login_required
def index(request):
    tenant = request.tenant
    if not tenant:
        return redirect("account_login")
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
    return render(request, "contacts/detail.html", {
        "contact": contact,
        "conversations": conversations,
    })
