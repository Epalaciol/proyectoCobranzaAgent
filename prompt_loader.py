"""
Carga system prompts desde YAML (local/dev) o AWS AppConfig (producción).

Uso:
    from prompt_loader import get_prompt
    system_prompt = get_prompt("NEGOCIADOR")

Variables de entorno (producción AWS):
    APPCONFIG_APP       — nombre de la aplicación en AppConfig
    APPCONFIG_ENV       — entorno (ej: "production")
    APPCONFIG_PROFILE   — perfil de configuración (ej: "prompts")
    AWS_REGION          — región AWS (default: us-east-1)

Sin esas variables, el loader lee de prompts.yaml en el mismo directorio.
AppConfig se cachea 60 segundos para evitar latencia en cada invocación.
"""

import os
import time
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Caché en memoria (compartida por el proceso Lambda / Streamlit)
# ──────────────────────────────────────────────────────────────────────────────
_cache: dict[str, str] = {}
_cache_expiry: float = 0.0
CACHE_TTL_SECONDS: float = float(os.getenv("PROMPT_CACHE_TTL", "60"))

_YAML_PATH = Path(__file__).parent / "prompts.yaml"


# ──────────────────────────────────────────────────────────────────────────────
# Detección de entorno
# ──────────────────────────────────────────────────────────────────────────────

def _is_appconfig_env() -> bool:
    return bool(os.getenv("APPCONFIG_APP"))


# ──────────────────────────────────────────────────────────────────────────────
# Lectura desde YAML (desarrollo local)
# ──────────────────────────────────────────────────────────────────────────────

def _load_yaml() -> dict[str, str]:
    try:
        import yaml  # PyYAML — sólo requerido cuando se usa el loader
    except ImportError as exc:
        raise ImportError(
            "PyYAML no está instalado. Ejecutá: pip install pyyaml"
        ) from exc

    with _YAML_PATH.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)

    prompts: dict = data.get("prompts", {})
    if not prompts:
        raise ValueError(f"prompts.yaml no contiene la clave 'prompts': {_YAML_PATH}")

    logger.debug("Prompts cargados desde YAML (%d claves)", len(prompts))
    return {k: v.strip() for k, v in prompts.items()}


# ──────────────────────────────────────────────────────────────────────────────
# Lectura desde AWS AppConfig (producción)
# ──────────────────────────────────────────────────────────────────────────────

def _load_appconfig() -> dict[str, str]:
    import boto3
    import yaml

    app     = os.environ["APPCONFIG_APP"]
    env     = os.environ["APPCONFIG_ENV"]
    profile = os.environ["APPCONFIG_PROFILE"]
    region  = os.getenv("AWS_REGION", "us-east-1")

    client = boto3.client("appconfigdata", region_name=region)

    session = client.start_configuration_session(
        ApplicationIdentifier=app,
        EnvironmentIdentifier=env,
        ConfigurationProfileIdentifier=profile,
    )
    token = session["InitialConfigurationToken"]

    response = client.get_latest_configuration(ConfigurationToken=token)
    raw = response["Configuration"].read()

    if not raw:
        logger.warning("AppConfig devolvió contenido vacío — usando caché anterior si existe")
        return {}

    data = yaml.safe_load(raw)
    prompts: dict = data.get("prompts", {})
    logger.info("Prompts cargados desde AppConfig (%d claves)", len(prompts))
    return {k: v.strip() for k, v in prompts.items()}


# ──────────────────────────────────────────────────────────────────────────────
# API pública
# ──────────────────────────────────────────────────────────────────────────────

def _refresh_cache() -> None:
    global _cache, _cache_expiry
    try:
        if _is_appconfig_env():
            fresh = _load_appconfig()
        else:
            fresh = _load_yaml()

        if fresh:               # no sobreescribir con respuesta vacía de AppConfig
            _cache = fresh
        _cache_expiry = time.monotonic() + CACHE_TTL_SECONDS
    except Exception:
        logger.exception("Error cargando prompts — se mantiene caché anterior")


def get_prompt(key: str) -> str:
    """
    Retorna el system prompt para la clave dada (ej: "NEGOCIADOR").

    - En desarrollo (sin APPCONFIG_APP): lee prompts.yaml, sin caché.
    - En producción (con APPCONFIG_APP): lee AppConfig, cachea 60s.

    Lanza KeyError si la clave no existe en el archivo de configuración.
    """
    if not _is_appconfig_env():
        # En local siempre releer el archivo para reflejar ediciones al instante
        prompts = _load_yaml()
    else:
        if not _cache or time.monotonic() > _cache_expiry:
            _refresh_cache()
        prompts = _cache

    if key not in prompts:
        available = list(prompts.keys())
        raise KeyError(
            f"Prompt '{key}' no encontrado. Claves disponibles: {available}"
        )

    return prompts[key]


def reload_prompts() -> None:
    """Fuerza recarga inmediata ignorando el TTL. Útil en tests o hot-reload."""
    global _cache_expiry
    _cache_expiry = 0.0
    _refresh_cache()
