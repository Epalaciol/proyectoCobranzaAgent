"""
Tests unitarios para el sistema Multi-Agente LLA.

Cómo ejecutar:
    source estebantest/bin/activate
    pytest tests/ -v
"""

import pytest
import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Mock de todas las dependencias de LangChain antes de importar multi_agent

def _make_tool_decorator():
    def tool(fn):
        fn.name = fn.__name__
        fn.invoke = lambda args: fn(**args)
        return fn
    return tool

_mock_tool = _make_tool_decorator()

_lc_core_mock = MagicMock()
_lc_core_mock.tools.tool = _mock_tool

_fake_modules = {
    "langchain_ollama":        MagicMock(ChatOllama=MagicMock(return_value=MagicMock(
                                   bind_tools=MagicMock(return_value=MagicMock())))),
    "langchain_core":          _lc_core_mock,
    "langchain_core.tools":    MagicMock(tool=_mock_tool),
    "langchain_core.messages": MagicMock(
                                   HumanMessage=MagicMock,
                                   SystemMessage=MagicMock,
                                   AIMessage=MagicMock,
                                   ToolMessage=MagicMock,
                               ),
}

with patch.dict("sys.modules", _fake_modules):
    from multi_agent import (
        consultar_datos_cliente,
        generar_link_pago,
        registrar_pago_inmediato,
        registrar_promesa_pago,
        escalar_a_humano,
        limpiar_marcas,
        detectar_nueva_fase,
        TOOL_MAP,
        tools,
        FASE_VALIDAR,
        FASE_NEGOCIAR,
        FASE_REGISTRAR,
        FASE_CERRAR,
    )


# ==========================================
# TESTS: consultar_datos_cliente
# ==========================================

class TestConsultarDatosCliente:

    def test_cliente_existente_juan(self):
        result = consultar_datos_cliente.invoke({"telefono": "+50712345678"})
        assert "Juan Pérez" in result
        assert "150" in result
        assert "45" in result

    def test_retorna_servicio(self):
        result = consultar_datos_cliente.invoke({"telefono": "+50712345678"})
        assert "Internet" in result

    def test_retorna_pais(self):
        result = consultar_datos_cliente.invoke({"telefono": "+50712345678"})
        assert "Panamá" in result

    def test_retorna_fecha_vencimiento(self):
        result = consultar_datos_cliente.invoke({"telefono": "+50712345678"})
        assert "2026-05-07" in result

    def test_retorna_segmento_riesgo(self):
        result = consultar_datos_cliente.invoke({"telefono": "+50712345678"})
        assert "Segmento de riesgo" in result

    def test_cliente_maria(self):
        result = consultar_datos_cliente.invoke({"telefono": "+50787654321"})
        assert "María Gómez" in result
        assert "45.5" in result

    def test_cliente_inexistente(self):
        result = consultar_datos_cliente.invoke({"telefono": "+00000000000"})
        assert "no encontrado" in result.lower()

    def test_numero_vacio(self):
        result = consultar_datos_cliente.invoke({"telefono": ""})
        assert "no encontrado" in result.lower()

    def test_todos_los_clientes_mock(self):
        numeros = ["+50712345678", "+50787654321", "+50755555555", "+50799999999", "+50766666666"]
        for numero in numeros:
            result = consultar_datos_cliente.invoke({"telefono": numero})
            assert "Cliente encontrado" in result, f"Fallo para {numero}"


# ==========================================
# TESTS: generar_link_pago
# ==========================================

class TestGenerarLinkPago:

    def test_link_generado_exitosamente(self):
        result = generar_link_pago.invoke({"telefono": "+50712345678"})
        assert "pagos.lla.com" in result
        assert "+50712345678" in result

    def test_link_incluye_monto(self):
        result = generar_link_pago.invoke({"telefono": "+50712345678"})
        assert "150" in result

    def test_link_cliente_inexistente(self):
        result = generar_link_pago.invoke({"telefono": "+00000000000"})
        assert "no encontrado" in result.lower()

    def test_link_incluye_token(self):
        result = generar_link_pago.invoke({"telefono": "+50799999999"})
        assert "token" in result.lower() or "LLA2026" in result


# ==========================================
# TESTS: registrar_pago_inmediato
# ==========================================

class TestRegistrarPagoInmediato:

    def test_registro_exitoso(self):
        result = registrar_pago_inmediato.invoke({
            "telefono": "+50712345678",
            "monto_usd": 150.0,
        })
        assert "ÉXITO" in result
        assert "150" in result

    def test_registro_incluye_confirmacion_cuenta(self):
        result = registrar_pago_inmediato.invoke({
            "telefono": "+50799999999",
            "monto_usd": 25.0,
        })
        assert "al día" in result.lower() or "cuenta" in result.lower()


# ==========================================
# TESTS: registrar_promesa_pago
# ==========================================

class TestRegistrarPromesaPago:

    def test_registro_exitoso(self):
        result = registrar_promesa_pago.invoke({
            "telefono": "+50712345678",
            "monto_usd": 75.0,
            "fecha_promesa": "2026-07-01",
        })
        assert "ÉXITO" in result
        assert "75.0" in result
        assert "2026-07-01" in result

    def test_registro_monto_completo(self):
        result = registrar_promesa_pago.invoke({
            "telefono": "+50712345678",
            "monto_usd": 150.0,
            "fecha_promesa": "2026-07-15",
        })
        assert "ÉXITO" in result

    def test_registro_incluye_recordatorio(self):
        result = registrar_promesa_pago.invoke({
            "telefono": "+50787654321",
            "monto_usd": 45.50,
            "fecha_promesa": "2026-07-10",
        })
        assert "recordatorio" in result.lower()


# ==========================================
# TESTS: escalar_a_humano
# ==========================================

class TestEscalarAHumano:

    def test_escalamiento_exitoso(self):
        result = escalar_a_humano.invoke({
            "telefono": "+50787654321",
            "motivo": "Cliente muy molesto y rechaza negociar.",
        })
        assert "ESCALAMIENTO INICIADO" in result
        assert "+50787654321" in result

    def test_escalamiento_incluye_motivo(self):
        motivo = "Cliente solicita hablar con humano."
        result = escalar_a_humano.invoke({
            "telefono": "+50712345678",
            "motivo": motivo,
        })
        assert motivo in result


# ==========================================
# TESTS: Gestión de fases
# ==========================================

class TestGestionFases:

    def test_detectar_fase_negociar(self):
        assert detectar_nueva_fase("Hola [FASE:NEGOCIAR] text") == FASE_NEGOCIAR

    def test_detectar_fase_registrar(self):
        assert detectar_nueva_fase("Acordado [FASE:REGISTRAR]") == FASE_REGISTRAR

    def test_detectar_fase_cerrar(self):
        assert detectar_nueva_fase("Gracias [FASE:CERRAR]") == FASE_CERRAR

    def test_detectar_sin_marca(self):
        assert detectar_nueva_fase("Mensaje normal sin marcas") is None

    def test_limpiar_marcas_negociar(self):
        resultado = limpiar_marcas("Hola cliente [FASE:NEGOCIAR]")
        assert "[FASE:NEGOCIAR]" not in resultado
        assert "Hola cliente" in resultado

    def test_limpiar_multiples_marcas(self):
        resultado = limpiar_marcas("[FASE:NEGOCIAR] texto [FASE:REGISTRAR]")
        assert "[FASE:" not in resultado

    def test_limpiar_sin_marcas_no_cambia(self):
        texto = "Mensaje limpio sin marcas"
        assert limpiar_marcas(texto) == texto


# ==========================================
# TESTS: Configuración del sistema
# ==========================================

class TestConfiguracionSistema:

    def test_tool_map_contiene_todas_las_tools(self):
        esperadas = {
            "consultar_datos_cliente",
            "generar_link_pago",
            "registrar_pago_inmediato",
            "registrar_promesa_pago",
            "escalar_a_humano",
        }
        assert esperadas == set(TOOL_MAP.keys())

    def test_lista_tools_tiene_cinco_elementos(self):
        assert len(tools) == 5

    def test_fases_definidas(self):
        assert FASE_VALIDAR == "VALIDADOR"
        assert FASE_NEGOCIAR == "NEGOCIADOR"
        assert FASE_REGISTRAR == "REGISTRADOR"
        assert FASE_CERRAR == "CERRAR"
