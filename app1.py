"""
app.py — WhatsApp webhook
Receives a WhatsApp text like "milk March 30, eggs April 5"
→ Gemini parses it → saves to Google Sheet → replies with confirmation
"""

import os
import json
from datetime import datetime
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from google import genai
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
client_ai = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# ── Google Sheets setup ──────────────────────────────────────────────────────
SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
          "https://www.googleapis.com/auth/drive"]

def get_sheet():
    print(f"Looking for sheet: '{os.getenv('SHEET_NAME')}'")  # add this
    creds = Credentials.from_service_account_file("google_creds.json", scopes=SCOPES)
    client = gspread.authorize(creds)
    sheet = client.open(os.getenv("SHEET_NAME", "FridgeBot")).sheet1
    return sheet

def ensure_headers(sheet):
    if sheet.row_values(1) != ["Product", "Expiry Date", "Added On"]:
        sheet.insert_row(["Product", "Expiry Date", "Added On"], 1)

# ── Gemini parsing ────────────────────────────────────────────────────────────
def parse_items_with_gemini(user_message: str) -> list[dict]:
    print(f"Parsing message with Gemini: {user_message}")
    today = datetime.now().strftime("%Y-%m-%d")

    prompt = f"""
Today's date is {today}.

The user sent this message about groceries they bought:
\"\"\"{user_message}\"\"\"

Extract every product and its expiry date. Return ONLY a valid JSON array like:
[
  {{"product": "Milk", "expiry": "2026-03-30"}},
  {{"product": "Eggs", "expiry": "2026-04-05"}}
]

Rules:
- Dates must be in YYYY-MM-DD format.
- If the user says "March 30" assume the current or next upcoming year.
- If no expiry is mentioned for an item, skip it.
- Return ONLY the JSON array, no explanation, no markdown.
"""

    response = client_ai.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )
    raw = response.text.strip()
    print(f"Gemini raw response: {raw}")

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    return json.loads(raw.strip())

# ── Webhook ───────────────────────────────────────────────────────────────────
@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    incoming = request.form.get("Body", "").strip()
    print(f"Received message1: {incoming}")
    resp = MessagingResponse()
    print(f"Received message: {incoming}")

    if not incoming:
        resp.message("Send me your groceries like: \"milk March 30, eggs April 5\"")
        return str(resp)

    try:
        items = parse_items_with_gemini(incoming)
        print(f"Parsed items: {items}")
    except Exception as e:
        print(f"GEMINI ERROR: {type(e).__name__}: {e}")  # add this
        resp.message(f"Sorry, I couldn't understand that. Error: {e}")
        return str(resp)

    if not items:
        resp.message("I didn't find any items with expiry dates. Try: \"milk March 30, eggs April 5\"")
        return str(resp)

    try:
        sheet = get_sheet()
        print("Connected to Google Sheet successfully.")
        ensure_headers(sheet)
        print("Ensured headers are set.")
        today_str = datetime.now().strftime("%Y-%m-%d")
        print(f"Prepared rows to insert: {items}")
        rows = [[item["product"], item["expiry"], today_str] for item in items]
        print(f"Appending rows to sheet: {rows}")
        sheet.append_rows(rows)
        print("Rows appended successfully.")
    except Exception as e:
        print(f"SHEET ERROR: {type(e).__name__}: {e}")  # add this
        resp.message(f"Parsed items but couldn't save to sheet: {e}")
        return str(resp)

    lines = [f"✅ Saved {len(items)} item(s) to your fridge tracker:\n"]
    for item in items:
        lines.append(f"• {item['product']} → expires {item['expiry']}")
    resp.message("\n".join(lines))
    return str(resp)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
