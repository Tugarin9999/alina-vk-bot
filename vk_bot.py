"""Чат-бот для сообществ ВКонтакте на Bots Long Poll.

Слушает новые сообщения сообщества, собирает историю переписки с каждым
собеседником (по peer_id) и отправляет запрос в GigaChat, затем отвечает
в сообщество. Ответ длиннее лимита ВК разбивается на несколько сообщений.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from collections.abc import Iterator

import vk_api
import requests
from vk_api.bot_longpoll import VkBotEvent, VkBotEventType, VkBotLongPoll
from vk_api.utils import get_random_id

from config import Settings
from giga_client import GigaChatClient, GigaChatClientError

logger = logging.getLogger(__name__)

#: Некоторым сообщениям ВК не хватает ключа text (например, служебные события).
_NON_TEXT = {"", None}

_CHUNK_BREAKPOINTS = ("\n", " ", "-", "")

#: Текст, который бот шлёт при отказе GigaChat.
FALLBACK_REPLY = (
    "Извините, у меня сейчас техническая неполадка. Попробуйте написать чуть позже "
    "или обратитесь к менеджеру на сайте https://zerocoder.ru/ — он обязательно поможет."
)


class VkCommunityBot:
    """Бот, отвечающий на сообщения сообщества ВКонтакте через GigaChat."""

    def __init__(self, settings: Settings, giga: GigaChatClient, system_prompt: str) -> None:
        self._settings = settings
        self._giga = giga
        self._system_prompt = system_prompt
        self._vk = vk_api.VkApi(token=settings.vk_group_token, api_version=settings.vk_api_version)
        self._group_id = self._resolve_group_id()
        self._history: defaultdict[int, deque[dict[str, str]]] = defaultdict(
            lambda: deque(maxlen=settings.max_history_messages)
        )

    # ------------------------------------------------------------------ #
    # Инициализация
    # ------------------------------------------------------------------ #
    def _resolve_group_id(self) -> int:
        response = self._vk.method("groups.getById", {})
        if isinstance(response, dict):
            groups = response.get("items") or response.get("groups") or []
        elif isinstance(response, list):
            groups = response
        else:
            groups = []
        if not groups:
            raise RuntimeError(
                "Не удалось определить ID сообщества. Проверьте VK_GROUP_TOKEN и "
                "права доступа (доступ к сообщениям сообщества)."
            )
        return int(groups[0]["id"])

    # ------------------------------------------------------------------ #
    # Главный цикл
    # ------------------------------------------------------------------ #
    def run(self) -> None:
        logger.info("Бот запущен (group_id=%s). Ожидаю сообщения…", self._group_id)
        while True:
            try:
                longpoll = VkBotLongPoll(self._vk, self._group_id, wait=self._settings.vk_longpoll_wait)
                for event in longpoll.listen():
                    if event.type == VkBotEventType.MESSAGE_NEW:
                        self._handle_message(event)
            except requests.exceptions.ReadTimeout:
                logger.debug("Долгое ожидание Long Poll, переподключаюсь.")
                continue
            except requests.exceptions.ConnectionError as exc:
                logger.warning("Потеряно соединение с VK: %s. Повтор через 5 c.", exc)
                time.sleep(5)
            except KeyboardInterrupt:
                logger.info("Остановлено пользователем.")
                break
            except Exception:  # noqa: BLE001 — гарантируем, что бот не падает.
                logger.exception("Непредвиденная ошибка в цикле Long Poll, повтор через 5 c.")
                time.sleep(5)

    # ------------------------------------------------------------------ #
    # Обработка сообщения
    # ------------------------------------------------------------------ #
    def _handle_message(self, event: VkBotEvent) -> None:
        message = event.message or {}
        text = message.get("text", "")

        # Пропускаем служебные события (добавление в беседу, закрепление и т.п.).
        if message.get("action") is not None or text in _NON_TEXT:
            return

        from_id = message.get("from_id", 0)
        peer_id = int(message.get("peer_id", from_id))

        # Игнорируем сообщения самого сообщества (от него же приходят MESSAGE_NEW).
        if from_id == -self._group_id:
            return

        sender_name = self._sender_name(from_id)

        history = self._history[peer_id]
        history.append({"role": "user", "content": text})

        messages = [{"role": "system", "content": self._system_prompt}]
        messages.extend(history)

        try:
            answer = self._giga.chat(
                messages,
                max_tokens=self._settings.giga_max_tokens,
            ).strip()
        except GigaChatClientError as exc:
            logger.error("Ошибка GigaChat по запросу %r: %s", text, exc)
            self._send(peer_id, FALLBACK_REPLY)
            return
        except Exception:  # noqa: BLE001
            logger.exception("Непредвиденная ошибка при вызове GigaChat.")
            self._send(peer_id, FALLBACK_REPLY)
            return

        if not answer:
            self._send(peer_id, FALLBACK_REPLY)
            return

        history.append({"role": "assistant", "content": answer})
        logger.info("Ответил %s (peer_id=%s) на: %r", sender_name, peer_id, text[:80])
        self._send(peer_id, answer)

    def _sender_name(self, from_id: int) -> str:
        try:
            user = self._vk.method("users.get", {"user_ids": from_id})
            if user:
                return f"{user[0].get('first_name', '')} {user[0].get('last_name', '')}".strip()
        except Exception:  # noqa: BLE001 — имя не критично.
            pass
        return str(from_id)

    # ------------------------------------------------------------------ #
    # Отправка ответа
    # ------------------------------------------------------------------ #
    def _send(self, peer_id: int, text: str) -> None:
        for chunk in self._chunk_text(text, self._settings.max_reply_length):
            self._vk.method(
                "messages.send",
                {"peer_id": peer_id, "message": chunk, "random_id": get_random_id()},
            )
            time.sleep(0.2)

    @staticmethod
    def _chunk_text(text: str, limit: int) -> Iterator[str]:
        """Разбивает длинный текст на части не длиннее ``limit`` символов."""
        text = text.strip()
        if not text:
            return
        if len(text) <= limit:
            yield text
            return

        buffer = ""
        for paragraph in text.split("\n"):
            candidate = f"{buffer}\n{paragraph}".strip() if buffer else paragraph
            if len(candidate) <= limit:
                buffer = candidate
                continue
            if buffer:
                yield buffer
                buffer = ""
            while len(paragraph) > limit:
                cut = limit
                for bc in _CHUNK_BREAKPOINTS:
                    marker = paragraph.rfind(bc, 0, limit)
                    if marker > 0:
                        cut = marker + (1 if bc == " " else 0)
                        break
                yield paragraph[:cut]
                paragraph = paragraph[cut:].strip()
                if not paragraph:
                    break
            buffer = paragraph
        if buffer:
            yield buffer