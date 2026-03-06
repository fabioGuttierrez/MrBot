from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.utils import timezone


@login_required
def onboarding(request):
    """Wizard de onboarding para novos tenants."""
    tenant = request.tenant
    if not tenant:
        return redirect("account_login")
    return render(request, "onboarding/wizard.html", {"tenant": tenant})
