from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django.template.loader import render_to_string

from apps.tenants.models import Tenant
from apps.channels_wa.models import WhatsAppSession, SessionStatus


def _get_widget_data(tenant_slug):
    tenant = get_object_or_404(Tenant, slug=tenant_slug, is_active=True)
    session = (
        WhatsAppSession.objects
        .filter(tenant=tenant, is_active=True, status=SessionStatus.CONNECTED)
        .exclude(phone_number="")
        .first()
    )
    phone = session.phone_number if session else None
    return tenant, phone


def widget_page(request, tenant_slug):
    """Página HTML standalone com botão + modal de contato."""
    tenant, phone = _get_widget_data(tenant_slug)
    return HttpResponse(render_to_string("widget/widget.html", {
        "tenant": tenant,
        "phone": phone,
    }))


def embed_js(request, tenant_slug):
    """JS IIFE auto-instalável (botão flutuante verde)."""
    tenant, phone = _get_widget_data(tenant_slug)
    wa_number = phone.replace("+", "").replace(" ", "") if phone else ""
    js = f"""
(function() {{
  if (document.getElementById('mrbot-widget-btn')) return;

  var phoneNumber = "{wa_number}";
  if (!phoneNumber) return;

  // Botão flutuante
  var btn = document.createElement("div");
  btn.id = "mrbot-widget-btn";
  btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="white" width="28" height="28"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.892 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/></svg>';
  btn.style.cssText = "position:fixed;bottom:24px;right:24px;width:56px;height:56px;border-radius:50%;background:#25D366;display:flex;align-items:center;justify-content:center;cursor:pointer;box-shadow:0 4px 16px rgba(37,211,102,0.5);z-index:9999;transition:transform 0.2s;";
  btn.onmouseover = function(){{ this.style.transform="scale(1.1)"; }};
  btn.onmouseout = function(){{ this.style.transform="scale(1)"; }};

  // Modal
  var modal = document.createElement("div");
  modal.id = "mrbot-widget-modal";
  modal.style.cssText = "display:none;position:fixed;bottom:92px;right:24px;width:300px;background:white;border-radius:16px;box-shadow:0 8px 32px rgba(0,0,0,0.18);z-index:9999;overflow:hidden;font-family:sans-serif;";
  modal.innerHTML = '<div style="background:#25D366;padding:16px 20px;"><p style="margin:0;color:white;font-weight:700;font-size:15px;">{tenant.name}</p><p style="margin:4px 0 0;color:rgba(255,255,255,0.8);font-size:12px;">Fale conosco pelo WhatsApp</p></div><div style="padding:16px;"><label style="display:block;font-size:12px;color:#666;margin-bottom:4px;">Seu nome</label><input id="mrbot-name" type="text" placeholder="Como posso te chamar?" style="width:100%;box-sizing:border-box;border:1px solid #e5e7eb;border-radius:8px;padding:8px 12px;font-size:13px;margin-bottom:10px;outline:none;"><label style="display:block;font-size:12px;color:#666;margin-bottom:4px;">Mensagem</label><textarea id="mrbot-msg" rows="3" placeholder="Olá! Gostaria de saber mais..." style="width:100%;box-sizing:border-box;border:1px solid #e5e7eb;border-radius:8px;padding:8px 12px;font-size:13px;resize:none;outline:none;margin-bottom:12px;"></textarea><button onclick="window.__mrbotOpen()" style="width:100%;background:#25D366;color:white;border:none;border-radius:8px;padding:10px;font-size:14px;font-weight:600;cursor:pointer;">Abrir WhatsApp →</button></div>';

  window.__mrbotOpen = function() {{
    var name = document.getElementById("mrbot-name").value.trim();
    var msg  = document.getElementById("mrbot-msg").value.trim();
    var text = name ? "Olá! Meu nome é " + name + ". " + (msg || "") : (msg || "Olá!");
    window.open("https://wa.me/" + phoneNumber + "?text=" + encodeURIComponent(text), "_blank");
  }};

  btn.onclick = function() {{
    modal.style.display = modal.style.display === "none" ? "block" : "none";
  }};

  document.body.appendChild(modal);
  document.body.appendChild(btn);
}})();
""".strip()
    return HttpResponse(js, content_type="application/javascript")
