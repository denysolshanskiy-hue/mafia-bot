from aiogram import types
from aiogram.dispatcher import Dispatcher
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def get_season_menu(is_admin=False):
    kb = ReplyKeyboardMarkup(resize_keyboard=True)

    kb.add("🏆 Мій рейтинг")
    kb.add("💰 Мій баланс")

    if is_admin:
        kb.add("💰 Нарахувати")
        kb.add("📊 Рейтинг")

    return kb


async def season_menu(message: types.Message):
    user_id = message.from_user.id

    # 👉 тут вставите свою перевірку адміна
    is_admin = user_id in [444726017]

    await message.answer(
        "Сезонне меню:",
        reply_markup=get_season_menu(is_admin)
    )


def register_handlers(dp: Dispatcher):
    dp.register_message_handler(season_menu, text="☣️ UNDERGROUND")
