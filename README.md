# Proyecto Ágil — Sistema Multi-Agente de Gestión de Cobranza

[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white)](https://python.org)
[![LangChain](https://img.shields.io/badge/LangChain-0.3-1C3C3C)](https://langchain.com)
[![Ollama](https://img.shields.io/badge/Ollama-Llama_3.1-000000)](https://ollama.com)
[![Tests](https://img.shields.io/badge/Tests-14_passing-brightgreen)](tests/)

Sistema multi-agente de IA para gestión de cobranza vía WhatsApp. Arquitectura serverless 100% en AWS.

**Documentación completa:** [`docs/index.html`](docs/index.html) — narrativa de negocio, métricas, arquitectura, visión futura y supuestos.

**Diseño técnico detallado:** [`doc/arquitectura_aws.md`](doc/arquitectura_aws.md)

---

## Ejecutar el prototipo local

**Prerrequisitos:** Python 3.10+ y [Ollama](https://ollama.com)

```bash
# 1. Instalar modelo (solo la primera vez — ~4.7 GB)
ollama pull llama3.1

# 2. Dependencias
python3 -m venv estebantest && source estebantest/bin/activate
pip install -r requirements.txt

# 3. Lanzar (Ollama debe estar corriendo)
streamlit run app.py
```

Abre `http://localhost:8501`. Si ves `[Errno 61] Connection refused`, ejecuta `ollama serve` en otra terminal.

## Correr los tests

No requieren Ollama.

```bash
pytest tests/ -v   # 14 tests passing
```

## Estructura

```
llaTechAssesment/
├── app.py              # Interfaz Streamlit (simulador WhatsApp)
├── multi_agent.py      # Orquestador Multi-Agente + Tools
├── prompts.py          # System prompts de los 4 agentes
├── mock_data.json      # 5 perfiles de cliente para pruebas
├── requirements.txt
├── tests/
│   └── test_agents.py  # 14 tests unitarios
├── doc/
│   └── arquitectura_aws.md   # Diseño técnico completo
└── docs/
    └── index.html      # Documentación ejecutable (abrir en navegador)
```

## Perfiles de prueba incluidos

| Teléfono | Cliente | Deuda | Caso |
|---|---|---|---|
| +50712345678 | Juan Pérez | $150 | Caso feliz — acepta pagar |
| +50787654321 | María Gómez | $45.50 | Cliente enojado — escala |
| +50755555555 | Carlos Rodríguez | $800 | Pide condonación — bloqueado |
| +50799999999 | Ana Sánchez | $25 | Pago inmediato |
| +50766666666 | Roberto Castillo | $320 | Alto riesgo |

## Variables de entorno

```bash
OLLAMA_MODEL=llama3.2 streamlit run app.py   # cambiar modelo
```
