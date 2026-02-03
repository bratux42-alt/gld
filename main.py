import logging
import os
import asyncio
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from dotenv import load_dotenv
from downloader import downloader

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN is not set in environment variables")

CHANNELS = ["@GlaGena1", "@PyWallpap"]
FREE_VIDEO_LIMIT = 7
FREE_AUDIO_LIMIT = 15
BONUS_LIMIT = 4

# Глобальный ограничитель одновременных загрузок
download_semaphore = asyncio.Semaphore(10)

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Главное меню
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🎬 Начать скачивание")],
        [KeyboardButton(text="💎 Бонус и Лимиты")]
    ],
    resize_keyboard=True
)

import json

# Хранилище данных пользователей
STATS_FILE = "user_stats.json"

def load_stats():
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_stats():
    with open(STATS_FILE, "w") as f:
        json.dump(user_stats, f)

user_stats = load_stats()
pending_downloads = {}

def get_user_limits(user_id, sub_count):
    bonus = BONUS_LIMIT * sub_count
    return {
        "video": FREE_VIDEO_LIMIT + bonus,
        "audio": FREE_AUDIO_LIMIT + bonus
    }

async def get_subs_count(user_id):
    count = 0
    for channel in CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status not in ["left", "kicked"]:
                count += 1
        except Exception as e:
            logging.error(f"Error checking sub for {channel}: {e}")
    return count

def reset_daily_stats(user_id):
    today = datetime.now().date().isoformat()
    if str(user_id) not in user_stats or user_stats[str(user_id)].get('last_reset') != today:
        user_stats[str(user_id)] = {'video': 0, 'audio': 0, 'last_reset': today}
        save_stats()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 **Добро пожаловать в GlaDownloader!** 🚀\n\n"
        "Я помогу тебе скачать видео и музыку с твоих любимых площадок быстро и удобно.\n\n"
        "Выбери действие в меню ниже: 👇",
        reply_markup=main_menu
    )

@dp.message(F.text == "🎬 Начать скачивание")
async def start_downloading(message: types.Message):
    await message.answer(
        "📝 **Просто отправь мне ссылку** на видео или музыку.\n\n"
        "Я автоматически определю платформу и предложу варианты скачивания."
    )

@dp.message(F.text == "💎 Бонус и Лимиты")
async def show_bonus(message: types.Message):
    user_id = str(message.from_user.id)
    reset_daily_stats(user_id)
    sub_count = await get_subs_count(user_id)
    limits = get_user_limits(user_id, sub_count)
    stats = user_stats[user_id]
    
    status_text = ""
    for i, channel in enumerate(CHANNELS, 1):
        try:
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
            status = "✅ Подписан" if member.status not in ["left", "kicked"] else "❌ Не подписан"
        except:
            status = "❌ Ошибка"
        status_text += f"{i}. {channel}: **{status}**\n"

    await message.answer(
        "💎 **Система бонусов и лимитов**\n\n"
        f"� **Твои лимиты на сегодня:**\n"
        f"• Видео: {stats['video']}/{limits['video']}\n"
        f"• Аудио: {stats['audio']}/{limits['audio']}\n\n"
        f"� Сброс лимитов: каждый день в 00:00 (сервер).\n\n"
        "💡 **Хочешь больше?**\n"
        "Подпишись на наши каналы и получай **+4 к каждому лимиту** ежедневно, пока ты подписан!\n\n"
        f"{status_text}\n"
        "1. [GlaGena1](https://t.me/GlaGena1)\n"
        "2. [PyWallpap](https://t.me/PyWallpap)",
        disable_web_page_preview=True,
        parse_mode="Markdown"
    )

@dp.message(F.text.regexp(r'(https?://[^\s]+)'))
async def handle_url(message: types.Message):
    url = message.text
    user_id = str(message.from_user.id)
    
    reset_daily_stats(user_id)
    sub_count = await get_subs_count(user_id)
    limits = get_user_limits(user_id, sub_count)
    stats = user_stats[user_id]

    text = f"Что ты хочешь скачать?\n\n📊 Твои лимиты на сегодня:\n"
    text += f"🎬 Видео: {stats['video']}/{limits['video']}\n"
    text += f"🎵 Аудио: {stats['audio']}/{limits['audio']}\n"
    
    if sub_count < len(CHANNELS):
        text += f"\n💡 Подпишись на каналы, чтобы увеличить лимиты (+{BONUS_LIMIT} за каждый)!"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎬 Видео", callback_data=f"dl_video_{message.message_id}"),
            InlineKeyboardButton(text="🎵 Аудио", callback_data=f"dl_audio_{message.message_id}")
        ]
    ])
    
    pending_downloads[str(message.message_id)] = url
    await message.answer(text, reply_markup=keyboard)

@dp.callback_query(F.data.startswith("dl_"))
async def process_download(callback: types.CallbackQuery):
    data = callback.data.split("_")
    mode = data[1]
    msg_id = data[2]
    user_id = str(callback.from_user.id)
    
    url = pending_downloads.get(msg_id)
    if not url:
        await callback.answer("Ошибка: ссылка устарела.")
        return

    reset_daily_stats(user_id)
    sub_count = await get_subs_count(user_id)
    limits = get_user_limits(user_id, sub_count)
    stats = user_stats[user_id]

    if stats[mode] >= limits[mode]:
        await callback.message.edit_text(f"❌ Лимит на сегодня исчерпан ({limits[mode]}/{limits[mode]}). Возвращайся завтра!")
        return

    if download_semaphore._value == 0:
        await callback.message.edit_text("⏳ Все линии загрузки заняты (10/10). Пожалуйста, подождите немного...")

    async with download_semaphore:
        await callback.message.edit_text(f"⏳ Начинаю загрузку ({mode})... Очередь: {10 - download_semaphore._value}/10")
        
        try:
            file_path = await downloader.download(url, mode=mode)
            
            if file_path and os.path.exists(file_path):
                input_file = FSInputFile(file_path)
                if mode == "video":
                    await bot.send_video(callback.message.chat.id, video=input_file)
                else:
                    await bot.send_audio(callback.message.chat.id, audio=input_file)
                
                user_stats[user_id][mode] += 1
                save_stats()
                await callback.message.delete()
                os.remove(file_path)
            else:
                await callback.message.edit_text("❌ Не удалось скачать файл. Попробуйте другую ссылку.")
        except Exception as e:
            logging.error(f"Error in process_download: {e}")
            await callback.message.edit_text(f"❌ Ошибка загрузки: {str(e)}")
        finally:
            if msg_id in pending_downloads:
                del pending_downloads[msg_id]

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
