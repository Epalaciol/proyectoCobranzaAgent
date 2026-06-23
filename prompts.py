"""
Compatibilidad con importaciones existentes.

Los prompts ahora viven en prompts.yaml y se cargan via prompt_loader.
En producción AWS, prompt_loader los lee desde AppConfig (sin redespliegue).
"""
from prompt_loader import get_prompt

SYSTEM_PROMPT_VALIDADOR   = get_prompt("VALIDADOR")
SYSTEM_PROMPT_NEGOCIADOR  = get_prompt("NEGOCIADOR")
SYSTEM_PROMPT_REGISTRADOR = get_prompt("REGISTRADOR")
SYSTEM_PROMPT_CIERRE      = get_prompt("CIERRE")
SYSTEM_PROMPT_SUPERVISOR  = get_prompt("SUPERVISOR")
