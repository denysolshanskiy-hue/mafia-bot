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
from aiogram.filters import Text

@router.message(Text("💰 Нарахувати"))
async def start_accrual(message: types.Message):
    await message.answer("Обробка івенту (скоро тут буде логіка)")
