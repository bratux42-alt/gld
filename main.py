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

ADMIN_ID = 8566608157

# Хранилище данных пользователей
STATS_FILE = "user_stats.json"

def load_stats():
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, "r") as f:
                data = json.load(f)
                # Убеждаемся, что есть список всех пользователей
                if "all_users" not in data:
                    data["all_users"] = []
                return data
        except:
            return {"all_users": []}
    return {"all_users": []}

def save_stats():
    with open(STATS_FILE, "w") as f:
        json.dump(user_stats, f)

user_stats = load_stats()
pending_downloads = {}

# Глобальное состояние для рассылки
broadcast_state = {}

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
            member = await bot.get_chat_member(chat_id=channel, user_id=int(user_id))
            if member.status not in ["left", "kicked"]:
                count += 1
        except Exception as e:
            logging.error(f"Error checking sub for {channel}: {e}")
    return count

def reset_daily_stats(user_id, username=None):
    today = datetime.now().date().isoformat()
    user_id_str = str(user_id)
    
    # Добавляем пользователя и юзернейм
    if "usernames" not in user_stats:
        user_stats["usernames"] = {}
    if username:
        user_stats["usernames"][user_id_str] = f"@{username}"
    
    if user_id_str not in user_stats.get("all_users", []):
        if "all_users" not in user_stats:
            user_stats["all_users"] = []
        user_stats["all_users"].append(user_id_str)

    if user_id_str not in user_stats or user_stats[user_id_str].get('last_reset') != today:
        user_stats[user_id_str] = {'video': 0, 'audio': 0, 'last_reset': today}
        save_stats()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = str(message.from_user.id)
    reset_daily_stats(user_id, message.from_user.username)
    
    markup = main_menu
    if message.from_user.id == ADMIN_ID:
        # Для админа можно добавить кнопку или просто сообщить о команде
        text_admin = "\n\n⚙️ Ты зашел как **Админ**. Используй /admin для управления."
    else:
        text_admin = ""

    await message.answer(
        "👋 **Добро пожаловать в GlaDownloader!** 🚀\n\n"
        "Я помогу тебе скачать видео и музыку с твоих любимых площадок быстро и удобно.\n\n"
        "Выбери действие в меню ниже: 👇" + text_admin,
        reply_markup=markup
    )

# --- ADMIN PANEL ---

@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")]
    ])
    await message.answer("🛠 **Панель администратора**", reply_markup=kb)

@dp.callback_query(F.data == "admin_stats")
async def show_stats(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    
    total_users = len(user_stats.get("all_users", []))
    active_today = sum(1 for k, v in user_stats.items() if k not in ["all_users", "usernames"] and isinstance(v, dict) and v.get("last_reset") == datetime.now().date().isoformat())
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Список пользователей", callback_data="admin_users_0")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")]
    ])

    await callback.message.edit_text(
        f"📊 **Статистика бота**\n\n"
        f"👤 Всего пользователей: {total_users}\n"
        f"📈 Активны сегодня: {active_today}",
        reply_markup=kb
    )

@dp.callback_query(F.data.startswith("admin_users_"))
async def list_users(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    
    page = int(callback.data.split("_")[2])
    users = user_stats.get("all_users", [])
    per_page = 10
    start = page * per_page
    end = start + per_page
    
    current_users = users[start:end]
    if not current_users:
        await callback.answer("Больше пользователей нет")
        return

    text = f"👥 **Список пользователей (Стр. {page + 1})**\n\n"
    for uid in current_users:
        stats = user_stats.get(uid, {})
        username = user_stats.get("usernames", {}).get(uid, "Unknown")
        
        # Получаем лимиты (проверка подписки для списка может быть медленной, 
        # поэтому показываем просто текущую активность за сегодня)
        v_done = stats.get('video', 0)
        a_done = stats.get('audio', 0)
        
        text += f"• ID: `{uid}` ({username})\n  └ 🎬 {v_done} | 🎵 {a_done}\n\n"

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Пред.", callback_data=f"admin_users_{page-1}"))
    if end < len(users):
        nav_buttons.append(InlineKeyboardButton(text="След. ➡️", callback_data=f"admin_users_{page+1}"))

    kb = InlineKeyboardMarkup(inline_keyboard=[nav_buttons, [InlineKeyboardButton(text="⬅️ К статистике", callback_data="admin_stats")]])
    
    await callback.message.edit_text(text, reply_markup=kb)

@dp.callback_query(F.data == "admin_broadcast")
async def start_broadcast(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    broadcast_state[callback.from_user.id] = True
    await callback.message.edit_text(
        "📢 **Создание рассылки**\n\n"
        "Отправь мне сообщение (текст, фото или видео), которое нужно разослать всем пользователям.\n"
        "Для отмены нажми кнопку ниже.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back")]])
    )

@dp.callback_query(F.data == "admin_back")
async def admin_back(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    broadcast_state.pop(callback.from_user.id, None)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")]
    ])
    await callback.message.edit_text("🛠 **Панель администратора**", reply_markup=kb)

@dp.message(F.text, lambda m: broadcast_state.get(m.from_user.id))
async def perform_broadcast(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    
    users = user_stats.get("all_users", [])
    count = 0
    await message.answer(f"🚀 Начинаю рассылку на {len(users)} пользователей...")
    
    for user_id in users:
        try:
            await bot.copy_message(chat_id=user_id, from_chat_id=message.chat.id, message_id=message.message_id)
            count += 1
            await asyncio.sleep(0.05) # Защита от спам-фильтра TG
        except Exception as e:
            logging.error(f"Failed to send message to {user_id}: {e}")
    
    broadcast_state.pop(message.from_user.id, None)
    await message.answer(f"✅ Рассылка завершена! Получили: {count}/{len(users)}")

# --- END ADMIN PANEL ---

@dp.message(F.text == "🎬 Начать скачивание")
async def start_downloading(message: types.Message):
    await message.answer(
        "📝 **Просто отправь мне ссылку** на видео или музыку.\n\n"
        "Я автоматически определю платформу и предложу варианты скачивания."
    )

@dp.message(F.text == "💎 Бонус и Лимиты")
async def show_bonus(message: types.Message):
    user_id = str(message.from_user.id)
    reset_daily_stats(user_id, message.from_user.username)
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
    
    reset_daily_stats(user_id, message.from_user.username)
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

    reset_daily_stats(user_id, callback.from_user.username)
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
                # На Zeabur иногда лучше проверять размер файла
                if os.path.getsize(file_path) < 100:
                    await callback.message.edit_text("❌ Ошибка: скачанный файл слишком мал или пуст. Возможно, защита YouTube заблокировала запрос.")
                    os.remove(file_path)
                    return

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
                await callback.message.edit_text("❌ Не удалось получить файл. YouTube/TikTok блокирует запросы с этого сервера. Попробуйте другую ссылку или позже.")
        except Exception as e:
            logging.error(f"Error in process_download: {e}")
            await callback.message.edit_text(f"⚠️ Ошибка сервера: {str(e)[:100]}. Мы уже разбираемся!")
        finally:
            if msg_id in pending_downloads:
                del pending_downloads[msg_id]

async def main():
    # Удаляем вебхук и все накопившиеся сообщения, чтобы избежать конфликтов при перезапуске
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
