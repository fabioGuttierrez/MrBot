def tenant(request):
    """Disponibiliza o tenant atual nos templates."""
    return {
        "current_tenant": getattr(request, "tenant", None),
    }
