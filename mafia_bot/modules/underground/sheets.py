import os
import json
from datetime import datetime

import gspread
from oauth2client.service_account import ServiceAccountCredentials


# ================= CONFIG =================
SHEET_NAME = "UNDERGROUND"

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]


# ================= AUTH =================
creds_json = os.getenv("GOOGLE_CREDENTIALS")

if not creds_json:
    raise Exception("❌ GOOGLE_CREDENTIALS not found")

try:
    creds_dict = json.loads(creds_json)
except Exception:
    raise Exception("❌ GOOGLE_CREDENTIALS is invalid JSON")

creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)


# ================= OPEN SHEET =================
spreadsheet = client.open(SHEET_NAME)

players_sheet = spreadsheet.worksheet("Players")
results_sheet = spreadsheet.worksheet("Results")
events_sheet = spreadsheet.worksheet("Events")


# ================= PLAYERS =================
def get_player(player_id):
    data = players_sheet.get_all_records()

    for row in data:
        # 👉 очищаємо ключі від пробілів
        clean_row = {k.strip(): v for k, v in row.items()}

        if str(clean_row.get("player_id")) == str(player_id):
            return clean_row

    return None


def add_player(player_id, nick):
    players_sheet.append_row([
        player_id,
        nick,
        0,  # balance
        0,  # current_streak
        0,  # total_games
        0,  # black_mark_used
        ""  # black_mark_type
    ])


def update_player(player_id, balance, streak, total_games):
    data = players_sheet.get_all_records()

    for i, row in enumerate(data, start=2):
        if str(row["player_id"]) == str(player_id):
            players_sheet.update(f"C{i}", [[balance]])
            players_sheet.update(f"D{i}", [[streak]])
            players_sheet.update(f"E{i}", [[total_games]])
            break


# ================= RESULTS =================
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


# ================= EVENTS =================
def is_event_processed(event_id):
    data = events_sheet.get_all_records()

    for row in data:
        if str(row["event_id"]) == str(event_id):
            return int(row.get("processed", 0)) == 1

    return False


def mark_event_processed(event_id):
    data = events_sheet.get_all_records()

    for i, row in enumerate(data, start=2):
        if str(row["event_id"]) == str(event_id):
            events_sheet.update(f"C{i}", 1)
            break


# ================= RATING =================
def get_top_players():
    data = players_sheet.get_all_records()
    return sorted(data, key=lambda x: int(x["balance"]), reverse=True)

# ================= BLACK MARK =================
def set_black_mark(player_id, bm_type):
    data = players_sheet.get_all_records()

    for i, row in enumerate(data, start=2):
        if str(row["player_id"]) == str(player_id):
            players_sheet.update(f"F{i}", [[1]])
            players_sheet.update(f"G{i}", [[bm_type]])
            break
