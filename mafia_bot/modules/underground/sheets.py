import gspread
from oauth2client.service_account import ServiceAccountCredentials

SHEET_NAME = "UNDERGROUND"

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

import os
import json

creds_json = os.getenv("GOOGLE_CREDENTIALS")
creds_dict = json.loads(creds_json)

creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)

client = gspread.authorize(creds)

spreadsheet = client.open(SHEET_NAME)

players_sheet = spreadsheet.worksheet("Players")
results_sheet = spreadsheet.worksheet("Results")
events_sheet = spreadsheet.worksheet("Events")

if result_exists(event_id, player_id):
    await message.answer("❌ Вже нараховано цьому гравцю")
    return


def get_player(player_id):
    data = players_sheet.get_all_records()
    for row in data:
        if str(row["player_id"]) == str(player_id):
            return row
    return None

def add_player(player_id, nick):
    players_sheet.append_row([
        player_id,
        nick,
        0,  # balance
        0,  # current_streak
        0   # total_games
    ])

def update_player(player_id, balance, streak, total_games):
    data = players_sheet.get_all_records()

    for i, row in enumerate(data, start=2):
        if str(row["player_id"]) == str(player_id):
            players_sheet.update(f"C{i}", balance)
            players_sheet.update(f"D{i}", streak)
            players_sheet.update(f"E{i}", total_games)
            break

def is_event_processed(event_id):
    data = events_sheet.get_all_records()
    for row in data:
        if str(row["event_id"]) == str(event_id):
            return row["processed"] == 1
    return False

def mark_event_processed(event_id):
    data = events_sheet.get_all_records()

    for i, row in enumerate(data, start=2):
        if str(row["event_id"]) == str(event_id):
            events_sheet.update(f"C{i}", 1)
            break

from datetime import datetime

def add_result(event_id, player_id, place, mvp, best_move, sheriff, income):
    results_sheet.append_row([
        event_id,
        player_id,
        place,
        mvp,
        best_move,
        sheriff,
        income,
        datetime.now().strftime("%Y-%m-%d %H:%M")
    ])
def result_exists(event_id, player_id):
    data = results_sheet.get_all_records()

    for row in data:
        if str(row["event_id"]) == str(event_id) and str(row["player_id"]) == str(player_id):
            return True

    return False

MAX_BALANCE = 2500

new_balance = min(balance + income, MAX_BALANCE)
income = new_balance - balance

def get_top_players():
    data = players_sheet.get_all_records()
    return sorted(data, key=lambda x: int(x["balance"]), reverse=True)

@router.message(F.text == "📊 Рейтинг")
async def show_rating(message: types.Message):
    players = get_top_players()

    if not players:
        await message.answer("❌ Немає даних")
        return

    text = "🏆 Рейтинг:\n\n"

    for i, p in enumerate(players[:10], start=1):
        text += f"{i}. {p['nick']} — {p['balance']} 💰\n"

    await message.answer(text)

@router.message(F.text == "💰 Мій баланс")
async def my_balance(message: types.Message):
    player = get_player(message.from_user.id)

    if not player:
        await message.answer("❌ Ви ще не грали")
        return

    await message.answer(
        f"💰 Баланс: {player['balance']}\n"
        f"🔥 Стрік: {player['current_streak']}"
    )
