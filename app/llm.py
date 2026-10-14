"""Подменяемый асинхронный клиент OpenAI-совместимого Chat Completions API."""

import logging
import time
import uuid
from dataclasses import dataclass

import aiohttp

from app.config import ConfigError, Settings

logger = logging.getLogger(__name__)
ERROR_TEXT = "Не удалось получить ответ модели. Попробуй ещё раз чуть позже."
TIMEOUT_TEXT = "Модель не успела ответить. Попробуй ещё раз или сократи вопрос."


class LLMError(Exception):
    def __init__(self, user_message: str = ERROR_TEXT):
        super().__init__(user_message)
        self.user_message = user_message


@dataclass(frozen=True)
class Completion:
    text: str
    usage: dict[str, int]
    request_id: str


class LLMClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        if not all((settings.llm_base_url, settings.llm_api_key, settings.llm_model)):
            raise ConfigError("Задайте LLM_BASE_URL, LLM_API_KEY и LLM_MODEL в окружении.")
        from urllib.parse import urlsplit

        url = urlsplit(settings.llm_base_url)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            raise ConfigError("LLM_BASE_URL: нужен HTTP(S)-адрес без учётных данных.")

    async def complete(self, messages: list[dict], temperature: float) -> str:
        return (await self.complete_result(messages, temperature)).text

    async def complete_result(self, messages: list[dict], temperature: float) -> Completion:
        """Возвращает usage для эксперимента; содержимое не записывается в журнал."""
        request_id = uuid.uuid4().hex[:12]
        started = time.monotonic()
        logger.info("LLM начало id=%s model=%s", request_id, self.settings.llm_model)
        outcome = "error"
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.settings.llm_timeout)
            ) as session:
                async with session.post(
                    self.settings.llm_base_url.rstrip("/") + "/chat/completions",
                    headers={"Authorization": "Bearer " + self.settings.llm_api_key},
                    json={
                        "model": self.settings.llm_model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": self.settings.llm_max_tokens,
                        "stream": False,
                    },
                ) as response:
                    if response.status != 200:
                        raise LLMError()
                    data = await response.json()
            choice = data["choices"][0]
            content = choice["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise LLMError()
            if choice.get("finish_reason") != "stop":
                raise LLMError("Ответ модели не завершён. Попробуй задать более короткий вопрос.")
            outcome = "success"
            raw_usage = data.get("usage") or {}
            usage = (
                {
                    key: value
                    for key, value in raw_usage.items()
                    if key in {"prompt_tokens", "completion_tokens", "total_tokens"}
                    and type(value) is int
                    and value >= 0
                }
                if isinstance(raw_usage, dict)
                else {}
            )
            return Completion(content, usage, request_id)
        except TimeoutError:
            raise LLMError(TIMEOUT_TEXT) from None
        except LLMError:
            raise
        except (aiohttp.ClientError, KeyError, IndexError, TypeError, ValueError):
            # Не журналируем тело ответа или исключение провайдера: там может быть ввод.
            raise LLMError() from None
        finally:
            logger.info(
                "LLM результат id=%s model=%s status=%s seconds=%.2f",
                request_id,
                self.settings.llm_model,
                outcome,
                time.monotonic() - started,
            )
