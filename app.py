import streamlit as st
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from datetime import date, timedelta, datetime
import json
import os

import multi_agent
from ui.styles import inject_css
from ui.components import (
    render_full_chat,
    render_welcome,
    render_cliente_card,
    render_fase_badge,
    render_chat_closed_footer,
)

st.set_page_config(
    page_title="LLA — Simulador WhatsApp",
    page_icon="💬",
    layout="centered",
)

inject_css()

# ──────────────────────────────────────────
# DATOS MOCK
# ──────────────────────────────────────────
_DB_PATH = os.path.join(os.path.dirname(__file__), "mock_data.json")
try:
    with open(_DB_PATH, "r", encoding="utf-8") as f:
        mock_db: dict = json.load(f)
except Exception:
    mock_db = {}

opciones_clientes = [
    f"{tel} ({datos['nombre']} — {datos['perfil_test']})"
    for tel, datos in mock_db.items()
]
opciones_clientes.append("+50700000000 (Desconocido)")

FASE_UI = {
    multi_agent.FASE_VALIDAR:   ("🔵", "Validando identidad",  "#DBEAFE", "#1e3a8a"),
    multi_agent.FASE_NEGOCIAR:  ("🟡", "Negociando pago",      "#FEF9C3", "#713f12"),
    multi_agent.FASE_REGISTRAR: ("🟠", "Registrando acuerdo",  "#FFEDD5", "#7c2d12"),
    multi_agent.FASE_CERRAR:    ("🟢", "Cerrado exitosamente", "#DCFCE7", "#14532d"),
}

# ──────────────────────────────────────────
# SESSION STATE
# ──────────────────────────────────────────
_DEFAULTS = {
    "messages":            [],
    "historial_langchain": [],
    "chat_active":         False,
    "campaña_iniciada":    False,
    "fase_actual":         multi_agent.FASE_VALIDAR,
    "cliente_nombre":      "Cliente",
    "cliente_numero":      "",
}
for k, v in _DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v


def _ts() -> str:
    return datetime.now().strftime("%H:%M")


def _reset_session():
    for k, v in _DEFAULTS.items():
        st.session_state[k] = v
    st.session_state.chat_active      = True
    st.session_state.campaña_iniciada = True


def _build_contexto(numero: str, nombre: str) -> SystemMessage:
    hoy = date.today()
    c1  = (hoy + timedelta(days=3)).strftime("%d/%m/%Y")
    c2  = (hoy + timedelta(days=18)).strftime("%d/%m/%Y")
    c3  = (hoy + timedelta(days=33)).strftime("%d/%m/%Y")
    return SystemMessage(content=(
        f"CONTEXTO DE CAMPAÑA:\n"
        f"- TELEFONO_CONTACTO={numero}\n"
        f"- Titular registrado: {nombre}\n"
        f"- FECHA_HOY: {hoy.strftime('%d/%m/%Y')} ({hoy.strftime('%A')})\n"
        f"- Fechas sugeridas para cuotas: CUOTA_1={c1} | CUOTA_2={c2} | CUOTA_3={c3}\n"
        "Usá TELEFONO_CONTACTO en cualquier tool. Calculá fechas de cuotas a partir de CUOTA_1/2/3. "
        "NUNCA uses placeholders — siempre usá valores reales."
    ))


def _render_chat(typing: bool = False) -> str:
    """Shortcut para renderizar el chat con el estado actual."""
    footer = "" if st.session_state.chat_active else render_chat_closed_footer(
        st.session_state.fase_actual, multi_agent.FASE_CERRAR
    )
    return render_full_chat(
        messages       = st.session_state.messages,
        today          = date.today(),
        nombre         = st.session_state.cliente_nombre,
        numero         = st.session_state.cliente_numero,
        activo         = st.session_state.chat_active,
        footer_content = footer,
        typing         = typing,
    )


# ──────────────────────────────────────────
# SIDEBAR
# ──────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🎯 Disparar Campaña")
    st.caption("Seleccioná un cliente para iniciar el contacto.")

    sel           = st.selectbox("Seleccionar cliente", opciones_clientes, label_visibility="collapsed")
    numero_limpio = sel.split(" ")[0]
    info          = mock_db.get(numero_limpio)

    if info:
        st.markdown(render_cliente_card(info, numero_limpio), unsafe_allow_html=True)

    if st.button("▶ Iniciar conversación"):
        _reset_session()
        nombre = info["nombre"] if info else "el titular de la línea"
        st.session_state.cliente_nombre = nombre
        st.session_state.cliente_numero = numero_limpio

        primer = f"¡Hola! 👋 ¿Tengo el gusto de hablar con {nombre}?"
        st.session_state.messages.append({"role": "bot", "text": primer, "ts": _ts()})
        st.session_state.historial_langchain = [
            _build_contexto(numero_limpio, nombre),
            AIMessage(content=primer),
        ]
        st.rerun()

    st.divider()
    st.markdown(render_fase_badge(st.session_state.fase_actual, FASE_UI), unsafe_allow_html=True)
    st.caption("Escribí **STOP** para simular opt-out.")

# ──────────────────────────────────────────
# ÁREA DE CHAT — contenedor fijo
# ──────────────────────────────────────────
if not st.session_state.campaña_iniciada:
    st.markdown(render_welcome(), unsafe_allow_html=True)

else:
    # Contenedor único: Streamlit solo actualiza este elemento en cada rerun
    chat_slot = st.empty()
    chat_slot.markdown(_render_chat(), unsafe_allow_html=True)

    if st.session_state.chat_active:
        user_input = st.chat_input("Escribí un mensaje...", key="wa_input")

        if user_input:
            # Opt-out / re-enrutamiento — 4 categorías alineadas con
            # doc/arquitectura_aws.md §3 ("Gestión de opt-out en español").
            # En producción esta detección vive antes del LLM (Lambda)
            # como segunda capa de seguridad.
            categoria = multi_agent.clasificar_opt_out(user_input)
            if categoria:
                respuestas = {
                    "OPT_OUT": (
                        "Entendido 🙏 No te enviaremos más mensajes en esta campaña "
                        "durante los próximos 30 días. Cuando quieras regularizar tu "
                        "cuenta podés ir a https://pagos.lla.com/linea ¡Hasta pronto!"
                    ),
                    "EXCLUSION_PERMANENTE": (
                        "Entendido. Tu solicitud de exclusión de nuestras listas de "
                        "contacto fue registrada y será procesada por el área "
                        "correspondiente. No te contactaremos nuevamente por esta vía. 🙏"
                    ),
                    "FOLLOW_UP": (
                        "Sin problema 😊 Te contactamos en otro momento dentro del "
                        "horario permitido. Mientras tanto, podés pagar cuando gustes "
                        "en https://pagos.lla.com/linea"
                    ),
                    "ESCALAR_HUMANO": (
                        "Por supuesto 🙏 Te transferimos con un asesor. En breve se "
                        "comunicarán contigo con todo el contexto de esta conversación."
                    ),
                }
                st.session_state.messages.append({"role": "user", "text": user_input, "ts": _ts()})
                st.session_state.messages.append({"role": "bot", "text": respuestas[categoria], "ts": _ts()})
                st.session_state.chat_active = False
                chat_slot.markdown(_render_chat(), unsafe_allow_html=True)
                st.rerun()

            # Guardrail: validar input antes de tocar el LLM
            turno_actual = len([m for m in st.session_state.messages if m["role"] == "user"])
            es_valido, rechazo = multi_agent.validar_input(user_input, turno_actual)
            if not es_valido:
                st.session_state.messages.append({"role": "user", "text": user_input, "ts": _ts()})
                st.session_state.messages.append({"role": "bot", "text": rechazo, "ts": _ts()})
                if "tiempo máximo" in rechazo:
                    st.session_state.chat_active = False
                chat_slot.markdown(_render_chat(), unsafe_allow_html=True)
                st.rerun()

            # 1. Agregar mensaje del usuario al estado
            st.session_state.messages.append({"role": "user", "text": user_input, "ts": _ts()})
            st.session_state.historial_langchain.append(HumanMessage(content=user_input))

            # 2. Mostrar mensaje del usuario + typing indicator (sin rerun)
            chat_slot.markdown(_render_chat(typing=True), unsafe_allow_html=True)

            # 3. Llamar al LLM (bloquea hasta tener respuesta)
            respuesta, sigue, nuevo_hist, nueva_fase = multi_agent.procesar_mensaje(
                st.session_state.historial_langchain,
                fase_actual=st.session_state.fase_actual,
            )

            # 4. Guardar respuesta y actualizar estado
            st.session_state.messages.append({"role": "bot", "text": respuesta, "ts": _ts()})
            st.session_state.historial_langchain = nuevo_hist
            st.session_state.chat_active         = sigue
            st.session_state.fase_actual         = nueva_fase

            # 5. Un solo rerun para refrescar sidebar (fase badge) y limpiar el input
            st.rerun()
