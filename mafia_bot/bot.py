import asyncio
import os
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from modules.keyboards import admin_menu_keyboard, player_menu_keyboard
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
from datetime import datetime, timedelta, time, date
import asyncio
from modules.underground.handlers import router as season_router
# Імпортуємо функції з вашого нового database.py
from database import get_connection, init_db
from datetime import datetime, timedelta, time
import pytz
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardRemove

# ================== INIT ==================
BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
EVENT_LOCATION = "📍 *Театр МО*\nвул. ст. лейтенанта Кагала, 38\n(головний вхід)"
# ================== STATES ==================
class CreateEventStates(StatesGroup):
    waiting_for_title = State()
    waiting_for_date = State()
    waiting_for_time = State()

class NicknameState(StatesGroup):
    waiting_for_nickname = State()

class CommentState(StatesGroup):
    waiting_for_comment = State()
    
class BroadcastStates(StatesGroup):
    choosing_event = State()
    typing_message = State()
    
# ================== CALLBACK DATA ==================
class InviteCallback(CallbackData, prefix="invite"):
    action: str   # join | ignore | cancel | list
    event_id: int

# ================== KEYBOARDS ==================

def admin_menu_keyboard():
    return ReplyKeyboardMarkup(
    keyboard=[
[KeyboardButton(text="➕ Створити івент"), KeyboardButton(text="📅 Активні події")],
[KeyboardButton(text="💳 Оплатити ігри"), KeyboardButton(text="🛠 Адмін: список + скасовані")],
[KeyboardButton(text="✅ Підтвердити вечір"), KeyboardButton(text="🏁 Завершити вечір")],
[KeyboardButton(text="❌ Скасувати івент"), KeyboardButton(text="📣 Повідомлення")],
[KeyboardButton(text="☣️ UNDERGROUND")]  # ← ОКРЕМИЙ РЯДОК
    ],
        resize_keyboard=True
    )

def player_menu_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Активні події")],
            [KeyboardButton(text="💳 Оплатити ігри")],
            [KeyboardButton(text="☣️ UNDERGROUND")]
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

def payment_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Я оплатив(ла)", callback_data="confirm_payment")]
        ]
    )

def cancel_keyboard(event_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Скасувати запис",
                    callback_data=InviteCallback(action="cancel", event_id=event_id).pack()
                )
            ]
        ]
    )

# ================== START / NICKNAME ==================
@dp.message(Command("clean"))
async def clean_keyboard(message: types.Message):
    if message.chat.type != "private":
        return
    await message.answer("Клавіатуру видалено", reply_markup=types.ReplyKeyboardRemove())
    
@dp.message(CommandStart())
async def start_handler(message: types.Message, state: FSMContext):
    if message.chat.type != "private":
        return
    user_id = message.from_user.id
    username = message.from_user.username
    conn = await get_connection()
    try:
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
# ================== Colse Event ==================
@dp.message(F.text == "🏁 Завершити вечір")
async def choose_event_to_close(message: types.Message):
    user_id = message.from_user.id
    conn = await get_connection()
    try:
        role = await conn.fetchval(
            "SELECT role FROM users WHERE user_id = $1",
            user_id
        )
        if role != "admin":
            return

        events = await conn.fetch(
            """
            SELECT event_id, title, event_date
            FROM events
            WHERE status = 'active'
            ORDER BY event_date
            """
        )

        if not events:
            await message.answer("ℹ️ Немає активних івентів.")
            return

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"🏁 {e['title']} ({e['event_date']})",
                        callback_data=f"close_event_{e['event_id']}"
                    )
                ]
                for e in events
            ]
        )

        await message.answer(
            "🔒 Оберіть івент, який потрібно **завершити**:",
            reply_markup=kb
        )

    finally:
        await conn.close()

@dp.callback_query(F.data.startswith("close_event_"))
async def close_event(callback: types.CallbackQuery):
    event_id = int(callback.data.split("_")[-1])
    conn = await get_connection()
    try:
        event = await conn.fetchrow(
            "SELECT title, event_date FROM events WHERE event_id = $1",
            event_id
        )
        if not event:
            await callback.answer("Івент не знайдено", show_alert=True)
            return

        await conn.execute(
            "UPDATE events SET status = 'closed' WHERE event_id = $1",
            event_id
        )

        await callback.message.edit_text(
            f"✅ Івент завершено:\n\n"
            f"🎭 *{event['title']}*\n"
            f"📅 {event['event_date']}",
            parse_mode="Markdown"
        )

        await callback.answer("Івент завершено")

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
            event_date_str = ev["event_date"].strftime("%d.%m.%Y")

            await message.answer(
                f"🎭 *{ev['title']}*\n"
                f"📅 {event_date_str}\n"
                f"⏰ {ev['event_time']}\n\n"
                f"{EVENT_LOCATION}",
                parse_mode="Markdown",
                reply_markup=invite_keyboard(ev["event_id"])
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
    raw = message.text.strip()

    try:
        # очікуємо формат 07.02. або 07.02
        event_date = datetime.strptime(raw.rstrip("."), "%d.%m").date()

        # автоматично підставляємо поточний рік
        event_date = event_date.replace(year=datetime.now().year)

    except ValueError:
        await message.answer("❌ Невірний формат дати. Введіть, будь ласка, так: 07.02")
        return

    await state.update_data(event_date=event_date)
    await message.answer("⏰ Введіть час (наприклад: 19:00):")
    await state.set_state(CreateEventStates.waiting_for_time)

@dp.message(CreateEventStates.waiting_for_time)
async def create_event_time(message: types.Message, state: FSMContext):
    data = await state.get_data()
    title = data["title"]
    event_date = data["event_date"]
    event_time = message.text.strip()
    admin_id = message.from_user.id

    conn = await get_connection()
    try:
        event_id = await conn.fetchval(
            """
            INSERT INTO events (title, event_date, event_time, status, created_by)
            VALUES ($1, $2, $3, 'active', $4)
            RETURNING event_id
            """,
            title, event_date, event_time, admin_id
        )

        event_date_str = event_date.strftime("%d.%m.%Y")

        players = await conn.fetch(
            "SELECT user_id FROM users WHERE is_active = 1"
        )

        sent_count = 0
        for p in players:
            try:
                await bot.send_message(
                    p["user_id"],
                    f"🔔 *Новий івент!*\n\n"
                    f"🎭 *{title}*\n"
                    f"📅 {event_date_str}\n"
                    f"⏰ {event_time}",
                    parse_mode="Markdown",
                    reply_markup=invite_keyboard(event_id)
                )
                sent_count += 1
            except Exception:
                continue

        await state.clear()
        await message.answer(
            f"✅ Івент створено!\n📢 Запрошення розіслано гравцям: **{sent_count}**",
            parse_mode="Markdown"
        )

    finally:
        await conn.close()
#=================== COMMIT EVENT ====================
@dp.message(F.text == "✅ Підтвердити вечір")
async def confirm_event_start(message: types.Message):
    user_id = message.from_user.id
    conn = await get_connection()
    try:
        role = await conn.fetchval(
            "SELECT role FROM users WHERE user_id = $1",
            user_id
        )
        if role != "admin":
            return

        events = await conn.fetch("""
            SELECT event_id, title, event_date
            FROM events
            WHERE status = 'active'
            ORDER BY event_date
        """)

        if not events:
            await message.answer("ℹ️ Немає активних івентів для підтвердження.")
            return

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"🚀 {e['title']} ({e['event_date']})",
                    callback_data=f"send_confirm_{e['event_id']}"
                )]
                for e in events
            ]
        )

        await message.answer(
            "❓ Оберіть івент для надсилання підтвердження:",
            reply_markup=kb
        )

    finally:
        await conn.close()

@dp.callback_query(F.data.startswith("send_confirm_"))
async def process_send_confirmation(callback: types.CallbackQuery):
    event_id = int(callback.data.split("_")[2])
    conn = await get_connection()
    try:
        players = await conn.fetch(
            "SELECT user_id FROM registrations WHERE event_id = $1 AND status = 'active'", 
            event_id
        )
        if not players:
            await callback.answer("На цей івент ще ніхто не записався", show_alert=True)
            return
        success_count = 0
        for p in players:
            try:
                await bot.send_message(
                    p['user_id'], 
                    "✅ Ігровий вечір в силі! Чекаємо на тебе🫶"
                )
                success_count += 1
            except Exception:
                continue
        await callback.message.edit_text(
            f"✅ Підтвердження надіслано!\n👥 Гравців сповіщено: **{success_count}**",
            parse_mode="Markdown"
        )
        await callback.answer("Розсилку завершено")
    finally:
        await conn.close()

# ================== JOIN / COMMENT / CANCEL / LIST ==================

@dp.callback_query(InviteCallback.filter(F.action == "join"))
async def invite_join(
    callback: types.CallbackQuery,
    callback_data: InviteCallback,
    state: FSMContext
):
    user_id = callback.from_user.id
    event_id = callback_data.event_id

    conn = await get_connection()
    try:
        # 1️⃣ Беремо івент
        event = await conn.fetchrow(
            """
            SELECT event_id, title, status
            FROM events
            WHERE event_id = $1
            """,
            event_id
        )

        if not event:
            await callback.answer("🚫 Івент не знайдено", show_alert=True)
            return

        if event["status"] != "active":
            status_text = "вже завершений" if event["status"] == "closed" else "скасований"
            await callback.answer(f"🚫 Цей івент {status_text}.", show_alert=True)
            return

        # 2️⃣ Перевірка ніку
        user = await conn.fetchrow(
            "SELECT display_name FROM users WHERE user_id = $1",
            user_id
        )
        if not user or not user["display_name"]:
            await callback.answer(
                "❌ Спочатку вкажіть ваш нік у /start",
                show_alert=True
            )
            return

        # 3️⃣ Перевірка — чи вже записаний
        exists = await conn.fetchval(
            """
            SELECT 1
            FROM registrations
            WHERE event_id = $1
              AND user_id = $2
              AND status = 'active'
            """,
            event_id,
            user_id
        )
        if exists:
            await callback.answer("Ви вже записані на цей івент", show_alert=True)
            return

        # 4️⃣ Запис
        await conn.execute(
            """
            INSERT INTO registrations (event_id, user_id, status)
            VALUES ($1, $2, 'active')
            """,
            event_id,
            user_id
        )

        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("Ви записані!")

        # 5️⃣ Переходимо до коментаря
        await state.set_state(CommentState.waiting_for_comment)
        await state.update_data(event_id=event_id)

        await bot.send_message(
            user_id,
            f"🎭 *{event['title']}*\n\n💬 Напишіть коментар або `-` щоб пропустити",
            parse_mode="Markdown"
        )

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
        # 1️⃣ Оновлюємо коментар
        await conn.execute(
            """
            UPDATE registrations
            SET comment = $1
            WHERE event_id = $2
              AND user_id = $3
              AND status = 'active'
            """,
            comment,
            event_id,
            user_id
        )

        # 2️⃣ Дані івенту
        event = await conn.fetchrow(
            """
            SELECT title, created_by
            FROM events
            WHERE event_id = $1
            """,
            event_id
        )

        # 3️⃣ Нік користувача
        display_name = await conn.fetchval(
            "SELECT display_name FROM users WHERE user_id = $1",
            user_id
        )

        await state.clear()

        # 4️⃣ Повідомлення гравцю
        await message.answer(
            "✅ Запис підтверджено!",
            reply_markup=cancel_keyboard(event_id)
        )

        # 5️⃣ Повідомлення адміну (безпечне)
        if event and event["created_by"]:
            try:
                await bot.send_message(
                    event["created_by"],
                    (
                        "🆕 *Нова реєстрація*\n"
                        f"🎭 {event['title']}\n"
                        f"👤 {display_name}\n"
                        f"💬 {comment if comment else '—'}"
                    ),
                    parse_mode="Markdown"
                )
            except Exception as e:
                print(f"⚠️ Не вдалося надіслати повідомлення адміну: {e}")

    finally:
        await conn.close()

@dp.callback_query(InviteCallback.filter(F.action == "cancel"))
async def invite_cancel(callback: types.CallbackQuery, callback_data: InviteCallback):
    user_id = callback.from_user.id
    event_id = callback_data.event_id
    MY_ADMIN_ID = 444726017

    conn = await get_connection()
    try:
        # перевіряємо, чи є активний запис
        reg = await conn.fetchrow(
            """
            SELECT r.status, e.title
            FROM registrations r
            JOIN events e ON e.event_id = r.event_id
            WHERE r.event_id = $1
              AND r.user_id = $2
              AND r.status = 'active'
            """,
            event_id,
            user_id
        )

        # ❌ якщо запису немає — просто попап і НІЧОГО не ламаємо
        if not reg:
            await callback.answer(
                "❗ Ви не записані на цей івент",
                show_alert=True
            )
            return

        # якщо запис є — скасовуємо
        await conn.execute(
            """
            UPDATE registrations
            SET status = 'cancelled',
                updated_at = CURRENT_TIMESTAMP
            WHERE event_id = $1
              AND user_id = $2
            """,
            event_id,
            user_id
        )

        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("Запис скасовано")

        await bot.send_message(
            user_id,
            "❌ Ви скасували свій запис на івент"
        )

        # повідомлення адміну — ТІЛЬКИ якщо реально було що скасовувати
        if user_id != MY_ADMIN_ID:
            user_nick = await conn.fetchval(
                "SELECT display_name FROM users WHERE user_id = $1",
                user_id
            )
            display_name = user_nick or callback.from_user.full_name

            await bot.send_message(
                MY_ADMIN_ID,
                f"⚠️ **Скасування!**\n🎭 {reg['title']}\n👤 {display_name}",
                parse_mode="Markdown"
            )

    finally:
        await conn.close()

@dp.callback_query(InviteCallback.filter(F.action == "list"))
async def show_event_players(callback: types.CallbackQuery, callback_data: InviteCallback):
    conn = await get_connection()
    try:
        event = await conn.fetchrow(
            "SELECT title, created_at FROM events WHERE event_id = $1",
            callback_data.event_id
        )
        if not event:
            await callback.answer("Івент не знайдено", show_alert=True)
            return

        players = await conn.fetch(
            """
            SELECT u.display_name, r.comment
            FROM registrations r
            JOIN users u ON u.user_id = r.user_id
            WHERE r.event_id = $1
              AND r.status = 'active'
              AND r.created_at >= $2
            ORDER BY r.created_at
            """,
            callback_data.event_id,
            event["created_at"]
        )

        if not players:
            await callback.answer("На цей івент ще ніхто не записався", show_alert=True)
            return

        text = f"👥 Гравці на {event['title']}:\n\n"
        for i, p in enumerate(players, 1):
            comment = f" ({p['comment']})" if p["comment"] else ""
            text += f"{i}. {p['display_name']}{comment}\n"

        if len(text) > 3500:
            text = text[:3500] + "\n\n… список скорочено"

        await callback.message.answer(text)
        await callback.answer()

    finally:
        await conn.close()


@dp.callback_query(InviteCallback.filter(F.action == "ignore"))
async def invite_ignore(callback: types.CallbackQuery):
    await callback.answer("Проігноровано")
    await callback.message.delete()

# ================== PAY FOR GAMES ==================
@dp.message(F.text == "💳 Оплатити ігри")
async def send_payment_info(message: types.Message):
    payment_text = (
        "💳 **Оплата ігрових вечорів**\n\n"
        "Kremenchuk Mafia Club\n\n"
        "🖤 **MAFIA UNDERGROUND:**\n"
        "1 гра — 60 грн\n"
        "2 гри — 150 грн\n"
        "3 гри — 250 грн\n"
        "4-5 ігор — 300 грн\n\n"
        "🎲 **Звичайний вечір:**\n"
        "50 грн/гра або 250 грн/вечір\n\n"
        "💳 **Номер картки:**\n"
        "`4441111070738616`\n\n"
        "Після оплати натисніть кнопку 👇"
    )
    await message.answer(payment_text, parse_mode="Markdown", reply_markup=payment_keyboard())

@dp.callback_query(F.data == "confirm_payment")
async def process_payment_confirmation(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    MY_ADMIN_ID = 444726017
    conn = await get_connection()
    user_nick = await conn.fetchval("SELECT display_name FROM users WHERE user_id = $1", user_id)
    await conn.close()
    name = user_nick or callback.from_user.full_name
    await bot.send_message(MY_ADMIN_ID, f"💰 **Нове повідомлення про оплату!**\n👤 Гравець: {name}\n🆔 ID: `{user_id}`", parse_mode="Markdown")
    await callback.answer("✅ Повідомлення надіслано адміністратору!", show_alert=True)
    await callback.message.edit_reply_markup(reply_markup=None)

# ================== ADMIN ACTIONS ==================

@dp.message(F.text == "🛠 Адмін: список + скасовані")
async def show_players_admin(message: types.Message):
    user_id = message.from_user.id
    conn = await get_connection()

    try:
        # 1️⃣ Перевірка адміна
        role = await conn.fetchval(
            "SELECT role FROM users WHERE user_id = $1",
            user_id
        )
        if role != "admin":
            return

        # 2️⃣ Беремо ВСІ активні івенти
        events = await conn.fetch(
            """
            SELECT event_id, title, created_at
            FROM events
            WHERE status = 'active'
            ORDER BY created_at
            """
        )

        if not events:
            await message.answer("ℹ️ Немає активних івентів")
            return

        # 3️⃣ Для КОЖНОГО івенту формуємо окремий звіт
        for event in events:
            rows = await conn.fetch(
                """
                SELECT
                    u.display_name,
                    r.status,
                    r.comment
                FROM registrations r
                JOIN users u ON u.user_id = r.user_id
                WHERE r.event_id = $1
                  AND r.created_at >= $2
                ORDER BY r.created_at
                """,
                event["event_id"],
                event["created_at"]
            )

            active = []
            cancelled = []

            for r in rows:
                if r["status"] == "active":
                    name = r["display_name"]
                    if r["comment"]:
                        name += f" ({r['comment']})"
                    active.append(name)
                elif r["status"] == "cancelled":
                    cancelled.append(r["display_name"])

            # 4️⃣ Формуємо текст
            text = f"🛠 *Адмін-звіт: {event['title']}*\n\n"

            text += "✅ **Активні:**\n"
            text += (
                "\n".join(f"{i+1}. {p}" for i, p in enumerate(active))
                if active else "—"
            )

            text += "\n\n❌ **Скасували:**\n"
            text += (
                "\n".join(f"{i+1}. {p}" for i, p in enumerate(cancelled))
                if cancelled else "—"
            )

            await message.answer(text)

    finally:
        await conn.close()

@dp.message(F.text == "❌ Скасувати івент")
async def request_cancel_event(message: types.Message):
    user_id = message.from_user.id
    conn = await get_connection()
    try:
        row = await conn.fetchrow("SELECT role FROM users WHERE user_id = $1", user_id)
        if not row or row['role'] != "admin": return
        event = await conn.fetchrow("SELECT event_id, title, event_date, event_time FROM events WHERE status = 'active' LIMIT 1")
        if not event:
            await message.answer("ℹ️ Немає активних івентів для скасування.")
            return
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔥 ПІДТВЕРДИТИ СКАСУВАННЯ", callback_data=f"confirm_cancel_{event['event_id']}") ]])
        await message.answer(f"❓ Ви впевнені, що хочете скасувати івент:\n🎭 *{event['title']}* ({event['event_date']})?", parse_mode="Markdown", reply_markup=kb)
    finally:
        await conn.close()

@dp.callback_query(F.data.startswith("confirm_cancel_"))
async def admin_confirm_cancel(callback: types.CallbackQuery):
    event_id = int(callback.data.split("_")[2])
    conn = await get_connection()
    try:
        row = await conn.fetchrow("SELECT role FROM users WHERE user_id = $1", callback.from_user.id)
        if not row or row['role'] != "admin":
            await callback.answer("❌ Немає прав", show_alert=True)
            return
        players_to_notify = await conn.fetch("SELECT user_id FROM registrations WHERE event_id = $1 AND status = 'active'", event_id)
        await conn.execute("UPDATE events SET status = 'closed' WHERE event_id = $1", event_id)
        for p in players_to_notify:
            try: await bot.send_message(p['user_id'], "😔 На жаль, ігровий вечір скасовано. Слідкуйте за новими анонсами!")
            except: continue
        await callback.message.edit_text(f"✅ Івент успішно скасовано.\n👥 Сповіщено гравців: **{len(players_to_notify)}**", parse_mode="Markdown")
        await callback.answer("Івент скасовано")
    finally:
        await conn.close()

@dp.message(F.text == "📣 Повідомлення")
async def broadcast_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id

    conn = await get_connection()
    try:
        role = await conn.fetchval(
            "SELECT role FROM users WHERE user_id = $1",
            user_id
        )

        if role != "admin":
            return

        events = await conn.fetch("""
            SELECT event_id, title, event_date
            FROM events
            WHERE status = 'active'
            ORDER BY event_date
        """)

        if not events:
            await message.answer("❌ Немає активних івентів")
            return

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"{e['title']} ({e['event_date']})",
                        callback_data=f"broadcast_event_{e['event_id']}"
                    )
                ] for e in events
            ]
        )

        await message.answer("🎯 Оберіть івент:", reply_markup=kb)
        await state.set_state(BroadcastStates.choosing_event)

    finally:
        await conn.close()

@dp.callback_query(F.data.startswith("broadcast_event_"))
async def broadcast_choose_event(callback: types.CallbackQuery, state: FSMContext):
    event_id = int(callback.data.split("_")[2])

    await state.update_data(event_id=event_id)

    await callback.message.edit_text(
        "✍️ Введіть повідомлення для гравців:"
    )

    await state.set_state(BroadcastStates.typing_message)
    await callback.answer()

@dp.message(BroadcastStates.typing_message)
async def broadcast_send(message: types.Message, state: FSMContext):
    text = message.text
    data = await state.get_data()
    event_id = data.get("event_id")

    conn = await get_connection()
    try:
        # беремо івент
        event = await conn.fetchrow(
            "SELECT title FROM events WHERE event_id = $1",
            event_id
        )

        # беремо гравців
        users = await conn.fetch("""
            SELECT user_id
            FROM registrations
            WHERE event_id = $1
              AND status = 'active'
        """, event_id)

        if not users:
            await message.answer("❌ Немає зареєстрованих гравців")
            return

        sent = 0

        for u in users:
            try:
                await bot.send_message(
                    u["user_id"],
                    f"📣 *Оновлення по івенту*\n\n"
                    f"🎭 {event['title']}\n\n"
                    f"{text}",
                    parse_mode="Markdown"
                )
                sent += 1
            except:
                continue

        await message.answer(
            f"✅ Повідомлення відправлено!\n👥 Отримали: **{sent}**",
            parse_mode="Markdown"
        )

        await state.clear()

    finally:
        await conn.close()
# ================== REMINDER ==================
async def reminder_loop():
    tz = pytz.timezone("Europe/Kyiv")

    while True:
        now = datetime.now(tz)
        print("🕒 reminder loop alive:", now.strftime("%Y-%m-%d %H:%M:%S"))

        # рівно о 12:00 за Києвом
        if now.hour == 12:
            conn = await get_connection()
            try:
                events = await conn.fetch(
                    """
                    SELECT event_id, title, event_date
                    FROM events
                    WHERE status = 'active'
                      AND reminder_sent = false
                      AND event_date = (CURRENT_DATE + INTERVAL '1 day')::date
                    """
                )

                print(f"📦 events found: {len(events)}")

                for event in events:
                    event_id = event["event_id"]
                    title = event["title"]

                    print(f"➡️ processing event {event_id} | {title}")

                    users = await conn.fetch(
                        """
                        SELECT u.user_id
                        FROM users u
                        WHERE u.is_active = 1
                          AND NOT EXISTS (
                              SELECT 1
                              FROM registrations r
                              WHERE r.user_id = u.user_id
                                AND r.event_id = $1
                                AND r.status = 'active'
                          )
                        """,
                        event_id
                    )

                    sent = 0
                    for u in users:
                        try:
                            await bot.send_message(
                                u["user_id"],
                                f"⏰ *Нагадування!*\n\n"
                                f"Завтра відбудеться івент:\n"
                                f"🎭 *{title}*\n\n"
                                f"{EVENT_LOCATION}\n\n"
                                f"Ще є час записатись 👇",
                                parse_mode="Markdown",
                                reply_markup=invite_keyboard(event_id)
                            )
                            sent += 1
                        except Exception:
                            continue

                    await conn.execute(
                        "UPDATE events SET reminder_sent = true WHERE event_id = $1",
                        event_id
                    )

                    ADMIN_ID = 444726017
                    await bot.send_message(
                        ADMIN_ID,
                        f"📣 *Нагадування надіслано*\n"
                        f"🎭 {title}\n"
                        f"👥 Отримали: **{sent}**",
                        parse_mode="Markdown"
                    )

            finally:
                await conn.close()

        await asyncio.sleep(60)
# ================== UNDERGROUND =======================
dp.include_router(season_router)
# ================== RUNNER & WEB SERVER ==================

async def handle(request):
    return web.Response(text="Bot is running!")

async def start_all():
    await init_db()
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get("PORT", 8000)))
    await site.start()
    print("Starting bot...")
    asyncio.create_task(reminder_loop())
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(start_all())
    except (KeyboardInterrupt, SystemExit):
        pass













































