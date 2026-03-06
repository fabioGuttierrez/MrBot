from django.http import Http404
from django.conf import settings
from .models import Tenant


class TenantMiddleware:
    """
    Injeta o tenant atual no request com base no usuário autenticado.
    Redireciona para seleção de tenant se necessário.
    """
    EXEMPT_PATHS = [
        "/admin/",
        "/accounts/",
        "/webhook/",
        "/static/",
        "/media/",
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Ignora paths isentos
        for path in self.EXEMPT_PATHS:
            if request.path.startswith(path):
                return self.get_response(request)

        # Injeta o tenant no request se o usuário estiver autenticado
        if request.user.is_authenticated:
            membership = (
                request.user.memberships
                .select_related("tenant")
                .filter(tenant__is_active=True)
                .first()
            )
            if membership:
                request.tenant = membership.tenant
            else:
                request.tenant = None
        else:
            request.tenant = None

        return self.get_response(request)
