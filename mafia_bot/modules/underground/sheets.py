import gspread
from oauth2client.service_account import ServiceAccountCredentials

SHEET_NAME = "UNDERGROUND"

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

creds = ServiceAccountCredentials.from_json_keyfile_name(
    "credentials.json", scope
)

client = gspread.authorize(creds)

spreadsheet = client.open(SHEET_NAME)

players_sheet = spreadsheet.worksheet("Players")
results_sheet = spreadsheet.worksheet("Results")
events_sheet = spreadsheet.worksheet("Events")

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
