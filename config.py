"""Конфигурация проекта: чтение настроек из переменных окружения и файла .env.

Все секреты (токен сообщества ВК, ключ авторизации GigaChat) передаются
только через переменные окружения / файл ``.env`` и никогда не хранятся в коде.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

#: Корень проекта (директория, где лежит этот файл).
BASE_DIR = Path(__file__).resolve().parent

#: Файл с секретами. Загружается, если существует; в Git не попадает.
ENV_PATH = BASE_DIR / ".env"

load_dotenv(ENV_PATH)


def _get_str(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _get_float(name: str, default: float | None) -> float | None:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "да"}


@dataclass
class Settings:
    """Настройки приложения, собранные из переменных окружения."""

    # VK
    vk_group_token: str = ""
    vk_api_version: str = "5.199"
    vk_longpoll_wait: int = 25

    # GigaChat
    giga_auth_key: str = ""
    giga_scope: str = "GIGACHAT_API_PERS"
    giga_model: str = "GigaChat-2-Pro"
    giga_api_base: str = "https://api.giga.chat/v1"
    giga_auth_url: str = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    giga_ca_bundle_path: str | None = None
    giga_verify_ssl: bool = True
    giga_timeout: float = 60.0
    giga_temperature: float | None = None
    giga_max_tokens: int = 1200

    # Поведение бота
    max_history_messages: int = 12
    max_reply_length: int = 3800
    knowledge_top_k: int | None = None
    knowledge_dir: str | None = None

    @property
    def knowledge_directory(self) -> Path:
        return Path(self.knowledge_dir) if self.knowledge_dir else BASE_DIR / "knowledge_base"


def load_settings() -> Settings:
    """Читает ``.env``/окружение и возвращает настройки (или кидает ошибку)."""
    vk_token = _get_str("VK_GROUP_TOKEN")
    if not vk_token:
        raise ValueError(
            "Не задан VK_GROUP_TOKEN. Добавьте его в файл .env "
            "(см. .env.example и README.md)."
        )

    giga_key = _get_str("GIGACHAT_AUTH_KEY")
    if not giga_key:
        raise ValueError(
            "Не задан GIGACHAT_AUTH_KEY. Добавьте его в файл .env "
            "(см. .env.example и README.md)."
        )

    return Settings(
        vk_group_token=vk_token,
        vk_api_version=_get_str("VK_API_VERSION", "5.199") or "5.199",
        vk_longpoll_wait=_get_int("VK_LONGPOLL_WAIT", 25),
        giga_auth_key=giga_key,
        giga_scope=_get_str("GIGACHAT_SCOPE", "GIGACHAT_API_PERS") or "GIGACHAT_API_PERS",
        giga_model=_get_str("GIGACHAT_MODEL", "GigaChat-2-Pro") or "GigaChat-2-Pro",
        giga_api_base=_get_str("GIGACHAT_API_BASE", "https://api.giga.chat/v1")
        or "https://api.giga.chat/v1",
        giga_auth_url=(
            _get_str("GIGACHAT_AUTH_URL")
            or "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
        ),
        giga_ca_bundle_path=_get_str("GIGACHAT_CA_BUNDLE_PATH"),
        giga_verify_ssl=_get_bool("GIGACHAT_VERIFY_SSL", True),
        giga_timeout=_get_float("GIGACHAT_TIMEOUT", 60.0) or 60.0,
        giga_temperature=_get_float("GIGACHAT_TEMPERATURE", None),
        giga_max_tokens=_get_int("GIGACHAT_MAX_TOKENS", 1200),
        max_history_messages=_get_int("MAX_HISTORY_MESSAGES", 12),
        max_reply_length=_get_int("MAX_REPLY_LENGTH", 3800),
        knowledge_top_k=_get_int("KNOWLEDGE_TOP_K", 0) or None,
        knowledge_dir=_get_str("KNOWLEDGE_DIR"),
    )