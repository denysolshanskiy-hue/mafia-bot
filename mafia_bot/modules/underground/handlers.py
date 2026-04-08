from aiogram import Router, types, F
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from modules.underground.sheets import client, SHEET_NAME
from database import get_connection
from modules.keyboards import admin_menu_keyboard
from modules.keyboards import player_menu_keyboard
from modules.underground.postgres_reader import get_active_event, get_event_players
from modules.underground.sheets import (
    get_player,
    add_player,
    update_player,
    add_result,
    result_exists,
    set_black_mark,
    get_rating_table
)

router = Router()

# ================= FSM =================
class AccrualState(StatesGroup):
    choosing_player = State()
    choosing_action = State()


# ================= CONFIG =================
ADMIN_IDS = [444726017]


# ================= LOGIC =================
def calculate_income(action):
    return {
        "🥇 Топ 1": 150,
        "🔥 MVP": 100,
        "⭐️ Топ 5": 50,
        "⚡ Хід": 150,
        "👮 Шериф": 50,
        "❌ Нічого": 0
    }.get(action, 0)


def get_max_balance(player):
    if player.get("black_mark_type") == "limit":
        return 3000
    return 2500


def get_season_menu(is_admin=False):
    keyboard = [
        [KeyboardButton(text="🏆 Мій рейтинг")],
        [KeyboardButton(text="💰 Мій баланс")],
        [KeyboardButton(text="🫐 Black Mark")]
    ]

    if is_admin:
        keyboard.append([KeyboardButton(text="💰 Нарахувати")])
        keyboard.append([KeyboardButton(text="📊 Рейтинг")])

    keyboard.append([KeyboardButton(text="⬅️ Назад")])

    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


# ================= MENU =================
@router.message(F.text == "☣️ UNDERGROUND")
async def season_menu(message: types.Message):
    is_admin = message.from_user.id in ADMIN_IDS

    await message.answer(
        "Сезонне меню:",
        reply_markup=get_season_menu(is_admin)
    )


@router.message(F.text == "⬅️ Назад")
async def back_to_main(message: types.Message, state: FSMContext):
    await state.clear()

    if message.from_user.id in ADMIN_IDS:
        kb = admin_menu_keyboard()
    else:
        from modules.keyboards import player_menu_keyboard
        kb = player_menu_keyboard()

    await message.answer("Головне меню:", reply_markup=kb)


# ================= START ACCRUAL =================
@router.message(F.text == "💰 Нарахувати")
async def start_accrual(message: types.Message, state: FSMContext):
    event = await get_active_event()

    if not event:
        await message.answer("❌ Немає активного івенту")
        return

    players = await get_event_players(event["event_id"])

    if not players:
        await message.answer("❌ Немає гравців")
        return

    keyboard = [[KeyboardButton(text=p["display_name"])] for p in players]
    keyboard.append([KeyboardButton(text="⬅️ Назад")])

    await state.update_data(
        event_id=event["event_id"],
        event_title=event["title"],
        players={p["display_name"]: p["user_id"] for p in players}
    )

    await state.set_state(AccrualState.choosing_player)

    await message.answer(
        f"🎭 {event['title']}\n\nОберіть гравця:",
        reply_markup=ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
    )


# ================= CHOOSE PLAYER =================
@router.message(AccrualState.choosing_player)
async def choose_player(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад":
        await back_to_main(message, state)
        return

    data = await state.get_data()
    players = data.get("players", {})

    if message.text not in players:
        await message.answer("❌ Оберіть гравця кнопкою")
        return

    await state.update_data(
        selected_player_id=players[message.text],
        selected_player_name=message.text
    )

    keyboard = [
        [KeyboardButton(text="🥇 Топ 1"), KeyboardButton(text="🔥 MVP")],
        [KeyboardButton(text="⭐️ Топ 5"), KeyboardButton(text="⚡ Хід")],
        [KeyboardButton(text="👮 Шериф"), KeyboardButton(text="❌ Нічого")],
        [KeyboardButton(text="⬅️ Назад")]
    ]

    await state.set_state(AccrualState.choosing_action)

    await message.answer(
        f"👤 {message.text}\n\nОберіть результат:",
        reply_markup=ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
    )


# ================= APPLY ACTION =================
@router.message(AccrualState.choosing_action)
async def apply_action(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад":
        await start_accrual(message, state)
        return

    allowed_actions = [
        "🥇 Топ 1", "🔥 MVP", "⭐️ Топ 5",
        "⚡ Хід", "👮 Шериф", "❌ Нічого"
    ]

    if message.text not in allowed_actions:
        await message.answer("❌ Оберіть дію кнопкою")
        return

    data = await state.get_data()

    player_id = data["selected_player_id"]
    player_name = data["selected_player_name"]
    event_id = data["event_id"]
    event_title = data["event_title"]

    if result_exists(event_id, player_id, message.text):
        await message.answer("❌ Цей бонус вже нараховано")
        return

    income = calculate_income(message.text)
    player = get_player(player_id)
    if not player:
        add_player(player_id, player_name)
        player = get_player(player_id)

    balance = int(player["balance"])
    streak = int(player["current_streak"])
    total_games = int(player["total_games"])

    max_balance = get_max_balance(player)
    new_balance = min(balance + income, max_balance)
    income = new_balance - balance

    # 🔥 streak логіка
    if income > 0:
        streak += 1
    else:
        if player.get("black_mark_type") == "streak":
            # використовуємо 1 раз
            set_black_mark(player_id, "used_streak")
        else:
            streak = 0

    total_games += 1

    update_player(player_id, new_balance, streak, total_games)

    add_result(
        event_id=event_id,
        player_id=player_id,
        place=message.text,
        mvp=1 if message.text == "🔥 MVP" else 0,
        best_move=1 if message.text == "⚡ Хід" else 0,
        sheriff=1 if message.text == "👮 Шериф" else 0,
        income=income
    )

    await message.answer(
        f"✅ {player_name}\n+{income} 💰\nБаланс: {new_balance}"
    )

    players = data.get("players", {})
    keyboard = [[KeyboardButton(text=name)] for name in players.keys()]
    keyboard.append([KeyboardButton(text="⬅️ Назад")])

    await state.set_state(AccrualState.choosing_player)

    await message.answer(
        f"🎭 {event_title}\n\nОберіть наступного гравця:",
        reply_markup=ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
    )


# ================= BLACK MARK =================
@router.message(F.text.contains("Black Mark"))
async def black_mark_menu(message: types.Message):
    player = get_player(message.from_user.id)

    if not player:
        await message.answer("❌ Ви ще не грали")
        return

    if int(player.get("black_mark_used") or 0) == 1:
        await message.answer("❌ Ви вже використали Black Mark")
        return

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💰 Підняти ліміт до 3000")],
            [KeyboardButton(text="🔥 Зберегти стрік (1 раз)")],
            [KeyboardButton(text="⬅️ Назад")]
        ],
        resize_keyboard=True
    )

    await message.answer("🫐 Оберіть ефект:", reply_markup=kb)


@router.message(F.text.in_(["💰 Підняти ліміт до 3000", "🔥 Зберегти стрік (1 раз)"]))
async def apply_black_mark(message: types.Message, state: FSMContext):

    await state.clear()

    player = get_player(message.from_user.id)

    if not player:
        await message.answer("❌ Ви ще не грали")
        return

    if int(player.get("black_mark_used") or 0) == 1:
        await message.answer("❌ Ви вже використали Black Mark")
        return

    if message.text == "💰 Підняти ліміт до 3000":
        set_black_mark(message.from_user.id, "limit")
        await message.answer("🫐 BLACK MARK АКТИВОВАНО\n💰 Ліміт = 3000")
    else:
        set_black_mark(message.from_user.id, "streak")
        await message.answer("🫐 BLACK MARK АКТИВОВАНО\n🔥 Стрік буде врятовано 1 раз")

# ================= MY BALANCE =================
@router.message(F.text == "💰 Мій баланс")
async def my_balance(message: types.Message):
    player = get_player(message.from_user.id)

    if not player:
        await message.answer("❌ Ви ще не брали участь у сезоні")
        return

    balance = int(player.get("balance") or 0)
    streak = int(player.get("current_streak") or 0)
    games = int(player.get("total_games") or 0)

    bm_used = int(player.get("black_mark_used") or 0)
    bm_type = player.get("black_mark_type") or ""

    # 🫐 статус Black Mark
    if bm_used == 0:
        bm_text = "🫐 Доступний"
    elif bm_type == "limit":
        bm_text = "🫐 Використано (ліміт 3000)"
    elif bm_type == "streak":
        bm_text = "🫐 Використано (збереження стріку)"
    elif bm_type == "used_streak":
        bm_text = "🫐 Використано (вже спрацював)"
    else:
        bm_text = "🫐 Використано"

    await message.answer(
        f"""
💰 Ваш баланс: {balance}

🔥 Стрік: {streak}
🎮 Ігор зіграно: {games}

{bm_text}
"""
    )
# ================= MY RATING =================
@router.message(F.text == "🏆 Мій рейтинг")
async def my_rating(message: types.Message):

    players = get_rating_table()

    if not players:
        await message.answer("❌ Рейтинг поки не заповнений")
        return

    user_id = str(message.from_user.id)

    position = None

    for i, p in enumerate(players, start=1):
        if str(p.get("player_id")) == user_id:
            position = i
            break

    if position is None:
        await message.answer("❌ Вас немає в рейтингу")
        return

    # 🔝 топ 10
    top_text = ""

    for i, p in enumerate(players[:10], start=1):
        nick = p.get("nick")
        rating = float(p.get("rating") or 0)

        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "▫️"

        top_text += f"{medal} {nick} — {rating}\n"

    my_rating_value = float(players[position - 1].get("rating") or 0)

    await message.answer(
        f"""
🏆 РЕЙТИНГ СЕЗОНУ

{top_text}

━━━━━━━━━━━━━━

👤 Ви:
#{position} місце
📊 {my_rating_value}
"""
    )
#================= SYNC POSTGRES ========================
async def sync_players_from_db():
    conn = await get_connection()
    rows = await conn.fetch("SELECT user_id, display_name FROM users")

    from modules.underground.sheets import client, SHEET_NAME
    sheet = client.open(SHEET_NAME).worksheet("Players")

    existing_ids = set(sheet.col_values(1))

    added = 0

    for row in rows:
        user_id = str(row["user_id"])
        nickname = row["display_name"] or "NoName"

        if user_id not in existing_ids:
            sheet.append_row([
                user_id,
                nickname,
                0,
                0,
                0,
                0,
                ""
            ])
            added += 1

    await conn.close()

    return added

@router.message(Command("sync_players"))
async def sync_players(message: types.Message):
    added = await sync_players_from_db()
    await message.answer(f"✅ Додано гравців: {added}")
