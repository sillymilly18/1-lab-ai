from unittest.mock import AsyncMock

import pytest

from app.assistant import Assistant, build_context, split_answer
from app.config import Settings
from app.handlers.student import (
    INVALID_SETTINGS,
    RESET_TEXT,
    reset,
    settings,
    switch_mode,
    text_message,
)
from app.llm import ERROR_TEXT, LLMClient, LLMError
from app.prompts import PROMPTS


class MemoryStore:
    def __init__(self):
        self.users = {}
        self.messages = {}

    async def settings(self, uid):
        return self.users.setdefault(uid, {"mode": "study", "temperature": 0.3})

    async def history(self, uid, limit):
        return self.messages.get(uid, [])[-limit:]

    async def save_turn(self, uid, text, answer, max_messages):
        self.messages.setdefault(uid, []).extend(
            [{"role": "user", "content": text}, {"role": "assistant", "content": answer}]
        )

    async def reset(self, uid):
        self.messages[uid] = []

    async def switch(self, uid, mode):
        (await self.settings(uid))["mode"] = mode
        await self.reset(uid)

    async def temperature(self, uid, value):
        (await self.settings(uid))["temperature"] = value


@pytest.fixture
def assistant():
    return Assistant(
        MemoryStore(),
        AsyncMock(complete=AsyncMock(return_value="Ответ")),
        Settings(bot_token="unused", postgres_password="unused", llm_model="test"),
    )


def message(uid=1, text="Вопрос"):
    from unittest.mock import Mock

    return Mock(chat=Mock(id=uid), text=text, answer=AsyncMock())


async def test_context_roles_and_two_users(assistant):
    await assistant.reply(1, "Первый")
    await assistant.reply(2, "Другой")
    assert assistant.llm.complete.call_args.args == (
        [{"role": "system", "content": PROMPTS["study"]}, {"role": "user", "content": "Другой"}],
        0.3,
    )
    await assistant.reply(1, "Следующий")
    assert assistant.llm.complete.call_args.args[0] == [
        {"role": "system", "content": PROMPTS["study"]},
        {"role": "user", "content": "Первый"},
        {"role": "assistant", "content": "Ответ"},
        {"role": "user", "content": "Следующий"},
    ]


def test_trimming_whole_pairs_and_current_request():
    history = [
        {"role": role, "content": str(i) * 4} for i in range(3) for role in ("user", "assistant")
    ]
    result = build_context("S", history, "CURRENT", 5, 16)
    assert result == [
        {"role": "system", "content": "S"},
        *history[-2:],
        {"role": "user", "content": "CURRENT"},
    ]
    assert build_context("S", history, "CURRENT", 2, 100) == [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "CURRENT"},
    ]
    with pytest.raises(ValueError):
        build_context("S", [], "TOO LONG", 12, 2)


async def test_switch_and_reset_only_one_user(assistant):
    await assistant.reply(1, "Первый")
    await assistant.reply(2, "Второй")
    msg = message(text="/translate")
    await switch_mode(msg, assistant)
    msg.answer.assert_awaited_once_with(
        "Режим /translate включён. История очищена.", parse_mode=None
    )
    assert assistant.store.users[1]["mode"] == "translate"
    assert assistant.store.messages[1] == []
    assert assistant.store.messages[2]
    await assistant.store.temperature(1, 0.7)
    await reset(message(), assistant)
    assert await assistant.store.settings(1) == {"mode": "translate", "temperature": 0.7}
    msg = message()
    await reset(msg, assistant)
    msg.answer.assert_awaited_once_with(RESET_TEXT, parse_mode=None)


async def test_temperature_validation_and_actual_parameter(assistant):
    msg = message(text="/settings 1.0")
    await settings(msg, assistant)
    msg.answer.assert_awaited_once_with("Temperature установлена: 1.0.", parse_mode=None)
    await assistant.reply(1, "Вопрос")
    assert assistant.llm.complete.call_args.args[1] == 1.0
    for value in ("0.5", "nan", "1.0 лишнее"):
        msg = message(text="/settings " + value)
        await settings(msg, assistant)
        msg.answer.assert_awaited_once_with(INVALID_SETTINGS, parse_mode=None)
    assert (await assistant.store.settings(2))["temperature"] == 0.3


async def test_error_and_long_answer_delivery(assistant, monkeypatch):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def typing(**kwargs):
        yield

    monkeypatch.setattr("app.handlers.student.ChatActionSender.typing", typing)
    assistant.llm.complete.side_effect = LLMError()
    msg = message()
    await text_message(msg, assistant)
    msg.answer.assert_awaited_once_with(ERROR_TEXT, parse_mode=None)
    assert not assistant.store.messages
    assistant.llm.complete.side_effect = None
    answer = "Я🙂\n" * 3000
    assistant.llm.complete.return_value = answer
    msg = message()
    await text_message(msg, assistant)
    chunks = [call.args[0] for call in msg.answer.await_args_list]
    assert chunks == split_answer(answer)
    assert "".join(chunks) == answer
    assert all(0 < len(chunk) <= 4096 for chunk in chunks)


async def test_http_request_and_malformed_reply(unused_tcp_port):
    from aiohttp import web

    captured = []
    payload = {"choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}]}

    async def handle(request):
        captured.append(await request.json())
        return web.json_response(payload)

    app = web.Application()
    app.router.add_post("/v1/chat/completions", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", unused_tcp_port).start()
    config = Settings(
        bot_token="unused",
        postgres_password="unused",
        llm_model="mock",
        llm_api_key="test",
        llm_base_url=f"http://127.0.0.1:{unused_tcp_port}/v1",
    )
    try:
        client = LLMClient(config)
        messages = [{"role": "system", "content": "S"}, {"role": "user", "content": "Q"}]
        assert await client.complete(messages, 0.7) == "OK"
        assert captured[0] == {
            "model": "mock",
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 700,
            "stream": False,
        }
        payload["choices"][0]["message"]["content"] = ""
        with pytest.raises(LLMError):
            await client.complete(messages, 0.3)
        payload["choices"] = []
        with pytest.raises(LLMError):
            await client.complete(messages, 0.3)
    finally:
        await runner.cleanup()


@pytest.mark.parametrize("limit", range(2, 14))
def test_context_respects_even_and_odd_message_limits(limit):
    history = [
        {"role": role, "content": str(i)} for i in range(10) for role in ("user", "assistant")
    ]
    result = build_context("S", history, "Q", limit, 100)
    assert len(result) <= limit
    assert result[0] == {"role": "system", "content": "S"}
    assert result[-1] == {"role": "user", "content": "Q"}
    middle = result[1:-1]
    assert middle == history[-len(middle) :] if middle else result == [result[0], result[-1]]
    assert [m["role"] for m in middle] == ["user", "assistant"] * (len(middle) // 2)


@pytest.mark.parametrize("mode", ["study", "translate", "quiz"])
async def test_active_mode_prompt_and_no_command_sent_to_model(assistant, mode):
    await assistant.reply(1, "Предыдущий вопрос")
    assistant.llm.complete.reset_mock()
    await switch_mode(message(text="/" + mode), assistant)
    assistant.llm.complete.assert_not_awaited()
    await assistant.reply(1, "Новый вопрос")
    assert assistant.llm.complete.call_args.args[0] == [
        {"role": "system", "content": PROMPTS[mode]},
        {"role": "user", "content": "Новый вопрос"},
    ]


async def test_odd_history_limit_preserves_latest_pair():
    from app.history import HistoryStore

    pool = AsyncMock()
    pool.fetch.return_value = [
        {"role": "user", "content": "Q"},
        {"role": "assistant", "content": "A"},
    ]
    store = HistoryStore(pool)
    assert await store.history(1, 3) == pool.fetch.return_value
    assert pool.fetch.call_args.args[1:] == (1, 2)


@pytest.mark.parametrize("response_kind", ["timeout", "http", "json", "null", "length", "empty"])
async def test_provider_failures_are_safe(unused_tcp_port, response_kind):
    import asyncio
    from dataclasses import replace

    from aiohttp import web

    from app.llm import TIMEOUT_TEXT

    async def handle(request):
        if response_kind == "timeout":
            await asyncio.sleep(0.1)
        if response_kind == "http":
            return web.Response(status=401, text="SECRET provider details")
        if response_kind == "json":
            return web.Response(text="{bad", content_type="application/json")
        if response_kind == "null":
            return web.json_response(None)
        return web.json_response(
            {
                "choices": [
                    {
                        "message": {"content": "" if response_kind == "empty" else "OK"},
                        "finish_reason": "length" if response_kind == "length" else "stop",
                    }
                ]
            }
        )

    app = web.Application()
    app.router.add_post("/v1/chat/completions", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", unused_tcp_port).start()
    config = Settings(
        bot_token="unused",
        postgres_password="unused",
        llm_model="mock",
        llm_api_key="SECRET",
        llm_base_url=f"http://127.0.0.1:{unused_tcp_port}/v1",
    )
    if response_kind == "timeout":
        config = replace(config, llm_timeout=0.01)
    try:
        with pytest.raises(LLMError) as caught:
            await LLMClient(config).complete([{"role": "user", "content": "Q"}], 0.3)
        expected = (
            TIMEOUT_TEXT
            if response_kind == "timeout"
            else "Ответ модели не завершён. Попробуй задать более короткий вопрос."
            if response_kind == "length"
            else ERROR_TEXT
        )
        assert str(caught.value) == expected
    finally:
        await runner.cleanup()


def test_split_preserves_emoji_and_fits_utf16_limit():
    text = "🙂" * 4097 + "конец"
    chunks = split_answer(text)
    assert "".join(chunks) == text
    assert all(0 < len(part.encode("utf-16-le")) // 2 <= 4096 for part in chunks)


def test_invalid_history_limit_and_missing_llm_fail_before_connections(monkeypatch):
    from app import __main__ as application
    from app.config import ConfigError

    with pytest.raises(ConfigError, match="HISTORY_MAX_MESSAGES"):
        Settings.load(
            "/nonexistent",
            environ={
                "BOT_TOKEN": "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk",
                "POSTGRES_PASSWORD": "secret",
                "HISTORY_MAX_MESSAGES": "1",
            },
        )
    create_bot = AsyncMock()
    monkeypatch.setattr(application, "create_bot", create_bot)
    with pytest.raises(ConfigError, match="LLM_BASE_URL"):
        import asyncio

        asyncio.run(application.run(Settings(bot_token="unused", postgres_password="unused")))
    create_bot.assert_not_called()


async def test_unexpected_value_error_does_not_expose_internal_text(assistant, monkeypatch):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def typing(**kwargs):
        yield

    monkeypatch.setattr("app.handlers.student.ChatActionSender.typing", typing)
    assistant.llm.complete.side_effect = ValueError("SECRET internal dialogue")
    msg = message()
    await text_message(msg, assistant)
    msg.answer.assert_awaited_once_with(
        "Не удалось обработать вопрос. Попробуй ещё раз чуть позже.", parse_mode=None
    )
    assert not assistant.store.messages
