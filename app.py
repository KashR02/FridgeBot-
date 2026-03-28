"""
app.py — WhatsApp webhook 
Receives a WhatsApp text like "milk March 30, eggs April 5"
Gemini parses it  - saves to Google Sheet -  replies with confirmation 
"""

import os
import json
from datetime import datetime
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse #Twilio's library to create responses to WhatsApp messages
import google.generativeai as genai
import gspread #Google Sheets API client library to interact with Google Sheets
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv() #Load environment variables from .env file, such as GEMINI_API_KEY and SHEET_NAME

app = Flask(__name__)
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# ── Google Sheets setup
SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
          "https://www.googleapis.com/auth/drive"]

def get_sheet():
    creds = Credentials.from_service_account_file("google_creds.json", scopes=SCOPES)
    client = gspread.Sauthorize(creds)
    sheet = client.open(os.getenv("SHEET_NAME", "FridgeExpiry")).sheet1
    return sheet

def ensure_headers(sheet):
    if sheet.row_values(1) != ["Product", "Expiry Date", "Added On"]:
        sheet.insert_row(["Product", "Expiry Date", "Added On"], 1)

# ── Gemini parsing
def parse_items_with_gemini(user_message: str) -> list[dict]:
    today = datetime.now().strftime("%Y-%m-%d")

    prompt = f"""
Today's date is {today}.

The user sent this message about groceries they bought:
\"\"\"{user_message}\"\"\"

Extract every product and its expiry date. Return ONLY a valid JSON array like:
[
  {{"product": "Milk", "expiry": "2025-03-30"}},
  {{"product": "Eggs", "expiry": "2025-04-05"}}
]

Rules:
- Dates must be in YYYY-MM-DD format.
- If the user says "March 30" assume the current or next upcoming year.
- If no expiry is mentioned for an item, skip it.
- Return ONLY the JSON array, no explanation, no markdown.
"""

    model = genai.GenerativeModel("gemini-2.0-flash")
    response = model.generate_content(prompt)
    raw = response.text.strip()
    print(f"Gemini raw response: {raw}")

    if raw.startswith("```"): # If Gemini wrapped the JSON in markdown, extract the content inside the code block
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    return json.loads(raw.strip()) # Convert the JSON string into a Python list of dictionaries



#Webhook endpoint for WhatsApp
@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    incoming = request.form.get("Body", "").strip() # Get the incoming WhatsApp message #form is how Twilio sends the message content #format of form data is defined by Twilio, "Body" contains the text message sent by the user
    resp = MessagingResponse() # Prepare a response object to reply to WhatsApp
    print(f"Received message: {incoming}")
    
    if not incoming: # If the message is empty, prompt the user with instructions
        resp.message("Send me your groceries like: \"milk March 30, eggs April 5\"")
        return str(resp)

    try:
        items = parse_items_with_gemini(incoming) # Use Gemini to parse the message into structured data  #items should be a list of dictionaries with "product" and "expiry" keys, e.g. [{"product": "Milk", "expiry": "2025-03-30"}, ...]   #incoming is the raw text message from the user, e.g. "milk March 30, eggs April 5"
    except Exception as e:
        resp.message(f"Sorry, I couldn't understand that. Try: \"milk March 30, eggs April 5\"\nError: {e}")
        return str(resp)
    print(f"Parsed items: {items}")

    if not items: # If Gemini didn't find any items, inform the user
        resp.message("I didn't find any items with expiry dates. Try: \"milk March 30, eggs April 5\"")
        return str(resp)

    try: # Save the parsed items to Google Sheets
        sheet = get_sheet()
        ensure_headers(sheet)
        today_str = datetime.now().strftime("%Y-%m-%d") # Get today's date to record when the item was added
        rows = [[item["product"], item["expiry"], today_str] for item in items] # Prepare rows to append to the sheet
        sheet.append_rows(rows) #rows is a list of lists, where each inner list represents a row to be added to the sheet, e.g. [["Milk", "2025-03-30", "2024-06-01"], ["Eggs", "2025-04-05", "2024-06-01"]]
    except Exception as e:
        resp.message(f"Parsed items but couldn't save to sheet: {e}")
        return str(resp)

    lines = [f"✅ Saved {len(items)} item(s) to your fridge tracker:\n"]
    print(f"Saving to sheet: {len(items)}")
    for item in items:
        lines.append(f"• {item['product']} → expires {item['expiry']}")
    resp.message("\n".join(lines)) # Send a confirmation message back to the user listing the saved items and their expiry dates
    return str(resp) #Converts response → XML → sent to WhatsApp


if __name__ == "__main__":
    app.run(debug=True, port=5000)
