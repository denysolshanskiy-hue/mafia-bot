from aiogram import Router, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

router = Router()

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

@router.message(F.text == "💰 Нарахувати")
async def start_accrual(message: types.Message):
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

    await message.answer(
        f"🎭 {event['title']}\n\nОберіть гравця:",
        reply_markup=kb
    )
