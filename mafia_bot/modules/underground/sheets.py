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
