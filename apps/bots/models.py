import uuid
from django.db import models
from django.utils.translation import gettext_lazy as _
from django_extensions.db.models import TimeStampedModel


class Department(models.TextChoices):
    SALES = "sales", _("Vendas")
    SUPPORT = "support", _("Suporte")
    FINANCE = "finance", _("Financeiro")
    LEADS = "leads", _("Captação de Leads")
    GENERAL = "general", _("Geral")


class Bot(TimeStampedModel):
    """Bot conversacional de um tenant."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="bots")
    name = models.CharField(_("nome do bot"), max_length=100)
    department = models.CharField(_("departamento"), max_length=20, choices=Department.choices, default=Department.GENERAL)
    avatar = models.ImageField(_("avatar"), upload_to="bots/avatars/", blank=True, null=True)
    is_active = models.BooleanField(_("ativo"), default=True)

    # Persona e instruções
    persona = models.TextField(_("persona"), blank=True, help_text="Descrição da personalidade do bot")
    capabilities = models.JSONField(_("o que pode fazer"), default=list, blank=True)
    restrictions = models.JSONField(_("o que não pode fazer"), default=list, blank=True)
    extra_instructions = models.TextField(_("instruções extras"), blank=True)

    # Configurações OpenAI
    model = models.CharField(_("modelo OpenAI"), max_length=50, default="gpt-4o")
    temperature = models.FloatField(_("temperatura"), default=0.7)
    max_tokens = models.PositiveIntegerField(_("máx. tokens resposta"), default=500)

    # Ferramentas (function calling)
    tools_enabled = models.BooleanField(
        _("ferramentas ativas"),
        default=False,
        help_text=_("Ativa function calling (ex: verificação de disponibilidade via Bookings)"),
    )

    class Meta:
        verbose_name = _("Bot")
        verbose_name_plural = _("Bots")
        ordering = ["tenant", "name"]

    def __str__(self):
        return f"{self.name} ({self.get_department_display()})"

    def build_system_prompt(self, company_name: str) -> str:
        caps = "\n".join(f"- {c}" for c in self.capabilities) or "- Responder dúvidas gerais"
        rests = "\n".join(f"- {r}" for r in self.restrictions) or "- Nenhuma restrição adicional"
        return f"""Você é {self.name}, assistente de {self.get_department_display()} da empresa {company_name}.

{self.persona}

VOCÊ PODE:
{caps}

VOCÊ NÃO PODE:
{rests}

{self.extra_instructions}

REGRAS GERAIS:
- Nunca invente informações que não lhe foram fornecidas.
- Se não souber responder, diga: "Vou te conectar com um especialista."
- Responda sempre em português brasileiro, de forma natural e amigável.
- Limite suas respostas a {self.max_tokens} tokens."""
