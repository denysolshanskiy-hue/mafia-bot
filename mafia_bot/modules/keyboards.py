from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def admin_menu_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Створити івент"), KeyboardButton(text="📅 Активні події")],
            [KeyboardButton(text="💳 Оплатити ігри"), KeyboardButton(text="🛠 Адмін: список + скасовані")],
            [KeyboardButton(text="✅ Підтвердити вечір"), KeyboardButton(text="🏁 Завершити вечір")],
            [KeyboardButton(text="❌ Скасувати івент")],
            [KeyboardButton(text="☣️ UNDERGROUND")]
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
