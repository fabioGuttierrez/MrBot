import uuid
from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.utils.translation import gettext_lazy as _
from django_extensions.db.models import TimeStampedModel


class UserManager(BaseUserManager):
    """Manager sem exigência de username — usa e-mail como identificador."""

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("O e-mail é obrigatório.")
        email = self.normalize_email(email)
        extra_fields.setdefault("username", email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(email, password, **extra_fields)


class User(AbstractUser):
    """
    Usuário customizado do MrBot.
    O username é substituído pelo email como campo principal.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(_("e-mail"), unique=True)
    avatar = models.ImageField(_("avatar"), upload_to="accounts/avatars/", blank=True, null=True)
    phone = models.CharField(_("telefone"), max_length=20, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    objects = UserManager()

    class Meta:
        verbose_name = _("Usuário")
        verbose_name_plural = _("Usuários")

    def __str__(self):
        return self.get_full_name() or self.email

    @property
    def full_name(self):
        return self.get_full_name() or self.email


class Role(models.TextChoices):
    ADMIN = "admin", _("Administrador")
    SUPERVISOR = "supervisor", _("Supervisor")
    AGENT = "agent", _("Agente")
    VIEWER = "viewer", _("Visualizador")


class TenantMembership(TimeStampedModel):
    """
    Vincula um usuário a um tenant com um papel (role) específico.
    Um usuário pode pertencer a múltiplos tenants.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="memberships",
        verbose_name=_("usuário"),
    )
    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        related_name="memberships",
        verbose_name=_("tenant"),
    )
    role = models.CharField(_("papel"), max_length=20, choices=Role.choices, default=Role.AGENT)
    is_active = models.BooleanField(_("ativo"), default=True)

    class Meta:
        verbose_name = _("Membro")
        verbose_name_plural = _("Membros")
        unique_together = ("user", "tenant")
        ordering = ["tenant__name", "user__email"]

    def __str__(self):
        return f"{self.user} @ {self.tenant} [{self.role}]"

    # Helpers de permissão
    @property
    def is_admin(self):
        return self.role == Role.ADMIN

    @property
    def is_supervisor(self):
        return self.role in (Role.ADMIN, Role.SUPERVISOR)

    @property
    def can_takeover(self):
        """Pode assumir conversa do bot."""
        return self.role in (Role.ADMIN, Role.SUPERVISOR, Role.AGENT)
