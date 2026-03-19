import calendar as cal_module
from datetime import date
from itertools import groupby

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.views.decorators.http import require_POST

from .models import Resource, Booking, BookingStatus

WEEKDAYS_PT = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"]
WEEKDAYS_PT_LONG = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
WEEKDAYS_PT_ABBR = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]  # 0=Segunda
MONTHS_PT = [
    "", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]


@login_required
def calendar_view(request):
    tenant = request.tenant
    if not tenant:
        return redirect("tenants:onboarding")

    today = date.today()
    try:
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))
    except (ValueError, TypeError):
        year, month = today.year, today.month

    year = max(2020, min(2099, year))
    month = max(1, min(12, month))

    # Calendário com semana iniciando no domingo
    c = cal_module.Calendar(firstweekday=6)
    raw_weeks = c.monthdatescalendar(year, month)

    # Busca todas as reservas do mês
    first_day = date(year, month, 1)
    last_day = date(year, month, cal_module.monthrange(year, month)[1])

    bookings_qs = (
        Booking.objects
        .filter(tenant=tenant, event_date__gte=first_day, event_date__lte=last_day)
        .select_related("resource", "contact")
        .order_by("event_date", "resource__name")
    )

    bookings_by_date = {}
    for booking in bookings_qs:
        bookings_by_date.setdefault(booking.event_date, []).append(booking)

    # Monta estrutura de semanas para o template
    weeks = []
    for week in raw_weeks:
        week_data = []
        for day in week:
            week_data.append({
                "date": day,
                "in_month": day.month == month,
                "is_today": day == today,
                "bookings": bookings_by_date.get(day, []),
            })
        weeks.append(week_data)

    # Navegação prev/next mês
    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1

    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1

    # Dia selecionado (painel lateral)
    selected_date_str = request.GET.get("day")
    selected_date = None
    day_bookings = []
    if selected_date_str:
        try:
            selected_date = date.fromisoformat(selected_date_str)
            day_bookings = (
                Booking.objects
                .filter(tenant=tenant, event_date=selected_date)
                .select_related("resource", "contact")
                .order_by("resource__name")
            )
        except ValueError:
            pass

    resources = Resource.objects.filter(
        tenant=tenant, is_active=True
    ).order_by("category", "name")

    context = {
        "year": year,
        "month": month,
        "month_name": MONTHS_PT[month],
        "weekday_names": WEEKDAYS_PT,
        "weeks": weeks,
        "today": today,
        "prev_year": prev_year,
        "prev_month": prev_month,
        "next_year": next_year,
        "next_month": next_month,
        "selected_date": selected_date,
        "day_bookings": day_bookings,
        "resources": resources,
        "BookingStatus": BookingStatus,
    }

    return render(request, "bookings/calendar.html", context)


@login_required
def upcoming_view(request):
    """Lista de próximos compromissos agrupados por data."""
    tenant = request.tenant
    if not tenant:
        return redirect("tenants:onboarding")

    today = date.today()
    bookings_qs = (
        Booking.objects
        .filter(
            tenant=tenant,
            event_date__gte=today,
            status__in=[BookingStatus.PENDING, BookingStatus.CONFIRMED],
        )
        .select_related("resource", "contact")
        .order_by("event_date", "resource__name")
    )

    grouped = [
        {
            "date": d,
            "bookings": list(bks),
            "day_name": WEEKDAYS_PT_LONG[d.weekday()],
            "day_abbr": WEEKDAYS_PT_ABBR[d.weekday()],
            "month_name": MONTHS_PT[d.month],
        }
        for d, bks in groupby(bookings_qs, key=lambda b: b.event_date)
    ]

    return render(request, "bookings/upcoming.html", {
        "grouped": grouped,
        "today": today,
        "BookingStatus": BookingStatus,
    })


@login_required
def day_detail(request, date_str):
    """HTMX: painel de detalhes de um dia."""
    tenant = request.tenant
    try:
        selected_date = date.fromisoformat(date_str)
    except ValueError:
        return HttpResponse("Data inválida", status=400)

    day_bookings = (
        Booking.objects
        .filter(tenant=tenant, event_date=selected_date)
        .select_related("resource", "contact")
        .order_by("resource__name")
    )
    resources = Resource.objects.filter(
        tenant=tenant, is_active=True
    ).order_by("category", "name")

    return render(request, "bookings/partials/day_detail.html", {
        "selected_date": selected_date,
        "day_bookings": day_bookings,
        "resources": resources,
        "BookingStatus": BookingStatus,
    })


@login_required
@require_POST
def booking_update_status(request, booking_id, new_status):
    """Altera o status de uma reserva. Retorna partial HTMX ou redireciona."""
    tenant = request.tenant
    booking = get_object_or_404(Booking, id=booking_id, tenant=tenant)

    if new_status in [BookingStatus.CONFIRMED, BookingStatus.CANCELLED, BookingStatus.PENDING]:
        booking.status = new_status
        booking.save(update_fields=["status", "modified"])

    # Requisição normal (formulário da página upcoming) → redireciona
    if not request.headers.get("HX-Request"):
        return redirect("bookings:upcoming")

    # Requisição HTMX → retorna partial do painel do dia
    day_bookings = (
        Booking.objects
        .filter(tenant=tenant, event_date=booking.event_date)
        .select_related("resource", "contact")
        .order_by("resource__name")
    )
    resources = Resource.objects.filter(
        tenant=tenant, is_active=True
    ).order_by("category", "name")

    return render(request, "bookings/partials/day_detail.html", {
        "selected_date": booking.event_date,
        "day_bookings": day_bookings,
        "resources": resources,
        "BookingStatus": BookingStatus,
    })


@login_required
@require_POST
def booking_create(request):
    """HTMX: cria uma reserva manual e retorna o painel atualizado."""
    tenant = request.tenant
    resource_id = request.POST.get("resource")
    event_date_str = request.POST.get("event_date")
    client_name = request.POST.get("client_name", "").strip()
    notes = request.POST.get("notes", "").strip()

    error = None
    selected_date = None

    try:
        selected_date = date.fromisoformat(event_date_str)
    except (ValueError, TypeError):
        error = "Data inválida."

    resource = None
    if not error:
        try:
            resource = Resource.objects.get(id=resource_id, tenant=tenant, is_active=True)
        except Resource.DoesNotExist:
            error = "Recurso não encontrado."

    if not error:
        booked_count = Booking.objects.filter(
            resource=resource,
            event_date=selected_date,
            status__in=[BookingStatus.PENDING, BookingStatus.CONFIRMED],
        ).count()
        if booked_count >= resource.max_bookings_per_day:
            error = f"'{resource.name}' já está sem disponibilidade nesta data."

    if not error:
        Booking.objects.create(
            tenant=tenant,
            resource=resource,
            event_date=selected_date,
            status=BookingStatus.PENDING,
            client_name=client_name,
            notes=notes,
        )

    if not selected_date:
        selected_date = date.today()

    day_bookings = (
        Booking.objects
        .filter(tenant=tenant, event_date=selected_date)
        .select_related("resource", "contact")
        .order_by("resource__name")
    )
    resources = Resource.objects.filter(
        tenant=tenant, is_active=True
    ).order_by("category", "name")

    return render(request, "bookings/partials/day_detail.html", {
        "selected_date": selected_date,
        "day_bookings": day_bookings,
        "resources": resources,
        "BookingStatus": BookingStatus,
        "error": error,
    })
