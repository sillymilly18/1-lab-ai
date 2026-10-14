"""RUN_INTEGRATION=1 python -m pytest -m integration -v.

Тест создаёт собственные контейнер и volume; пользовательскую БД не использует.
"""

import asyncio
import json
import os
import secrets
import socket
import time
from dataclasses import replace

import asyncpg
import pytest

from app.config import Settings
from app.db import create_pool
from app.health import HealthState, health_result
from scripts.common import CommandError, run_command

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_INTEGRATION") != "1",
        reason="Включите RUN_INTEGRATION=1 для Docker-тестов",
    ),
]


@pytest.fixture
def database():
    name = "itmo-test-" + secrets.token_hex(6)
    volume = name + "-data"
    password = secrets.token_urlsafe(24)

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]

    def docker(*args):
        return run_command(["docker", *args], label="Интеграционный Docker-тест", timeout=180)

    def wait_until_ready():
        deadline = time.monotonic() + 60
        while True:
            try:
                docker("exec", name, "pg_isready", "-h", "127.0.0.1", "-U", "bot", "-d", "bot")
                return
            except CommandError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(1)

    docker("info")
    docker("volume", "create", volume)
    try:
        docker(
            "run",
            "-d",
            "--name",
            name,
            "-p",
            f"127.0.0.1:{port}:5432",
            "-e",
            "POSTGRES_DB=bot",
            "-e",
            "POSTGRES_USER=bot",
            "-e",
            f"POSTGRES_PASSWORD={password}",
            "--mount",
            f"type=volume,source={volume},target=/var/lib/postgresql/data",
            "postgres:16-bookworm",
        )
        info = json.loads(docker("inspect", name))[0]
        assert int(info["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostPort"]) == port
        wait_until_ready()
        yield (
            Settings(
                bot_token="123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk",
                postgres_password=password,
                postgres_port=port,
            ),
            docker,
            wait_until_ready,
            name,
        )
    finally:
        try:
            docker("rm", "-f", name)
        finally:
            docker("volume", "rm", volume)


async def test_real_db_password_restart_health_and_persistence(database):
    # Arrange
    settings, docker, wait_until_ready, name = database
    pool = await create_pool(settings)
    task = asyncio.create_task(asyncio.Event().wait())
    state = HealthState(pool=pool, initialized=True, polling_task=task)
    try:
        await pool.execute("CREATE TABLE integration_probe (value text NOT NULL)")
        await pool.execute("INSERT INTO integration_probe VALUES ($1)", "Сохранилось 👋")
        # Act / Assert: реальное подключение и ошибка пароля.
        assert (await health_result(state))[0] == 200
        with pytest.raises(asyncpg.InvalidPasswordError):
            await create_pool(replace(settings, postgres_password="wrong-password"))
        # Act / Assert: потеря соединения и сохранность данных после запуска.
        await asyncio.to_thread(docker, "stop", name)
        assert (await health_result(state))[0] == 503
        await asyncio.to_thread(docker, "start", name)
        await asyncio.to_thread(wait_until_ready)
        for _ in range(60):
            if (await health_result(state))[0] == 200:
                break
            await asyncio.sleep(1)
        assert (await health_result(state))[0] == 200
        assert await pool.fetchval("SELECT value FROM integration_probe") == "Сохранилось 👋"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await pool.close()


async def test_lab1_two_users_persist_after_pool_restart(database):
    from app.assistant import build_context
    from app.history import HistoryStore

    settings, _, _, _ = database
    pool = await create_pool(settings)
    try:
        store = HistoryStore(pool)
        await store.initialize()
        assert await store.settings(101) == {"mode": "study", "temperature": 0.3}
        await store.settings(202)
        await store.save_turn(101, "Проект Альфа", "Запомнил", 12)
        await store.switch(202, "quiz")
        await store.temperature(202, 1.0)
        await store.save_turn(202, "Тема: Python", "Вопросы", 12)
    finally:
        await pool.close()
    # Новый пул и хранилище имитируют перезапуск приложения.
    pool = await create_pool(settings)
    try:
        store = HistoryStore(pool)
        assert await store.settings(202) == {"mode": "quiz", "temperature": 1.0}
        assert await store.settings(101) == {"mode": "study", "temperature": 0.3}
        assert await store.history(101, 12) == [
            {"role": "user", "content": "Проект Альфа"},
            {"role": "assistant", "content": "Запомнил"},
        ]
        await store.reset(101)
        assert await store.history(101, 12) == []
        assert await store.history(202, 12)
        await store.switch(202, "translate")
        assert await store.history(202, 12) == []
        assert await store.settings(202) == {"mode": "translate", "temperature": 1.0}
        for i in range(5):
            await store.save_turn(202, f"Q{i}", f"A{i}", 5)
        history = await store.history(202, 5)
        assert [m["content"] for m in history] == ["Q3", "A3", "Q4", "A4"]
        context = build_context("S", history, "NOW", 5, 100)
        assert [m["content"] for m in context] == ["S", "Q4", "A4", "NOW"]
    finally:
        await pool.close()
