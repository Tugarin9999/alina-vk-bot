"""Клиент GigaChat API, реализованный по официальной документации.

Поток работы (по документации GigaChat API):
1. Получение access-токена: ``POST /api/v2/oauth``.
   - Заголовок ``Authorization: Basic <ключ_авторизации>`` (ключ из Studio).
   - Заголовок ``RqUID`` — уникальный UUID запроса.
   - Тело: ``scope`` (обычно ``GIGACHAT_API_PERS``).
   - Токен действителен 30 минут, поэтому клиент кэширует его и обновляет
     автоматически (по времени истечения или после ответа 401).
2. Генерация текста: ``POST /v1/chat/completions``.
   - Заголовок ``Authorization: Bearer <access_token>``.
   - Тело: модель и список сообщений (как у OpenAI-совместимых API).

Токены и ключи никогда не логируются и не выводятся в консоль.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

import requests

from config import Settings

logger = logging.getLogger(__name__)

#: Запас времени до истечения токена (в секундах), чтобы обновить его заранее.
TOKEN_REFRESH_MARGIN = 60

#: Код состояния, при котором стоит попробовать запросить свежий токен и повторить запрос.
TOKEN_EXPIRED_HTTP_CODES = {401, 403}


class GigaChatClientError(RuntimeError):
    """Ошибка при работе с GigaChat API."""


class GigaChatClient:
    """Лёгкий клиент GigaChat API (OAuth-токен + chat/completions)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._session = requests.Session()
        self._session.verify = settings.giga_verify_ssl
        if settings.giga_ca_bundle_path:
            ca = settings.giga_ca_bundle_path.strip()
            if not ca:
                raise GigaChatClientError("Путь к сертификату GIGACHAT_CA_BUNDLE_PATH пуст.")
            self._session.verify = ca

        self._api_base = settings.giga_api_base.rstrip("/")
        # Эндпоинт OAuth-токена — отдельный сервер авторизации (port 9443), его
        # адрес настраивается отдельно и по документации по умолчанию такой:
        self._auth_url = settings.giga_auth_url

        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    # ------------------------------------------------------------------ #
    # Авторизация
    # ------------------------------------------------------------------ #
    def _get_access_token(self) -> str:
        now = time.time()
        if self._access_token and now < self._token_expires_at - TOKEN_REFRESH_MARGIN:
            return self._access_token

        logger.info("Запрашиваю новый access-токен GigaChat…")
        headers = {
            "Authorization": f"Basic {self._settings.giga_auth_key}",
            "RqUID": str(uuid.uuid4()),
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "zerocoder-vk-bot/1.0",
        }
        data = {"scope": self._settings.giga_scope}

        try:
            response = self._session.post(
                self._auth_url, headers=headers, data=data, timeout=self._settings.giga_timeout
            )
            response.raise_for_status()
            payload = response.json()
        except requests.exceptions.SSLError as exc:
            raise GigaChatClientError(
                "Ошибка проверки SSL-сертификата при запросе токена GigaChat. "
                "Если используется корневой сертификат Минцифры, укажите путь к нему "
                "в GIGACHAT_CA_BUNDLE_PATH, либо отключите проверку GIGACHAT_VERIFY_SSL=false "
                "(только для локальных тестов)."
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise GigaChatClientError(
                f"Не удалось получить токен GigaChat: {exc}"
            ) from exc

        token = payload.get("access_token")
        if not token:
            raise GigaChatClientError(
                "Ответ GigaChat не содержит access_token. Проверьте GIGACHAT_AUTH_KEY "
                "и GIGACHAT_SCOPE."
            )

        expires_at = payload.get("expires_at")
        if isinstance(expires_at, (int, float)):
            # Значение может быть в миллисекундах (тринадцатизначное).
            if expires_at > 1_000_000_000_000:
                expires_at /= 1000.0
            self._token_expires_at = float(expires_at)
        else:
            # По документации токен действует 30 минут.
            self._token_expires_at = now + 30 * 60

        self._access_token = token
        return token

    def _refresh_token(self) -> None:
        self._access_token = None
        self._token_expires_at = 0.0

    # ------------------------------------------------------------------ #
    # Генерация ответа
    # ------------------------------------------------------------------ #
    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Отправляет сообщения в модель и возвращает текст ответа."""
        if not messages:
            raise GigaChatClientError("Передан пустой список сообщений.")

        payload: dict[str, Any] = {
            "model": model or self._settings.giga_model,
            "messages": messages,
        }
        temp = self._settings.giga_temperature if temperature is None else temperature
        if temp is not None:
            payload["temperature"] = temp
        if max_tokens is not None and max_tokens > 0:
            payload["max_tokens"] = max_tokens

        url = f"{self._api_base}/chat/completions"
        token = self._get_access_token()
        for attempt in (1, 2):  # первый запрос + повтор после обновления токена
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-Request-ID": str(uuid.uuid4()),
                "User-Agent": "zerocoder-vk-bot/1.0",
            }
            try:
                response = self._session.post(
                    url, json=payload, headers=headers, timeout=self._settings.giga_timeout
                )
            except requests.exceptions.SSLError as exc:
                raise GigaChatClientError(
                    "Ошибка проверки SSL-сертификата при запросе к GigaChat. "
                    "Укажите GIGACHAT_CA_BUNDLE_PATH или отключите проверку сертификата "
                    "(GIGACHAT_VERIFY_SSL=false) только для локальных тестов."
                ) from exc
            except requests.exceptions.RequestException as exc:
                raise GigaChatClientError(f"Ошибка запроса к GigaChat: {exc}") from exc

            if response.status_code in TOKEN_EXPIRED_HTTP_CODES and attempt == 1:
                logger.warning("Токен GigaChat истёк (HTTP %s), обновляю…", response.status_code)
                self._refresh_token()
                token = self._get_access_token()
                continue

            if response.status_code >= 400:
                raise GigaChatClientError(
                    f"GigaChat вернул ошибку HTTP {response.status_code}: "
                    f"{response.text[:500]}"
                )

            data = response.json()
            content = self._extract_content(data)
            if content is None:
                raise GigaChatClientError(
                    f"Не удалось извлечь текст ответа из ответа GigaChat: {data}"
                )
            return content

        raise GigaChatClientError("Не удалось получить ответ от GigaChat после обновления токена.")

    @staticmethod
    def _extract_content(data: dict[str, Any]) -> str | None:
        """Извлекает текст ответа из разных вариантов схемы ответа."""
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message") or {}
            content = message.get("content")
            if isinstance(content, str):
                return content

        messages = data.get("messages")
        if isinstance(messages, list) and messages:
            content = messages[0].get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                # v2 API: контент может быть массивом частей.
                text_parts = [
                    part.get("text")
                    for part in content
                    if isinstance(part, dict) and isinstance(part.get("text"), str)
                ]
                if text_parts:
                    return "\n".join(text_parts)

        return None

    def close(self) -> None:
        self._session.close()