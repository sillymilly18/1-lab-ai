"""Реальные ответы модели без сообщений в Telegram; изолированный временный user_id.

В Docker: docker compose exec -T bot python - --output - < scripts/experiment.py
Вне Docker: python -m scripts.experiment --output outputs/lab1-experiment.json
Команды /settings и /reset вызываются через те же обработчики программно.
Ручную демонстрацию через Telegram этот запуск не заменяет.
"""

import argparse
import asyncio
import json
import secrets
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.assistant import Assistant
from app.config import Settings
from app.db import create_pool
from app.handlers.student import reset
from app.handlers.student import settings as settings_command
from app.history import HistoryStore
from app.llm import LLMClient, LLMError
from app.prompts import PROMPTS

QUESTION = (
    "Объясни разницу между списком и кортежем в Python студенту первого курса. "
    "Покажи короткий пример и задай вопрос для самопроверки."
)
CRITERIA = [
    "Три раздела: Объяснение, Пример, Самопроверка; не более 200 слов; один вопрос в конце.",
    "Указано, что list изменяемый, tuple неизменяемый; нет утверждения, что tuple нельзя читать.",
    "Короткий корректный пример показывает различие; объяснение понятно первокурснику.",
    "Нет обещаний универсального превосходства в скорости или неподтверждённых фактов.",
]
INCOMPLETE_PROMPT = "Ты помощник. Объясняй учебные вопросы."


class RecordingClient:
    def __init__(self, client):
        self.client = client
        self.last = None

    async def complete(self, messages, temperature):
        self.last = await self.client.complete_result(messages, temperature)
        return self.last.text


async def run(output):
    config = Settings.load()
    client = LLMClient(config)
    recorder = RecordingClient(client)
    pool = await create_pool(config)
    store = HistoryStore(pool)
    assistant = Assistant(store, recorder, config)
    uid = -(secrets.randbits(62) + 1)
    data = {
        "date": datetime.now(ZoneInfo("Europe/Moscow")).isoformat(),
        "model": config.llm_model,
        "api": "Chat Completions /v1/chat/completions",
        "mode": "study",
        "question": QUESTION,
        "system_prompt": PROMPTS["study"],
        "max_tokens": config.llm_max_tokens,
        "timeout": config.llm_timeout,
        "history_max_messages": config.history_max_messages,
        "context_max_chars": config.context_max_chars,
        "other_sampling": "Не передаются; неизменные настройки сервера.",
        "criteria_before_run": CRITERIA,
        "method": (
            "Реальная LLM, PostgreSQL; /reset и /settings вызываются программно, без Telegram."
        ),
        "runs": [],
        "prompt_comparison": [],
    }

    def save():
        if output != "-":
            target = Path(output)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")

    async def answer(*args, **kwargs):
        return None

    def message(text):
        return SimpleNamespace(chat=SimpleNamespace(id=uid), text=text, answer=answer)

    save()  # Критерии зафиксированы до первого запроса.
    try:
        await store.initialize()
        await store.switch(uid, "study")
        for temperature in (0.0, 0.3, 0.7, 1.0):
            await settings_command(message(f"/settings {temperature:.1f}"), assistant)
            for repeat in range(1, 4):
                await reset(message("/reset"), assistant)
                row = {"run": len(data["runs"]) + 1, "temperature": temperature, "repeat": repeat}
                print(
                    f"Запуск {row['run']}/12, temperature={temperature}",
                    file=sys.stderr,
                    flush=True,
                )
                try:
                    text = await assistant.reply(uid, QUESTION)
                    row.update(
                        text=text, length=len(text), usage=recorder.last.usage, status="success"
                    )
                except LLMError as exc:
                    row.update(status="error", error=exc.user_message)
                data["runs"].append(row)
                save()
        for label, prompt in (("incomplete", INCOMPLETE_PROMPT), ("improved", PROMPTS["study"])):
            await reset(message("/reset"), assistant)
            row = {"label": label, "system_prompt": prompt, "temperature": 0.3}
            try:
                result = await client.complete_result(
                    [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": QUESTION},
                    ],
                    0.3,
                )
                row.update(
                    text=result.text, length=len(result.text), usage=result.usage, status="success"
                )
            except LLMError as exc:
                row.update(status="error", error=exc.user_message)
            data["prompt_comparison"].append(row)
            save()
    finally:
        await store.reset(uid)
        await pool.execute("DELETE FROM lab1_users WHERE user_id=$1", uid)
        await pool.close()
    if output == "-":
        print(json.dumps(data, ensure_ascii=False, indent=2))
    return (
        0 if all(r["status"] == "success" for r in data["runs"] + data["prompt_comparison"]) else 1
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="outputs/lab1-experiment.json")
    args = parser.parse_args()
    return asyncio.run(run(args.output))


if __name__ == "__main__":
    raise SystemExit(main())
