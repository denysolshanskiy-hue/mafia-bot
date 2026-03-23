from aiogram import Router, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.state import StatesGroup, State

class AccrualState(StatesGroup):
    choosing_player = State()
    choosing_action = State()
    
router = Router()

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
#=================== MENU ========================
def get_season_menu(is_admin=False):
    keyboard = [
        [KeyboardButton(text="🏆 Мій рейтинг")],
        [KeyboardButton(text="💰 Мій баланс")]
    ]

    if is_admin:
        keyboard.append([KeyboardButton(text="💰 Нарахувати")])
        keyboard.append([KeyboardButton(text="📊 Рейтинг")])

    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True
    )


@router.message(lambda message: message.text == "☣️ UNDERGROUND")
async def season_menu(message: types.Message):
    user_id = message.from_user.id

    # 👉 вставте свій ID
    is_admin = user_id in [444726017]

    await message.answer(
        "Сезонне меню:",
        reply_markup=get_season_menu(is_admin)
    )
#======================== INCOME =========================
from aiogram import F
from modules.underground.postgres_reader import get_active_event, get_event_players

from aiogram.fsm.context import FSMContext

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

    keyboard = []
    for p in players:
        keyboard.append([KeyboardButton(text=p["display_name"])])

    kb = ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True
    )

    # 👉 зберігаємо event_id і список гравців
    await state.update_data(
        event_id=event["event_id"],
        players={p["display_name"]: p["user_id"] for p in players}
    )

    await state.set_state(AccrualState.choosing_player)

    await message.answer(
        f"🎭 {event['title']}\n\nОберіть гравця:",
        reply_markup=kb
    )

@router.message(AccrualState.choosing_player)
async def choose_player(message: types.Message, state: FSMContext):
    data = await state.get_data()
    players = data.get("players", {})

    player_name = message.text

    if player_name not in players:
        await message.answer("❌ Оберіть гравця кнопкою")
        return

    player_id = players[player_name]

    await state.update_data(
        selected_player_id=player_id,
        selected_player_name=player_name
    )

    # 👉 кнопки дій
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🥇 Топ 1"), KeyboardButton(text="🥈 Топ 2")],
            [KeyboardButton(text="🥉 Топ 3"), KeyboardButton(text="🔥 MVP")],
            [KeyboardButton(text="⚡ Хід"), KeyboardButton(text="👮 Шериф")],
            [KeyboardButton(text="❌ Нічого")]
        ],
        resize_keyboard=True
    )

    await state.set_state(AccrualState.choosing_action)

    await message.answer(
        f"👤 {player_name}\n\nОберіть результат:",
        reply_markup=kb
    )
from modules.underground.sheets import (
    get_player,
    add_player,
    update_player,
    add_result
)

MAX_BALANCE = 2500


@router.message(AccrualState.choosing_action)
async def apply_action(message: types.Message, state: FSMContext):
    action = message.text

    data = await state.get_data()

    player_id = data["selected_player_id"]
    player_name = data["selected_player_name"]
    event_id = data["event_id"]

    income = calculate_income(action)

    # 👉 отримуємо гравця з Sheets
    player = get_player(player_id)

    if not player:
        add_player(player_id, player_name)
        player = get_player(player_id)

    balance = int(player["balance"])
    streak = int(player["current_streak"])
    total_games = int(player["total_games"])

    # 👉 застосовуємо ліміт
    new_balance = balance + income

    if new_balance > MAX_BALANCE:
        income = MAX_BALANCE - balance
        new_balance = MAX_BALANCE

    # 👉 оновлення стріку
    if income > 0:
        streak += 1
    else:
        streak = 0

    total_games += 1

    # 👉 запис
    update_player(player_id, new_balance, streak, total_games)

    add_result(
        event_id=event_id,
        player_id=player_id,
        place=action,
        mvp=1 if action == "🔥 MVP" else 0,
        best_move=1 if action == "⚡ Хід" else 0,
        sheriff=1 if action == "👮 Шериф" else 0,
        income=income
    )

    await message.answer(
        f"✅ {player_name}\n"
        f"+{income} 💰\n"
        f"Баланс: {new_balance}"
    )

    await state.set_state(AccrualState.choosing_player)
