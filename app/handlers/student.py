"""Команды и текстовые сообщения только из личных чатов."""

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionSender

from app.assistant import ALLOWED_TEMPERATURES, Assistant, ContextError, split_answer
from app.llm import LLMError

router = Router(name="student")
router.message.filter(F.chat.type == "private", F.text)
logger = logging.getLogger(__name__)
START_TEXT = (
    "Я AI-ассистент студента. Отправь текстовый вопрос.\n"
    "/study — объяснения по программированию\n"
    "/translate — перевод (укажи язык)\n"
    "/quiz — вопросы для самопроверки\n"
    "/settings — режим, модель и temperature\n"
    "/settings 0.7 — изменить temperature (0.0, 0.3, 0.7, 1.0)\n"
    "/reset — очистить историю, сохранив настройки"
)
RESET_TEXT = "История очищена. Режим и temperature сохранены."
INVALID_SETTINGS = "Укажи /settings 0.0, /settings 0.3, /settings 0.7 или /settings 1.0."


@router.message(Command("start"))
async def start(message: Message, assistant: Assistant):
    async with assistant.lock(message.chat.id):
        await assistant.store.settings(message.chat.id)
        await message.answer(START_TEXT, parse_mode=None)


@router.message(Command("study", "translate", "quiz"))
async def switch_mode(message: Message, assistant: Assistant):
    mode = message.text.split()[0][1:].split("@")[0]
    async with assistant.lock(message.chat.id):
        await assistant.store.switch(message.chat.id, mode)
        await message.answer(f"Режим /{mode} включён. История очищена.", parse_mode=None)


@router.message(Command("reset"))
async def reset(message: Message, assistant: Assistant):
    async with assistant.lock(message.chat.id):
        await assistant.store.reset(message.chat.id)
        await message.answer(RESET_TEXT, parse_mode=None)


@router.message(Command("settings"))
async def settings(message: Message, assistant: Assistant):
    args = message.text.split()[1:]
    async with assistant.lock(message.chat.id):
        if args:
            if len(args) != 1 or args[0] not in ALLOWED_TEMPERATURES:
                await message.answer(INVALID_SETTINGS, parse_mode=None)
                return
            await assistant.store.temperature(message.chat.id, ALLOWED_TEMPERATURES[args[0]])
            await message.answer(f"Temperature установлена: {args[0]}.", parse_mode=None)
        else:
            preferences = await assistant.store.settings(message.chat.id)
            await message.answer(
                f"Режим: /{preferences['mode']}\nМодель: {assistant.config.llm_model}\n"
                f"Temperature: {preferences['temperature']:.1f}\n"
                "Изменить: /settings 0.0, 0.3, 0.7 или 1.0",
                parse_mode=None,
            )


@router.message(F.text.startswith("/"))
async def unknown_command(message: Message):
    await message.answer("Неизвестная команда. Список команд: /start", parse_mode=None)


@router.message()
async def text_message(message: Message, assistant: Assistant):
    async with assistant.lock(message.chat.id):
        async with ChatActionSender.typing(bot=message.bot, chat_id=message.chat.id):
            try:
                answer = await assistant.reply(message.chat.id, message.text)
            except (LLMError, ContextError) as exc:
                answer = str(exc)
            except Exception as exc:
                # Только тип: SQL/внешняя ошибка может содержать текст диалога.
                logger.error("Ошибка обработки type=%s", type(exc).__name__)
                answer = "Не удалось обработать вопрос. Попробуй ещё раз чуть позже."
            for part in split_answer(answer):
                await message.answer(part, parse_mode=None)
