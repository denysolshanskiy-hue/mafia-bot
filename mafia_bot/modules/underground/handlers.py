from aiogram import Router, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

router = Router()


def get_season_menu(is_admin=False):
    kb = ReplyKeyboardMarkup(resize_keyboard=True)

    kb.add(KeyboardButton(text="🏆 Мій рейтинг"))
    kb.add(KeyboardButton(text="💰 Мій баланс"))

    if is_admin:
        kb.add(KeyboardButton(text="💰 Нарахувати"))
        kb.add(KeyboardButton(text="📊 Рейтинг"))

    return kb


@router.message(lambda message: message.text == "☣️ UNDERGROUND")
async def season_menu(message: types.Message):
    user_id = message.from_user.id

    # 👉 вставте свій ID
    is_admin = user_id in [444726017]

    await message.answer(
        "Сезонне меню:",
        reply_markup=get_season_menu(is_admin)
    )
