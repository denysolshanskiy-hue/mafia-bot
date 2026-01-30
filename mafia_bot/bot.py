import asyncio
import os
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.filters.callback_data import CallbackData

# Імпортуємо функції з твого database.py
from database import get_connection, init_db

# ================== INIT ==================
BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ================== STATES ==================
class CreateEventStates(StatesGroup):
    waiting_for_title = State()
    waiting_for_date = State()
    waiting_for_time = State()

class NicknameState(StatesGroup):
    waiting_for_nickname = State()

class CommentState(StatesGroup):
    waiting_for_comment = State()

# ================== CALLBACK DATA ==================
class InviteCallback(CallbackData, prefix="invite"):
    # ТУТ БУЛА ПОМИЛКА: додано 'list'
    action: str   # join | ignore | cancel | list
    event_id: int

# ================== KEYBOARDS ==================

def admin_menu_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Створити івент"), KeyboardButton(text="📅 Активні події")],
            [KeyboardButton(text="💳 Оплатити ігри"), KeyboardButton(text="🛠 Адмін: список + скасовані")],
            [KeyboardButton(text="✅ Підтвердити вечір"), KeyboardButton(text="🏁 Завершити вечір")],
            [KeyboardButton(text="❌ Скасувати івент")]
        ],
        resize_keyboard=True
    )

def player_menu_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Активні події")],
            [KeyboardButton(text="💳 Оплатити ігри")], 
        ],
        resize_keyboard=True
    )

def invite_keyboard(event_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Записатись",
                    callback_data=InviteCallback(action="join", event_id=event_id).pack(),
                ),
                InlineKeyboardButton(
                    text="👥 Список гравців",
                    callback_data=InviteCallback(action="list", event_id=event_id).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="❌ Скасувати запис",
                    callback_data=InviteCallback(action="cancel", event_id=event_id).pack(),
                )
            ]
        ]
    )

def cancel_keyboard(event_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="❌ Скасувати запис",
                callback_data=InviteCallback(action="cancel", event_id=event_id).pack()
            )
        ]]
    )

def payment_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="✅ Я оплатив(ла)", callback_data="confirm_payment")]]
    )

# ================== START / NICKNAME ==================

@dp.message(CommandStart())
async def start_handler(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    conn = await get_connection()
    try:
        row = await conn.fetchrow("SELECT display_name, role FROM users WHERE user_id = $1", user_id)
        if not row:
            await conn.execute("INSERT INTO users (user_id, username, display_name, role) VALUES ($1, $2, NULL, 'player')",
                             user_id, message.from_user.username)
            await message.answer("👋 Вітаю!\n\nВведіть, будь ласка, ваш **нік** для ігор:", parse_mode="Markdown")
            await state.set_state(NicknameState.waiting_for_nickname)
            return

        display_name, role = row['display_name'], row['role']
        if not display_name:
            await message.answer("Введіть, будь ласка, ваш **нік**:")
            await state.set_state(NicknameState.waiting_for_nickname)
            return

        keyboard = admin_menu_keyboard() if role == "admin" else player_menu_keyboard()
        await message.answer(f"З поверненням, **{display_name}** 👋", parse_mode="Markdown", reply_markup=keyboard)
    finally:
        await conn.close()

@dp.message(NicknameState.waiting_for_nickname)
async def save_nickname(message: types.Message, state: FSMContext):
    nickname = message.text.strip()
    if len(nickname) < 2 or len(nickname) > 20:
        await message.answer("❌ Нік має бути від 2 до 20 символів.")
        return
    conn = await get_connection()
    try:
        await conn.execute("UPDATE users SET display_name = $1 WHERE user_id = $2", nickname, message.from_user.id)
        await state.clear()
        await message.answer(f"✅ Готово! Ваш нік: **{nickname}**", parse_mode="Markdown", reply_markup=player_menu_keyboard())
    finally:
        await conn.close()

# ================== JOIN / LIST / CANCEL LOGIC ==================

@dp.callback_query(InviteCallback.filter(F.action == "join"))
async def invite_join(callback: types.CallbackQuery, callback_data: InviteCallback, state: FSMContext):
    conn = await get_connection()
    try:
        event = await conn.fetchrow("SELECT status, title FROM events WHERE event_id = $1", callback_data.event_id)
        if not event or event["status"] != 'active':
            await callback.answer("🚫 Цей івент вже неактивний.", show_alert=True)
            return

        user = await conn.fetchrow("SELECT display_name FROM users WHERE user_id = $1", callback.from_user.id)
        if not user or not user["display_name"]:
            await callback.answer("❌ Спочатку вкажіть ваш нік", show_alert=True)
            return

        existing = await conn.fetchval("SELECT 1 FROM registrations WHERE event_id = $1 AND user_id = $2 AND status = 'active'", callback_data.event_id, callback.from_user.id)
        if existing:
            await callback.answer("Ви вже записані")
            return

        await conn.execute("INSERT INTO registrations (event_id, user_id, status) VALUES ($1, $2, 'active')", callback_data.event_id, callback.from_user.id)
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("Ви записані!")

        await state.set_state(CommentState.waiting_for_comment)
        await state.update_data(event_id=callback_data.event_id)
        await bot.send_message(callback.from_user.id, f"🎭 **{event['title']}**\n\n💬 Напишіть коментар або `-` щоб пропустити")
    finally:
        await conn.close()

@dp.callback_query(InviteCallback.filter(F.action == "list"))
async def show_event_players(callback: types.CallbackQuery, callback_data: InviteCallback):
    conn = await get_connection()
    try:
        event_title = await conn.fetchval("SELECT title FROM events WHERE event_id = $1", callback_data.event_id)
        players = await conn.fetch("""
            SELECT u.display_name, r.comment FROM registrations r 
            JOIN users u ON r.user_id = u.user_id 
            WHERE r.event_id = $1 AND r.status = 'active'
            ORDER BY r.created_at ASC""", callback_data.event_id)

        if not players:
            await callback.answer("На цей івент поки ніхто не записався", show_alert=True)
            return

        text = f"👥 **Гравці на {event_title}:**\n\n"
        for i, p in enumerate(players, 1):
            comment = f" ({p['comment']})" if p['comment'] else ""
            text += f"{i}. {p['display_name']}{comment}\n"
        
        await callback.message.answer(text, parse_mode="Markdown")
        await callback.answer()
    finally:
        await conn.close()

@dp.message(CommentState.waiting_for_comment)
async def save_comment(message: types.Message, state: FSMContext):
    comment = None if message.text.strip() == "-" else message.text.strip()
    data = await state.get_data()
    event_id = data.get("event_id")
    conn = await get_connection()
    try:
        await conn.execute("UPDATE registrations SET comment = $1 WHERE event_id = $2 AND user_id = $3 AND status = 'active'", comment, event_id, message.from_user.id)
        info = await conn.fetchrow("SELECT e.title, u.display_name, e.created_by FROM events e JOIN users u ON u.user_id = $1 WHERE e.event_id = $2", message.from_user.id, event_id)
        await state.clear()
        await message.answer("✅ Запис підтверджено!", reply_markup=cancel_keyboard(event_id))
        if info:
            await bot.send_message(info['created_by'], f"🆕 *Реєстрація*\n🎭 {info['title']}\n👤 {info['display_name']}\n💬 {comment or '—'}", parse_mode="Markdown")
    finally:
        await conn.close()

# ================== ADMIN: CREATE / CONFIRM / CLOSE ==================

@dp.message(F.text == "➕ Створити івент")
async def create_event_start(message: types.Message, state: FSMContext):
    await message.answer("📝 Введіть назву івенту:")
    await state.set_state(CreateEventStates.waiting_for_title)

@dp.message(CreateEventStates.waiting_for_title)
async def create_event_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await message.answer("📅 Введіть дату (20.01):")
    await state.set_state(CreateEventStates.waiting_for_date)

@dp.message(CreateEventStates.waiting_for_date)
async def create_event_date(message: types.Message, state: FSMContext):
    await state.update_data(event_date=message.text)
    await message.answer("⏰ Введіть час (19:00):")
    await state.set_state(CreateEventStates.waiting_for_time)

@dp.message(CreateEventStates.waiting_for_time)
async def create_event_time(message: types.Message, state: FSMContext):
    data = await state.get_data()
    conn = await get_connection()
    try:
        event_id = await conn.fetchval("INSERT INTO events (title, event_date, event_time, status, created_by) VALUES ($1, $2, $3, 'active', $4) RETURNING event_id",
                                     data['title'], data['event_date'], message.text, message.from_user.id)
        await state.clear()
        await message.answer("✅ Івент створено!")
    finally:
        await conn.close()

@dp.message(F.text == "🏁 Завершити вечір")
async def archive_event(message: types.Message):
    conn = await get_connection()
    try:
        event = await conn.fetchrow("SELECT event_id, title FROM events WHERE status = 'active' ORDER BY created_at DESC LIMIT 1")
        if event:
            await conn.execute("UPDATE events SET status = 'closed' WHERE event_id = $1", event['event_id'])
            await message.answer(f"✅ Івент {event['title']} завершено.")
        else:
            await message.answer("ℹ️ Немає активних івентів.")
    finally:
        await conn.close()

# ================== PAYMENT ==================

@dp.message(F.text == "💳 Оплатити ігри")
async def send_payment_info(message: types.Message):
    text = "💳 **Оплата ігрових вечорів**\n\n`4441111070738616`\n\nПісля оплати натисніть кнопку 👇"
    await message.answer(text, parse_mode="Markdown", reply_markup=payment_keyboard())

@dp.callback_query(F.data == "confirm_payment")
async def confirm_pay(callback: types.CallbackQuery):
    await bot.send_message(444726017, f"💰 **Оплата!**\n👤 {callback.from_user.full_name}\n🆔 `{callback.from_user.id}`")
    await callback.answer("✅ Адміністратора сповіщено!", show_alert=True)

# ================== RUNNER ==================
async def handle(request): return web.Response(text="Bot is running!")
async def start_all():
    await init_db()
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', int(os.environ.get("PORT", 8000))).start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(start_all())
