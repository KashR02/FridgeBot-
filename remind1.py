"""
remind.py — Daily expiry checker
Run every morning via cron or GitHub Actions.
Reads the Google Sheet, asks Gemini how urgent each item is,
and sends a WhatsApp message with a smart summary.
"""

import os
from datetime import datetime, date
from twilio.rest import Client
from google import genai
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

client_ai = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# ── Google Sheets ─────────────────────────────────────────────────────────────
SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
          "https://www.googleapis.com/auth/drive"]

def get_all_items() -> list[dict]:
    creds = Credentials.from_service_account_file("google_creds.json", scopes=SCOPES)
    client = gspread.authorize(creds)
    sheet = client.open(os.getenv("SHEET_NAME", "FridgeExpiry")).sheet1
    return sheet.get_all_records()

# ── Gemini urgency assessment ─────────────────────────────────────────────────
def build_smart_reminder(items: list[dict]) -> str:
    today = date.today().isoformat()

    item_lines = "\n".join(
        f"- {row['Product']}: expires {row['Expiry Date']}"
        for row in items
        if row.get("Expiry Date")
    )

    if not item_lines:
        return None

    prompt = f"""
Today is {today}.

Here are the items currently in the user's fridge:
{item_lines}

Write a short, friendly WhatsApp message (max 200 words) that:
1. Tells them ONLY about items that need attention soon — use your judgment
   (dairy: warn 2-3 days before, bread: 1 day, cheese: 5 days, etc.)
2. Groups items smartly (e.g. "expiring today", "use within 2 days", "use this week")
3. Skips items with plenty of time left
4. If nothing needs attention, say everything looks fine
5. Keep it warm and conversational, like a helpful friend texting them

Return ONLY the message, no preamble.
"""

    response = client_ai.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )
    return response.text.strip()

# ── Send WhatsApp via Twilio ──────────────────────────────────────────────────
def send_whatsapp(message: str):
    client = Client(
        os.getenv("TWILIO_ACCOUNT_SID"),
        os.getenv("TWILIO_AUTH_TOKEN")
    )
    client.messages.create(
        from_=f"whatsapp:{os.getenv('TWILIO_WHATSAPP_FROM')}",
        to=f"whatsapp:{os.getenv('YOUR_PHONE_NUMBER')}",
        body=message
    )
    print(f"[{datetime.now()}] Reminder sent.")

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print(f"[{datetime.now()}] Running daily expiry check...")
    items = get_all_items()

    if not items:
        print("No items in sheet. Nothing to remind.")
        return

    message = build_smart_reminder(items)

    if message:
        send_whatsapp(message)
    else:
        print("Nothing urgent today.")

if __name__ == "__main__":
    main()
