import json
import os
import logging
from datetime import date, timedelta

from langchain_ollama import ChatOllama
from langchain_core.tools import tool
from langchain_core.messages import (
    HumanMessage,
    SystemMessage,
    AIMessage,
    ToolMessage,
)
from typing import List, Optional

# ==========================================
# LOGGING ESTRUCTURADO
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ==========================================
# GUARDRAILS DE ENTRADA — Anti Prompt Injection
# ==========================================

MAX_INPUT_LENGTH = 600      # caracteres máximos por mensaje
MAX_TURNS_PER_SESSION = 25  # turnos máximos antes de cerrar la sesión

# Palabras clave que indican intento de desviar al agente de su propósito
_PATRONES_OFFTOPIC = [
    "ignora", "ignore", "olvida", "forget", "instrucciones anteriores",
    "previous instructions", "system prompt", "eres ahora", "you are now",
    "actúa como", "act as", "pretend", "roleplay", "juego de rol",
    "dime cómo", "tell me how", "receta", "recipe", "chiste", "joke",
    "escríbeme", "write me", "código", "código python", "python code",
    "hack", "jailbreak", "dan mode", "developer mode",
]


def validar_input(texto: str, turno_actual: int) -> tuple[bool, str]:
    """
    Valida el mensaje del usuario antes de enviarlo al LLM.
    Retorna (es_valido, mensaje_de_rechazo_o_vacio).
    """
    if turno_actual >= MAX_TURNS_PER_SESSION:
        logger.warning("Sesión cerrada por límite de turnos (%d)", turno_actual)
        return False, (
            "Esta conversación ha alcanzado su tiempo máximo. "
            "Para continuar gestionando tu cuenta podés ingresar a "
            "https://pagos.lla.com/linea o llamarnos. ¡Hasta pronto! 🙏"
        )

    if len(texto) > MAX_INPUT_LENGTH:
        logger.warning("Input rechazado: longitud %d > %d", len(texto), MAX_INPUT_LENGTH)
        return False, (
            "Tu mensaje es demasiado largo para procesarlo. "
            "¿Podés resumirlo en pocas palabras? 😊"
        )

    texto_lower = texto.lower()
    for patron in _PATRONES_OFFTOPIC:
        if patron in texto_lower:
            logger.warning("Posible prompt injection detectado: patron='%s'", patron)
            return False, (
                "Solo puedo ayudarte con la gestión de tu cuenta LLA. "
                "¿Querés conocer tus opciones de pago? 😊"
            )

    return True, ""


# ==========================================
# 1. HERRAMIENTAS (TOOLS)
# ==========================================

def _cargar_mock_db() -> dict:
    file_path = os.path.join(os.path.dirname(__file__), "mock_data.json")
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error("Error leyendo mock_data.json: %s", e)
        return {}


@tool
def consultar_datos_cliente(telefono: str) -> str:
    """Consulta los datos y el saldo pendiente de un cliente usando su número de teléfono."""
    mock_db = _cargar_mock_db()
    cliente = mock_db.get(telefono)
    if cliente:
        segmento = cliente.get("segmento_riesgo", "MEDIO")
        return (
            f"Cliente encontrado: {cliente['nombre']}. "
            f"Servicio contratado: {cliente.get('servicio', 'N/A')}. "
            f"País: {cliente.get('pais', 'N/A')}. "
            f"Saldo pendiente: ${cliente['deuda_usd']} USD. "
            f"Días sin pago: {cliente['dias_vencido']} días. "
            f"Fecha de vencimiento: {cliente.get('fecha_vencimiento', 'N/A')}. "
            f"Segmento de riesgo: {segmento}."
        )
    return "Cliente no encontrado en el sistema."


@tool
def generar_link_pago(telefono: str) -> str:
    """Genera un enlace de pago personalizado para que el cliente pague su saldo de forma inmediata."""
    mock_db = _cargar_mock_db()
    cliente = mock_db.get(telefono)
    if not cliente:
        return f"No se pudo generar el link: cliente {telefono} no encontrado."
    monto = cliente["deuda_usd"]
    link = f"https://pagos.lla.com/linea?tel={telefono}&monto={monto}&token=LLA2026"
    logger.info("Link de pago generado para %s: %s", telefono, link)
    return f"Link de pago generado: {link} (monto: ${monto} USD). Comparte este link con el cliente para pago inmediato."


@tool
def registrar_pago_inmediato(telefono: str, monto_usd: float) -> str:
    """Registra en el sistema que el cliente realizó o confirmó un pago inmediato total."""
    logger.info("CRM: Pago inmediato registrado — Tel: %s | Monto: $%.2f", telefono, monto_usd)
    return (
        f"ÉXITO: Pago inmediato de ${monto_usd} registrado para el número {telefono}. "
        f"La cuenta quedará al día en los próximos minutos."
    )


@tool
def registrar_promesa_pago(telefono: str, monto_usd: float, fecha_promesa: str) -> str:
    """Registra en el CRM que el cliente prometió pagar un monto en una fecha (formato YYYY-MM-DD)."""
    logger.info(
        "CRM: Promesa de pago registrada — Tel: %s | Monto: $%.2f | Fecha: %s",
        telefono, monto_usd, fecha_promesa,
    )
    return (
        f"ÉXITO: Promesa de pago de ${monto_usd} registrada para el {fecha_promesa}. "
        f"El cliente recibirá un recordatorio 24 horas antes."
    )


@tool
def escalar_a_humano(telefono: str, motivo: str) -> str:
    """Escala la conversación a un agente humano cuando el cliente está muy molesto o rechaza todas las opciones de pago."""
    logger.warning("ESCALAMIENTO: Tel %s → Motivo: %s", telefono, motivo)
    return (
        f"ESCALAMIENTO INICIADO: El caso del número {telefono} fue enviado a la cola de asesores. "
        f"Motivo: {motivo}. Un asesor se comunicará pronto."
    )


tools = [
    consultar_datos_cliente,
    generar_link_pago,
    registrar_pago_inmediato,
    registrar_promesa_pago,
    escalar_a_humano,
]

TOOL_MAP = {t.name: t for t in tools}


# ==========================================
# 2. AGENTES ESPECIALIZADOS
# ==========================================

MODEL_NAME = os.getenv("OLLAMA_MODEL", "llama3.1")

import prompts

try:
    llm_validador = ChatOllama(model=MODEL_NAME, temperature=0.2).bind_tools(
        [consultar_datos_cliente]
    )
    llm_negociador = ChatOllama(model=MODEL_NAME, temperature=0.3).bind_tools(
        [consultar_datos_cliente, generar_link_pago, registrar_pago_inmediato, escalar_a_humano]
    )
    llm_registrador = ChatOllama(model=MODEL_NAME, temperature=0.0).bind_tools(
        [registrar_promesa_pago]
    )
    llm_cierre = ChatOllama(model=MODEL_NAME, temperature=0.4)
    supervisor_llm = ChatOllama(model=MODEL_NAME, temperature=0.0)

    logger.info("Agentes inicializados correctamente (modelo: %s).", MODEL_NAME)
except Exception as e:
    logger.error("No se pudo conectar a Ollama: %s. ¿Está el servicio corriendo?", e)
    raise


# ==========================================
# 3. GESTIÓN DE FASE (sin tags de texto)
# ==========================================

# Fases válidas del flujo
FASE_VALIDAR   = "VALIDADOR"
FASE_NEGOCIAR  = "NEGOCIADOR"
FASE_REGISTRAR = "REGISTRADOR"
FASE_CERRAR    = "CERRAR"

# Marcas internas que el LLM puede incluir para señalar transiciones
_MARCAS_FASE = {
    "[FASE:NEGOCIAR]":  FASE_NEGOCIAR,
    "[FASE:REGISTRAR]": FASE_REGISTRAR,
    "[FASE:CERRAR]":    FASE_CERRAR,
}

def detectar_nueva_fase(texto: str) -> Optional[str]:
    """Retorna la nueva fase si el texto contiene una marca de transición, o None."""
    for marca, fase in _MARCAS_FASE.items():
        if marca in texto:
            return fase
    return None


def limpiar_marcas(texto: str) -> str:
    """Elimina las marcas internas del texto antes de mostrarlo al cliente."""
    for marca in _MARCAS_FASE:
        texto = texto.replace(marca, "")
    return texto.strip()


def agente_para_fase(fase: str):
    """Retorna (llm, system_prompt) según la fase actual."""
    if fase == FASE_VALIDAR:
        return llm_validador, prompts.SYSTEM_PROMPT_VALIDADOR
    if fase == FASE_NEGOCIAR:
        return llm_negociador, prompts.SYSTEM_PROMPT_NEGOCIADOR
    if fase == FASE_REGISTRAR:
        return llm_registrador, prompts.SYSTEM_PROMPT_REGISTRADOR
    if fase == FASE_CERRAR:
        return llm_cierre, prompts.SYSTEM_PROMPT_CIERRE
    return llm_validador, prompts.SYSTEM_PROMPT_VALIDADOR


# ==========================================
# 4. EJECUCIÓN DE TOOLS
# ==========================================

def _ejecutar_tools(tool_calls: list) -> tuple[list, bool]:
    tool_messages = []
    fue_escalado = False

    for tc in tool_calls:
        tool_name = tc["name"]
        logger.info("Tool: '%s' | args: %s", tool_name, tc["args"])

        selected_tool = TOOL_MAP.get(tool_name)
        if selected_tool:
            try:
                result = selected_tool.invoke(tc)
            except Exception as e:
                logger.error("Error en tool %s: %s", tool_name, e)
                result = f"Error interno al ejecutar {tool_name}. Intenta de nuevo."
        else:
            result = f"Error: herramienta '{tool_name}' no disponible."
            logger.error("Tool no encontrada: %s", tool_name)

        tool_messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))

        if tool_name == "escalar_a_humano":
            fue_escalado = True

    return tool_messages, fue_escalado


# ==========================================
# 5. ORQUESTADOR PRINCIPAL
# ==========================================

def procesar_mensaje(historial_mensajes: List, fase_actual: str = FASE_VALIDAR) -> tuple[str, bool, List, str]:
    """
    Procesa un mensaje del cliente y retorna (respuesta, chat_activo, historial, nueva_fase).

    Args:
        historial_mensajes: Lista de mensajes LangChain acumulados.
        fase_actual: Fase del flujo ('VALIDADOR', 'NEGOCIADOR', 'REGISTRADOR', 'CERRAR').

    Returns:
        (texto_respuesta, chat_sigue_activo, historial_actualizado, fase_siguiente)
    """
    agente, system_prompt = agente_para_fase(fase_actual)

    # Inyectar fecha actual para que el LLM calcule fechas reales de cuotas
    hoy = date.today()
    cuota1 = (hoy + timedelta(days=3)).strftime("%d/%m/%Y")
    cuota2 = (hoy + timedelta(days=18)).strftime("%d/%m/%Y")
    cuota3 = (hoy + timedelta(days=33)).strftime("%d/%m/%Y")
    contexto_fecha = (
        f"\n\nCONTEXTO DEL SISTEMA:\n"
        f"- FECHA_HOY: {hoy.strftime('%d/%m/%Y')} ({hoy.strftime('%A')})\n"
        f"- Fechas sugeridas para cuotas: CUOTA_1={cuota1} | CUOTA_2={cuota2} | CUOTA_3={cuota3}\n"
        f"- Usá estas fechas exactas al proponer planes de cuotas. NO uses placeholders como [fecha]."
    )
    system_prompt_con_fecha = system_prompt + contexto_fecha

    mensajes_para_llm = [SystemMessage(content=system_prompt_con_fecha)] + historial_mensajes

    # --- Invocación principal del agente ---
    try:
        response = agente.invoke(mensajes_para_llm)
    except Exception as e:
        logger.error("Error invocando LLM (%s): %s", fase_actual, e)
        fallback = (
            "En este momento tenemos una demora técnica. Podés pagar directamente en "
            "https://pagos.lla.com/linea o intentar nuevamente en unos minutos. ¡Gracias por tu paciencia! 🙏"
        )
        return fallback, True, historial_mensajes, fase_actual

    historial_actualizado = historial_mensajes + [response]

    # --- Ejecución de tools si el agente las solicitó ---
    if response.tool_calls:
        tool_messages, fue_escalado = _ejecutar_tools(response.tool_calls)
        historial_actualizado = historial_actualizado + tool_messages

        if fue_escalado:
            logger.info("Conversación escalada a humano.")
            return (
                "Entendido 🙏 Transferí tu caso a uno de nuestros asesores. "
                "En breve se comunicarán contigo. ¡Gracias por tu paciencia!",
                False,
                historial_actualizado,
                fase_actual,
            )

        try:
            final_response = agente.invoke(
                [SystemMessage(content=system_prompt_con_fecha)] + historial_actualizado
            )
        except Exception as e:
            logger.error("Error en re-invocación post-tool (%s): %s", fase_actual, e)
            return (
                "Hubo un retraso técnico. Podés regularizar tu cuenta en https://pagos.lla.com/linea 😊",
                True,
                historial_actualizado,
                fase_actual,
            )

        respuesta_texto = final_response.content
        historial_actualizado = historial_actualizado + [final_response]
    else:
        respuesta_texto = response.content

    # --- Detectar cambio de fase por marcas internas ---
    nueva_fase = detectar_nueva_fase(respuesta_texto) or fase_actual
    texto_limpio = limpiar_marcas(respuesta_texto)

    if not texto_limpio:
        texto_limpio = "Entendido, procedemos con lo acordado. 😊"

    # --- Auditoría del Supervisor ---
    logger.info("Supervisor auditando: '%s'", texto_limpio[:100])
    try:
        supervision = supervisor_llm.invoke([
            SystemMessage(content=prompts.SYSTEM_PROMPT_SUPERVISOR),
            HumanMessage(content=f"Mensaje del agente a evaluar:\n{texto_limpio}"),
        ])
        decision = supervision.content.strip()
    except Exception as e:
        logger.error("Error en Supervisor: %s", e)
        decision = "APROBADO"

    if decision.startswith("APROBADO"):
        logger.info("Supervisor: APROBADO ✅")
        chat_activo = nueva_fase != FASE_CERRAR
        return texto_limpio, chat_activo, historial_actualizado, nueva_fase

    logger.warning("Supervisor: RECHAZADO ❌ — %s", decision)
    fallback_supervisor = (
        "Para regularizar tu saldo de forma rápida y segura, ingresá a "
        "https://pagos.lla.com/linea o respondé aquí con tu propuesta de pago. 😊"
    )
    return fallback_supervisor, True, historial_actualizado, fase_actual
