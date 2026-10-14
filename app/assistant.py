"""Логика диалога без зависимости от Telegram и HTTP."""

import asyncio
from contextlib import asynccontextmanager

from app.prompts import PROMPTS

ALLOWED_TEMPERATURES = {"0.0": 0.0, "0.3": 0.3, "0.7": 0.7, "1.0": 1.0}


class ContextError(ValueError):
    """Безопасная ошибка размера пользовательского контекста."""


def build_context(prompt, history, text, max_messages, max_chars):
    if max_messages < 2:
        raise ContextError("Лимит контекста должен вмещать инструкцию и вопрос.")
    if len(prompt) + len(text) > max_chars:
        raise ContextError("Вопрос слишком длинный. Сократи его и отправь снова.")
    # История поступает полными парами: не отделяем ответ от его вопроса.
    pairs = [history[i : i + 2] for i in range(0, len(history), 2)]
    pairs = [
        p for p in pairs if len(p) == 2 and p[0]["role"] == "user" and p[1]["role"] == "assistant"
    ]
    used = len(prompt) + len(text)
    selected = []
    for pair in reversed(pairs):
        size = sum(len(m["content"]) for m in pair)
        if len(selected) * 2 + 4 > max_messages or used + size > max_chars:
            break
        selected.insert(0, pair)
        used += size
    return (
        [{"role": "system", "content": prompt}]
        + [m for pair in selected for m in pair]
        + [{"role": "user", "content": text}]
    )


def split_answer(text, limit=4096):
    if limit < 2:
        raise ValueError("Лимит части должен быть не меньше двух.")
    # Консервативно считаем UTF-16: emoji вне BMP занимают две единицы.
    parts, start, used = [], 0, 0
    for index, char in enumerate(text):
        width = 2 if ord(char) > 0xFFFF else 1
        if used + width > limit:
            parts.append(text[start:index])
            start, used = index, 0
        used += width
    if start < len(text):
        parts.append(text[start:])
    return parts


class Assistant:
    def __init__(self, store, llm, settings):
        self.store, self.llm, self.config = store, llm, settings
        self._locks = {}

    @asynccontextmanager
    async def lock(self, user_id):
        # Счётчик включает ожидающие задачи, чтобы не создать два lock для пользователя.
        entry = self._locks.setdefault(user_id, [asyncio.Lock(), 0])
        entry[1] += 1
        try:
            async with entry[0]:
                yield
        finally:
            entry[1] -= 1
            if entry[1] == 0:
                del self._locks[user_id]

    async def reply(self, user_id, text):
        preferences = await self.store.settings(user_id)
        history = await self.store.history(user_id, self.config.history_max_messages)
        messages = build_context(
            PROMPTS[preferences["mode"]],
            history,
            text,
            self.config.history_max_messages,
            self.config.context_max_chars,
        )
        answer = await self.llm.complete(messages, preferences["temperature"])
        await self.store.save_turn(user_id, text, answer, self.config.history_max_messages)
        return answer
