from copy import deepcopy
from typing import Any, Dict, List

DEFAULT_AI_PROVIDER = "auto"
DEFAULT_AI_MODEL = "gemini-2.5-flash"

_MODEL_CATALOG: List[Dict[str, Any]] = [
    {
        "id": "gemini-2.5-flash",
        "label": "Gemini 2.5 Flash",
        "providers": ["kie", "openrouter"],
        "openrouter_model": "google/gemini-2.5-flash",
        "kie_endpoint": "https://api.kie.ai/gemini-2.5-flash/v1/chat/completions",
        "is_free": False,
    },
    {
        "id": "gemini-3-flash",
        "label": "Gemini 3 Flash",
        "providers": ["kie", "openrouter"],
        "openrouter_model": "google/gemini-3-flash",
        "kie_endpoint": "https://api.kie.ai/gemini-3-flash/v1/chat/completions",
        "is_free": False,
    },
    {
        "id": "google/gemma-4-31b-it:free",
        "label": "Gemma 4 31B (Free)",
        "providers": ["openrouter"],
        "openrouter_model": "google/gemma-4-31b-it:free",
        "kie_endpoint": "",
        "is_free": True,
    },
    {
        "id": "google/gemini-flash-1.5-8b",
        "label": "Gemini Flash 1.5 8B",
        "providers": ["openrouter"],
        "openrouter_model": "google/gemini-flash-1.5-8b",
        "kie_endpoint": "",
        "is_free": False,
    },
    {
        "id": "openai/gpt-4o-mini",
        "label": "GPT-4o Mini",
        "providers": ["openrouter"],
        "openrouter_model": "openai/gpt-4o-mini",
        "kie_endpoint": "",
        "is_free": False,
    },
    {
        "id": "anthropic/claude-3.5-sonnet",
        "label": "Claude 3.5 Sonnet",
        "providers": ["openrouter"],
        "openrouter_model": "anthropic/claude-3.5-sonnet",
        "kie_endpoint": "",
        "is_free": False,
    },
]


def get_ai_models_catalog() -> List[Dict[str, Any]]:
    return deepcopy(_MODEL_CATALOG)


def get_ai_model_ids() -> List[str]:
    return [item["id"] for item in _MODEL_CATALOG]


def normalize_ai_provider(provider: str) -> str:
    clean = str(provider or DEFAULT_AI_PROVIDER).strip().lower()
    return clean if clean in {"auto", "kie", "openrouter"} else DEFAULT_AI_PROVIDER


def supports_provider(model_id: str, provider: str) -> bool:
    model = str(model_id or "").strip()
    clean_provider = normalize_ai_provider(provider)
    if clean_provider == "auto":
        return True
    for item in _MODEL_CATALOG:
        if item["id"] == model:
            return clean_provider in set(item.get("providers") or [])
    return False


def normalize_ai_model(model_id: str, provider: str = "auto") -> str:
    model = str(model_id or "").strip()
    provider_clean = normalize_ai_provider(provider)

    if model in get_ai_model_ids() and supports_provider(model, provider_clean):
        return model

    if provider_clean == "kie":
        for item in _MODEL_CATALOG:
            if "kie" in set(item.get("providers") or []):
                return str(item["id"])
    if provider_clean == "openrouter":
        for item in _MODEL_CATALOG:
            if "openrouter" in set(item.get("providers") or []):
                return str(item["id"])

    return DEFAULT_AI_MODEL


def to_openrouter_model(model_id: str) -> str:
    model = str(model_id or "").strip()
    for item in _MODEL_CATALOG:
        if item["id"] == model:
            return str(item.get("openrouter_model") or model)
    return str(model or DEFAULT_AI_MODEL)


def get_kie_endpoint(model_id: str) -> str:
    model = str(model_id or "").strip()
    for item in _MODEL_CATALOG:
        if item["id"] == model:
            return str(item.get("kie_endpoint") or "")
    return ""
