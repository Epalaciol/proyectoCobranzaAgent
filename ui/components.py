"""
Funciones que leen los templates HTML y devuelven strings listos
para ser inyectados con st.markdown(html, unsafe_allow_html=True).
"""
import os
import re
import time
from datetime import date
from typing import List, Dict

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")

MESES_ES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
    5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
    9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre",
}


def _tpl(filename: str, **kwargs) -> str:
    """Carga un template y reemplaza {{placeholder}} con los valores dados.
    Usa {{key}} en lugar de {key} para evitar conflictos con JS/CSS."""
    with open(os.path.join(TEMPLATES_DIR, filename), "r", encoding="utf-8") as f:
        content = f.read()
    for key, value in kwargs.items():
        content = content.replace(f"{{{{{key}}}}}", str(value))
    return content


def fecha_es(d: date) -> str:
    return f"{d.day} de {MESES_ES[d.month]} de {d.year}"


_URL_RE = re.compile(r'(https?://[^\s<>"\']+)')


def _linkify(text: str) -> str:
    """Convierte URLs planas en etiquetas <a> clicables."""
    return _URL_RE.sub(
        r'<a href="\1" target="_blank" rel="noopener noreferrer" '
        r'style="color:#0d6efd;text-decoration:underline;word-break:break-all;">\1</a>',
        text,
    )


def render_bubble(role: str, texto: str, ts: str) -> str:
    """Renderiza una burbuja de mensaje (bot o user)."""
    css        = "bot" if role == "bot" else "user"
    check      = '<span class="wa-check">✓✓</span>' if css == "user" else ""
    safe_texto = _linkify(texto.replace("\n", "<br>"))
    return _tpl("bubble.html", css=css, texto=safe_texto, ts=ts, check=check)


TYPING_BUBBLE = (
    '<div class="wa-row bot">'
    '<div class="wa-bub bot wa-typing-bub">'
    '<span></span><span></span><span></span>'
    '</div></div>'
)


def render_full_chat(
    messages: List[Dict],
    today: date,
    nombre: str,
    numero: str,
    activo: bool,
    footer_content: str,
    typing: bool = False,
) -> str:
    """Renderiza el chat completo (header + mensajes + footer) en un solo bloque HTML.
    Si typing=True añade el indicador de puntos animados al final de los mensajes."""
    status  = "En línea" if activo else "Conversación cerrada"
    bubbles = "".join(
        render_bubble(m["role"], m["text"], m.get("ts", ""))
        for m in messages
    )
    if typing:
        bubbles += TYPING_BUBBLE
    return _tpl(
        "full_chat.html",
        nombre=nombre,
        numero=numero,
        status=status,
        fecha_label=f"Hoy · {fecha_es(today)}",
        bubbles=bubbles,
        footer_content=footer_content,
        ts=str(int(time.time() * 1000)),  # timestamp único fuerza re-ejecución del script
    )


def render_welcome() -> str:
    """Renderiza la pantalla de bienvenida cuando no hay campaña activa."""
    return _tpl("welcome.html")


def render_cliente_card(info: Dict, numero: str) -> str:
    """Renderiza la tarjeta de info del cliente en el sidebar."""
    riesgo_icon = {"BAJO": "🟢", "MEDIO": "🟡", "ALTO": "🔴"}.get(
        info.get("segmento_riesgo", ""), "⚪"
    )
    return (
        f'<div class="cli-card">'
        f'<b>{info["nombre"]}</b><br>'
        f'📱 {numero}<br>'
        f'💰 ${info["deuda_usd"]} USD &nbsp;·&nbsp; {info["dias_vencido"]} días sin pago<br>'
        f'{riesgo_icon} Riesgo <b>{info.get("segmento_riesgo", "N/A")}</b><br>'
        f'📡 {info["servicio"]}'
        f'</div>'
    )


def render_fase_badge(fase: str, fase_ui: Dict) -> str:
    """Renderiza el badge de fase actual en el sidebar."""
    ic, lbl, bg, fg = fase_ui.get(fase, ("⚪", "Sin iniciar", "#F1F5F9", "#374151"))
    return (
        f'<div style="background:{bg};color:{fg};padding:8px 12px;'
        f'border-radius:8px;font-size:13px;font-weight:600;">'
        f'{ic} {lbl}</div>'
    )


def render_chat_closed_footer(fase: str, fase_cerrar: str) -> str:
    """HTML del footer cuando el chat está cerrado."""
    if fase == fase_cerrar:
        return (
            '<div class="wa-closed" style="color:#166534;background:#DCFCE7;">'
            '✅ Conversación cerrada — cuenta regularizada exitosamente.</div>'
        )
    return (
        '<div class="wa-closed" style="color:#854D0E;background:#FEF9C3;">'
        '⚠️ Chat escalado a asesor humano.</div>'
    )
