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
from aiogram.client.session.aiohttp import AiohttpSession

# Імпортуємо функції з вашого нового database.py
from database import get_connection, init_db

# ================== INIT ==================
# Отримуємо токен з Environment Variables Koyeb
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
    action: str   # join | ignore | cancel
    event_id: int

# ================== KEYBOARDS ==================
def invite_keyboard(event_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Записатись",
                    callback_data=InviteCallback(action="join", event_id=event_id).pack(),
                ),
                InlineKeyboardButton(
                    text="❌ Ігнорувати",
                    callback_data=InviteCallback(action="ignore", event_id=event_id).pack(),
                ),
            ]
        ]
    )

def cancel_keyboard(event_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Скасувати запис",
                    callback_data=InviteCallback(action="cancel", event_id=event_id).pack(),
                )
            ]
        ]
    )

def player_menu_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📅 Активні події")]],
        resize_keyboard=True,
    )

def player_menu_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Активні події")],
            [KeyboardButton(text="👥 Список гравців")],
        ],
        resize_keyboard=True
    )


def admin_menu_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Створити івент")],
            [KeyboardButton(text="📅 Активні події")],
            [KeyboardButton(text="👥 Список гравців")],
            [KeyboardButton(text="🛠 Адмін: список + скасовані")],
            [KeyboardButton(text="❌ Скасувати івент")],
        ],
        resize_keyboard=True
    )


# ================== START / NICKNAME ==================

@dp.message(CommandStart())
async def start_handler(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username

    conn = await get_connection()
    try:
        # PostgreSQL використовує $1 замість ?
        row = await conn.fetchrow(
            "SELECT display_name, role FROM users WHERE user_id = $1",
            user_id,
        )

        if not row:
            await conn.execute(
                """
                INSERT INTO users (user_id, username, display_name, role)
                VALUES ($1, $2, NULL, 'player')
                """,
                user_id, username,
            )
            await message.answer(
                "👋 Вітаю!\n\nВведіть, будь ласка, ваш **нік** для ігор:",
                parse_mode="Markdown",
            )
            await state.set_state(NicknameState.waiting_for_nickname)
            return

        display_name, role = row['display_name'], row['role']
        
        if not display_name:
            await message.answer("Введіть, будь ласка, ваш **нік**:")
            await state.set_state(NicknameState.waiting_for_nickname)
            return

        keyboard = admin_menu_keyboard() if role == "admin" else player_menu_keyboard()
        await message.answer(
            f"З поверненням, **{display_name}** 👋",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
    finally:
        await conn.close()

@dp.message(NicknameState.waiting_for_nickname)
async def save_nickname(message: types.Message, state: FSMContext):
    nickname = message.text.strip()
    if len(nickname) < 2 or len(nickname) > 20:
        await message.answer("❌ Нік має бути від 2 до 20 символів.")
        return

    user_id = message.from_user.id
    conn = await get_connection()
    try:
        await conn.execute(
            "UPDATE users SET display_name = $1 WHERE user_id = $2",
            nickname, user_id,
        )
        await state.clear()
        await message.answer(
            f"✅ Готово! Ваш нік: **{nickname}**",
            parse_mode="Markdown",
            reply_markup=player_menu_keyboard(),
        )
    finally:
        await conn.close()

# ================== ACTIVE EVENTS ==================

@dp.message(F.text == "📅 Активні події")
async def show_active_events(message: types.Message):
    conn = await get_connection()
    try:
        events = await conn.fetch(
            """
            SELECT event_id, title, event_date, event_time
            FROM events
            WHERE status = 'active'
            ORDER BY created_at DESC
            """
        )
        
        if not events:
            await message.answer("ℹ️ Наразі немає активних івентів")
            return

        for ev in events:
            await message.answer(
                f"🎭 *{ev['title']}*\n📅 {ev['event_date']}\n⏰ {ev['event_time']}",
                parse_mode="Markdown",
                reply_markup=invite_keyboard(ev['event_id']),
            )
    finally:
        await conn.close()

# ================== CREATE EVENT (ADMIN) ==================

@dp.message(F.text == "➕ Створити івент")
async def create_event_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    conn = await get_connection()
    try:
        row = await conn.fetchrow("SELECT role FROM users WHERE user_id = $1", user_id)
        if not row or row['role'] != "admin":
            await message.answer("❌ У вас немає прав адміністратора")
            return

        await message.answer("📝 Введіть назву івенту (наприклад: Мафія Класика):")
        await state.set_state(CreateEventStates.waiting_for_title)
    finally:
        await conn.close()

@dp.message(CreateEventStates.waiting_for_title)
async def create_event_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await message.answer("📅 Введіть дату (наприклад: 20.01):")
    await state.set_state(CreateEventStates.waiting_for_date)

@dp.message(CreateEventStates.waiting_for_date)
async def create_event_date(message: types.Message, state: FSMContext):
    await state.update_data(event_date=message.text)
    await message.answer("⏰ Введіть час (наприклад: 19:00):")
    await state.set_state(CreateEventStates.waiting_for_time)

@dp.message(CreateEventStates.waiting_for_time)
async def create_event_time(message: types.Message, state: FSMContext):
    data = await state.get_data()
    title = data["title"]
    event_date = data["event_date"]
    event_time = message.text
    admin_id = message.from_user.id

    conn = await get_connection()
    try:
        # INSERT повертає ID в Postgres через RETURNING
        event_id = await conn.fetchval(
            """
            INSERT INTO events (title, event_date, event_time, status, created_by)
            VALUES ($1, $2, $3, 'active', $4)
            RETURNING event_id
            """,
            title, event_date, event_time, admin_id,
        )

        players = await conn.fetch("SELECT user_id FROM users WHERE is_active = 1")
        
        for p in players:
            try:
                await bot.send_message(
                    p['user_id'],
                    f"🔔 *Новий івент!*\n\n🎭 *{title}*\n📅 {event_date}\n⏰ {event_time}",
                    parse_mode="Markdown",
                    reply_markup=invite_keyboard(event_id),
                )
            except Exception:
                continue

        await state.clear()
        await message.answer("✅ Івент створено та розіслано гравцям!")
    finally:
        await conn.close()

# ================== JOIN / COMMENT / CANCEL ==================

@dp.callback_query(InviteCallback.filter(F.action == "join"))
async def invite_join(callback: types.CallbackQuery, callback_data: InviteCallback, state: FSMContext):
    user_id = callback.from_user.id
    event_id = callback_data.event_id

    conn = await get_connection()
    try:
        existing = await conn.fetchval(
            "SELECT 1 FROM registrations WHERE event_id = $1 AND user_id = $2 AND status = 'active'",
            event_id, user_id
        )
        if existing:
            await callback.answer("Ви вже записані на цей івент")
            return

        await conn.execute(
            """
            INSERT INTO registrations (event_id, user_id, status)
            VALUES ($1, $2, 'active')
            """,
            event_id, user_id
        )
        
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("Ви записані!")

        await state.set_state(CommentState.waiting_for_comment)
        await state.update_data(event_id=event_id)
        await bot.send_message(user_id, "💬 Напишіть коментар (наприклад: +1) або надішліть `-` щоб пропустити")
    finally:
        await conn.close()

@dp.message(CommentState.waiting_for_comment)
async def save_comment(message: types.Message, state: FSMContext):
    comment = None if message.text.strip() == "-" else message.text.strip()
    data = await state.get_data()
    event_id = data.get("event_id")
    user_id = message.from_user.id

    conn = await get_connection()
    try:
        await conn.execute(
            "UPDATE registrations SET comment = $1 WHERE event_id = $2 AND user_id = $3 AND status = 'active'",
            comment, event_id, user_id
        )
        
        event_info = await conn.fetchrow(
            "SELECT e.title, u.display_name, e.created_by FROM events e JOIN users u ON u.user_id = $1 WHERE e.event_id = $2",
            user_id, event_id
        )
        
        await state.clear()
        await message.answer("✅ Запис підтверджено!", reply_markup=cancel_keyboard(event_id))

        if event_info:
            await bot.send_message(
                event_info['created_by'],
                f"🆕 *Реєстрація*\n🎭 {event_info['title']}\n👤 {event_info['display_name']}\n💬 {comment or '—'}",
                parse_mode="Markdown"
            )
    finally:
        await conn.close()

@dp.callback_query(InviteCallback.filter(F.action == "cancel"))
async def invite_cancel(callback: types.CallbackQuery, callback_data: InviteCallback):
    user_id = callback.from_user.id
    event_id = callback_data.event_id

    conn = await get_connection()
    try:
        await conn.execute(
            "UPDATE registrations SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP WHERE event_id = $1 AND user_id = $2",
            event_id, user_id
        )
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("Запис скасовано")
        await bot.send_message(user_id, "❌ Ви скасували свій запис на івент")
    finally:
        await conn.close()

@dp.callback_query(InviteCallback.filter(F.action == "ignore"))
async def invite_ignore(callback: types.CallbackQuery):
    await callback.answer("Проігноровано")
    await callback.message.delete()

# ================== ADMIN ACTIONS ==================

@dp.message(F.text == "👥 Список гравців")
async def show_players_public(message: types.Message):
    conn = await get_connection()

    try:
        event = await conn.fetchrow(
            """
            SELECT event_id, title
            FROM events
            WHERE status = 'active'
            ORDER BY created_at DESC
            LIMIT 1
            """
        )

        if not event:
            await message.answer("ℹ️ Немає активних ігрових вечорів")
            return

        players = await conn.fetch(
            """
            SELECT u.display_name, r.comment
            FROM registrations r
            JOIN users u ON u.user_id = r.user_id
            WHERE r.event_id = $1
              AND r.status = 'active'
            ORDER BY r.created_at
            """,
            event["event_id"]
        )

        text = f"👥 *Гравці на івенті:* _{event['title']}_\n\n"

        if not players:
            text += "— Поки ніхто не записався"
        else:
            for i, p in enumerate(players, 1):
                comment = f" ({p['comment']})" if p["comment"] else ""
                text += f"{i}. {p['display_name']}{comment}\n"

        await message.answer(text, parse_mode="Markdown")

    finally:
        await conn.close()

@dp.message(F.text == "🛠 Адмін: список + скасовані")
async def show_players_admin(message: types.Message):
    user_id = message.from_user.id
    conn = await get_connection()

    try:
        role = await conn.fetchval(
            "SELECT role FROM users WHERE user_id = $1 AND is_active = 1",
            user_id
        )
        if role != "admin":
            await message.answer("❌ Команда доступна лише адміну")
            return

        event = await conn.fetchrow(
            """
            SELECT event_id, title
            FROM events
            WHERE status = 'active'
            ORDER BY created_at DESC
            LIMIT 1
            """
        )

        if not event:
            await message.answer("ℹ️ Немає активних івентів")
            return

        rows = await conn.fetch(
            """
            SELECT u.display_name, r.status, r.comment
            FROM registrations r
            JOIN users u ON u.user_id = r.user_id
            WHERE r.event_id = $1
            ORDER BY r.created_at
            """,
            event["event_id"]
        )

        active_players = []
        cancelled_players = []

        for r in rows:
            if r["status"] == "active":
                line = r["display_name"]
                if r["comment"]:
                    line += f" ({r['comment']})"
                active_players.append(line)
            elif r["status"] == "cancelled":
                cancelled_players.append(r["display_name"])

        text = f"🛠 *Адмін-звіт по івенту:* _{event['title']}_\n\n"

        text += "✅ *Активні:*\n"
        text += "\n".join(f"- {p}" for p in active_players) if active_players else "—"

        text += "\n\n❌ *Скасували:*\n"
        text += "\n".join(f"- {p}" for p in cancelled_players) if cancelled_players else "—"

        await message.answer(text, parse_mode="Markdown")

    finally:
        await conn.close()

# ================== RUNNER & WEB SERVER ==================

async def handle(request):
    return web.Response(text="Bot is running!")

async def start_all():
    # 1. Ініціалізація БД
    await init_db()

    # 2. Веб-сервер
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get("PORT", 8000)))
    await site.start()

    # 3. Бот
    print("Starting bot...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(start_all())
    except (KeyboardInterrupt, SystemExit):
        pass


