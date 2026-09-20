"""Точка входа чат-бота «Алина» для сообщества ВКонтакте.

Запуск:  python main.py
"""

from __future__ import annotations

import logging

from config import load_settings
from giga_client import GigaChatClient
from knowledge import KnowledgeBase
from prompts import build_system_prompt
from vk_bot import VkCommunityBot


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main() -> None:
    _setup_logging()
    settings = load_settings()

    knowledge = KnowledgeBase(settings.knowledge_directory)
    system_prompt = build_system_prompt(knowledge.as_context())

    giga = GigaChatClient(settings)
    bot = VkCommunityBot(settings, giga, system_prompt)
    try:
        bot.run()
    finally:
        giga.close()


if __name__ == "__main__":
    main()