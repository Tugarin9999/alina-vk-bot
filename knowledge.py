"""Загрузка базы знаний Zerocoder из markdown-файлов.

Механизм работы:
1. Все файлы ``*.md`` из директории базы знаний читаются и разбиваются
   на секции по заголовкам уровня ``##``.
2. Для каждой секции считаются ключевые слова (заголовки и значимые слова).
3. По запросу пользователя можно либо подставить базу целиком
   (``retrieve(..., top_k=None)``), либо выбрать ``top_k`` наиболее
   релевантных секций по совпадению ключевых слов.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_STOPWORDS: frozenset[str] = frozenset(
    {
        "в", "на", "с", "со", "и", "а", "но", "или", "не", "ни", "для", "от", "до",
        "по", "из", "за", "о", "об", "у", "к", "ко", "во", "это", "что", "как", "так",
        "же", "бы", "же", "его", "ее", "их", "мне", "меня", "тебе", "вас", "вы", "ты",
        "мы", "они", "он", "она", "кто", "где", "когда", "почему", "сколько", "быть",
        "есть", "можно", "нужно", "думаю",
    }
)


@dataclass(frozen=True)
class Section:
    """Секция базы знаний: заголовок и текст."""

    heading: str
    text: str

    @property
    def keywords(self) -> set[str]:
        return _keywords(self.heading) | _keywords(self.text)


def _keywords(text: str) -> set[str]:
    words = re.findall(r"[а-яёa-z0-9]+", text.lower())
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS}


class KnowledgeBase:
    """База знаний, загруженная из markdown-файлов директории."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.sections: list[Section] = []
        self._load()

    def _load(self) -> None:
        files = sorted(self.directory.glob("*.md"))
        if not files:
            raise FileNotFoundError(
                f"В директории базы знаний '{self.directory}' нет файлов *.md"
            )
        for path in files:
            text = path.read_text(encoding="utf-8")
            self.sections.extend(self._parse(text))

    @staticmethod
    def _parse(text: str) -> list[Section]:
        sections: list[Section] = []
        current_heading = ""
        current_lines: list[str] = []
        for raw_line in text.splitlines():
            if raw_line.startswith("## "):
                if current_heading or any(current_lines):
                    sections.append(
                        Section(current_heading, "\n".join(current_lines).strip())
                    )
                current_heading = raw_line[3:].strip()
                current_lines = []
            else:
                current_lines.append(raw_line)
        if current_heading or any(current_lines):
            sections.append(Section(current_heading, "\n".join(current_lines).strip()))
        return sections

    def as_context(self) -> str:
        """Возвращает полную базу знаний одним текстом для системного промпта."""
        return "\n\n".join(
            f"## {s.heading}\n{s.text}" if s.heading else s.text for s in self.sections
        )

    def retrieve(self, query: str, top_k: int = 5) -> list[Section]:
        """Возвращает top_k секций по совпадению ключевых слов с запросом."""
        if not query.strip():
            return self.sections
        q_words = _keywords(query)
        scored = [
            (len(q_words & section.keywords), -len(section.text), section)
            for section in self.sections
        ]
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        best = [item for item in scored if item[0] > 0][:top_k]
        if not best:
            return []
        return [section for _, _, section in best]

    def context_for(self, query: str, top_k: int | None = None) -> str:
        """База знаний для запроса.

        Если ``top_k`` задан и нашлись релевантные секции — возвращает только их,
        иначе возвращает полную базу.
        """
        if top_k:
            best = self.retrieve(query, top_k=top_k)
            if best:
                return "\n\n".join(
                    f"## {s.heading}\n{s.text}" if s.heading else s.text for s in best
                )
        return self.as_context()