import json
import os
from copy import deepcopy
from typing import Any, Dict

from ai_model_registry import DEFAULT_AI_MODEL, DEFAULT_AI_PROVIDER
from paths import BASE_PATH

SYSTEM_DATA_DIR = os.path.join(BASE_PATH, "System_Data")
SYSTEM_CONFIG_FILE = os.path.join(SYSTEM_DATA_DIR, "config.json")
FARM_DB_FILE = os.path.join(SYSTEM_DATA_DIR, "farm_data.db")
LEGACY_CONFIG_FILE = os.path.join(BASE_PATH, "config_dao_dien.json")

_DEFAULT_STRUCTURED_CONFIG: Dict[str, Any] = {
    "system": {
        "ffmpeg_path": "",
        "server_port": 8000,
        "debug_mode": False,
    },
    "video_defaults": {
        "resolution": "1080x1920",
        "fps": 30,
        "max_duration_seconds": 60,
    },
    "api_keys": {
        "groq_ai": "",
        "kie_ai": "",
        "openrouter_ai": "",
        "telegram_bot": "",
        "apify_token": "",
    },
    "ai_settings": {
        "provider": DEFAULT_AI_PROVIDER,
        "model": DEFAULT_AI_MODEL,
    },
    "paths": {
        "font_path": "",
        "drive_creds": "",
        "client_secret": "",
        "icloud_path": "",
    },
    "runtime": {},
}


def ensure_system_data_dir() -> str:
    os.makedirs(SYSTEM_DATA_DIR, exist_ok=True)
    return SYSTEM_DATA_DIR


def _read_json_file(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_json_file(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data or {}, handle, indent=4, ensure_ascii=False)


def _merge_dict(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in (patch or {}).items():
        if isinstance(base.get(key), dict) and isinstance(value, dict):
            _merge_dict(base[key], value)
        else:
            base[key] = value
    return base


def _structured_from_legacy(legacy: Dict[str, Any]) -> Dict[str, Any]:
    data = deepcopy(_DEFAULT_STRUCTURED_CONFIG)
    data["system"]["ffmpeg_path"] = str(legacy.get("ffmpeg_path", "") or "")
    data["system"]["server_port"] = int(legacy.get("server_port", 8000) or 8000)
    data["system"]["debug_mode"] = bool(legacy.get("debug_mode", False))

    data["video_defaults"]["resolution"] = str(legacy.get("resolution", "1080x1920") or "1080x1920")
    data["video_defaults"]["fps"] = int(legacy.get("fps", 30) or 30)
    data["video_defaults"]["max_duration_seconds"] = int(legacy.get("max_duration_seconds", 60) or 60)

    data["api_keys"]["groq_ai"] = str(legacy.get("groq_key", "") or "")
    data["api_keys"]["kie_ai"] = str(legacy.get("kie_key", "") or "")
    data["api_keys"]["openrouter_ai"] = str(legacy.get("openrouter_key", "") or "")
    data["api_keys"]["telegram_bot"] = str(legacy.get("telegram_bot_token", "") or "")
    data["api_keys"]["apify_token"] = str(legacy.get("apify_token", "") or "")

    data["ai_settings"]["provider"] = str(legacy.get("ai_provider", DEFAULT_AI_PROVIDER) or DEFAULT_AI_PROVIDER)
    data["ai_settings"]["model"] = str(legacy.get("ai_model", DEFAULT_AI_MODEL) or DEFAULT_AI_MODEL)

    data["paths"]["font_path"] = str(legacy.get("font_path", "") or "")
    data["paths"]["drive_creds"] = str(legacy.get("drive_creds", "") or "")
    data["paths"]["client_secret"] = str(legacy.get("client_secret", "") or "")
    data["paths"]["icloud_path"] = str(legacy.get("icloud_path", "") or "")

    runtime = dict(legacy)
    data["runtime"] = runtime
    return data


def _flat_from_structured(structured: Dict[str, Any]) -> Dict[str, Any]:
    system = structured.get("system", {}) or {}
    video_defaults = structured.get("video_defaults", {}) or {}
    api_keys = structured.get("api_keys", {}) or {}
    ai_settings = structured.get("ai_settings", {}) or {}
    paths = structured.get("paths", {}) or {}
    runtime = dict(structured.get("runtime", {}) or {})

    runtime["ffmpeg_path"] = str(system.get("ffmpeg_path", runtime.get("ffmpeg_path", "")) or "")
    runtime["server_port"] = int(system.get("server_port", runtime.get("server_port", 8000)) or 8000)
    runtime["debug_mode"] = bool(system.get("debug_mode", runtime.get("debug_mode", False)))
    runtime["resolution"] = str(video_defaults.get("resolution", runtime.get("resolution", "1080x1920")) or "1080x1920")
    runtime["fps"] = int(video_defaults.get("fps", runtime.get("fps", 30)) or 30)
    runtime["max_duration_seconds"] = int(video_defaults.get("max_duration_seconds", runtime.get("max_duration_seconds", 60)) or 60)
    runtime["groq_key"] = str(api_keys.get("groq_ai", runtime.get("groq_key", "")) or "")
    runtime["kie_key"] = str(api_keys.get("kie_ai", runtime.get("kie_key", "")) or "")
    runtime["openrouter_key"] = str(api_keys.get("openrouter_ai", runtime.get("openrouter_key", "")) or "")
    runtime["telegram_bot_token"] = str(api_keys.get("telegram_bot", runtime.get("telegram_bot_token", "")) or "")
    runtime["apify_token"] = str(api_keys.get("apify_token", runtime.get("apify_token", "")) or "")
    runtime["ai_provider"] = str(ai_settings.get("provider", runtime.get("ai_provider", DEFAULT_AI_PROVIDER)) or DEFAULT_AI_PROVIDER)
    runtime["ai_model"] = str(ai_settings.get("model", runtime.get("ai_model", DEFAULT_AI_MODEL)) or DEFAULT_AI_MODEL)
    runtime["font_path"] = str(paths.get("font_path", runtime.get("font_path", "")) or "")
    runtime["drive_creds"] = str(paths.get("drive_creds", runtime.get("drive_creds", "")) or "")
    runtime["client_secret"] = str(paths.get("client_secret", runtime.get("client_secret", "")) or "")
    runtime["icloud_path"] = str(paths.get("icloud_path", runtime.get("icloud_path", "")) or "")
    return runtime


def load_config() -> Dict[str, Any]:
    ensure_system_data_dir()
    legacy = _read_json_file(LEGACY_CONFIG_FILE)
    structured = deepcopy(_DEFAULT_STRUCTURED_CONFIG)
    if legacy:
        _merge_dict(structured, _structured_from_legacy(legacy))

    stored = _read_json_file(SYSTEM_CONFIG_FILE)
    needs_save = False
    if stored:
        _merge_dict(structured, stored)
    else:
        needs_save = True
    
    # Ensure all default fields exist (for backwards compatibility)
    if "ai_settings" in structured:
        if "provider" not in structured["ai_settings"]:
            structured["ai_settings"]["provider"] = DEFAULT_AI_PROVIDER
            needs_save = True
        if "model" not in structured["ai_settings"]:
            structured["ai_settings"]["model"] = DEFAULT_AI_MODEL
            needs_save = True
    
    # Save if needed to update file with missing fields
    if needs_save:
        _write_json_file(SYSTEM_CONFIG_FILE, structured)

    return _flat_from_structured(structured)


def save_config(flat_config: Dict[str, Any]) -> Dict[str, Any]:
    ensure_system_data_dir()
    current_structured = deepcopy(_DEFAULT_STRUCTURED_CONFIG)
    stored = _read_json_file(SYSTEM_CONFIG_FILE)
    if stored:
        _merge_dict(current_structured, stored)

    flat = dict(flat_config or {})
    current_structured["system"]["ffmpeg_path"] = str(flat.get("ffmpeg_path", current_structured["system"].get("ffmpeg_path", "")) or "")
    current_structured["system"]["server_port"] = int(flat.get("server_port", current_structured["system"].get("server_port", 8000)) or 8000)
    current_structured["system"]["debug_mode"] = bool(flat.get("debug_mode", current_structured["system"].get("debug_mode", False)))

    current_structured["video_defaults"]["resolution"] = str(flat.get("resolution", current_structured["video_defaults"].get("resolution", "1080x1920")) or "1080x1920")
    current_structured["video_defaults"]["fps"] = int(flat.get("fps", current_structured["video_defaults"].get("fps", 30)) or 30)
    current_structured["video_defaults"]["max_duration_seconds"] = int(flat.get("max_duration_seconds", current_structured["video_defaults"].get("max_duration_seconds", 60)) or 60)

    current_structured["api_keys"]["groq_ai"] = str(flat.get("groq_key", current_structured["api_keys"].get("groq_ai", "")) or "")
    current_structured["api_keys"]["kie_ai"] = str(flat.get("kie_key", current_structured["api_keys"].get("kie_ai", "")) or "")
    current_structured["api_keys"]["openrouter_ai"] = str(flat.get("openrouter_key", current_structured["api_keys"].get("openrouter_ai", "")) or "")
    current_structured["api_keys"]["telegram_bot"] = str(flat.get("telegram_bot_token", current_structured["api_keys"].get("telegram_bot", "")) or "")
    current_structured["api_keys"]["apify_token"] = str(flat.get("apify_token", current_structured["api_keys"].get("apify_token", "")) or "")

    current_structured["ai_settings"]["provider"] = str(flat.get("ai_provider", current_structured["ai_settings"].get("provider", DEFAULT_AI_PROVIDER)) or DEFAULT_AI_PROVIDER)
    current_structured["ai_settings"]["model"] = str(flat.get("ai_model", current_structured["ai_settings"].get("model", DEFAULT_AI_MODEL)) or DEFAULT_AI_MODEL)

    current_structured["paths"]["font_path"] = str(flat.get("font_path", current_structured["paths"].get("font_path", "")) or "")
    current_structured["paths"]["drive_creds"] = str(flat.get("drive_creds", current_structured["paths"].get("drive_creds", "")) or "")
    current_structured["paths"]["client_secret"] = str(flat.get("client_secret", current_structured["paths"].get("client_secret", "")) or "")
    current_structured["paths"]["icloud_path"] = str(flat.get("icloud_path", current_structured["paths"].get("icloud_path", "")) or "")

    current_structured["runtime"] = dict(flat)

    _write_json_file(SYSTEM_CONFIG_FILE, current_structured)
    legacy_flat = _flat_from_structured(current_structured)
    _write_json_file(LEGACY_CONFIG_FILE, legacy_flat)
    return legacy_flat
