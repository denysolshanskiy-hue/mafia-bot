from aiogram import Router, types, F
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

from modules.keyboards import admin_menu_keyboard
from modules.underground.postgres_reader import get_active_event, get_event_players
from modules.underground.sheets import (
    get_player,
    add_player,
    update_player,
    add_result,
    result_exists
)

router = Router()

# ================= FSM =================
class AccrualState(StatesGroup):
    choosing_player = State()
    choosing_action = State()


# ================= CONFIG =================
ADMIN_IDS = [444726017]
MAX_BALANCE = 2500


# ================= LOGIC =================
def calculate_income(action):
    values = {
        "🥇 Топ 1": 150,
        "🔥 MVP": 100,
        "⭐️ Топ 5": 50,
        "⚡ Хід": 150,
        "👮 Шериф": 50,
        "❌ Нічого": 0
    }
    return values.get(action, 0)


def get_season_menu(is_admin=False):
    keyboard = [
        [KeyboardButton(text="🏆 Мій рейтинг")],
        [KeyboardButton(text="💰 Мій баланс")]
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

    await message.answer(
        "Головне меню:",
        reply_markup=admin_menu_keyboard()
    )


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

    # 🚫 антидубль
    if result_exists(event_id, player_id):
        await message.answer("❌ Цьому гравцю вже нараховано")
        return

    income = calculate_income(message.text)

    player = get_player(player_id)

    if not player:
        add_player(player_id, player_name)
        player = get_player(player_id)

    balance = int(player["balance"])
    streak = int(player["current_streak"])
    total_games = int(player["total_games"])

    new_balance = min(balance + income, MAX_BALANCE)
    income = new_balance - balance

    streak = streak + 1 if income > 0 else 0
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
        f"✅ {player_name}\n"
        f"+{income} 💰\n"
        f"Баланс: {new_balance}"
    )

    # 🔁 повертаємо список гравців
    players = data.get("players", {})
    keyboard = [[KeyboardButton(text=name)] for name in players.keys()]
    keyboard.append([KeyboardButton(text="⬅️ Назад")])

    await state.set_state(AccrualState.choosing_player)

    await message.answer(
        f"🎭 {event_title}\n\nОберіть наступного гравця:",
        reply_markup=ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
    )
