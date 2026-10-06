from aiogram import Bot
from aiogram.types import InputRichMessage


async def send_message(token, chat_id, message):
    async with Bot(token=token) as bot:
        await bot.send_rich_message(chat_id, InputRichMessage(html=message))
