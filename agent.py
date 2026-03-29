"""
agent.py — True AI Agent for Fridge Expiry Tracker
The agent decides which tools to call based on your WhatsApp message.
Tools: add_items, delete_item, get_all_items, get_expiring_soon, send_reminder
"""

import os
import json
from datetime import datetime, date, timedelta
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client as TwilioClient
from google import genai
from google.genai import types
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
client_ai = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# ── Google Sheets ─────────────────────────────────────────────────────────────
SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
          "https://www.googleapis.com/auth/drive"]

def get_sheet():
    creds = Credentials.from_service_account_file("google_creds.json", scopes=SCOPES)
    client = gspread.authorize(creds)
    sheet = client.open(os.getenv("SHEET_NAME", "Fridgebot")).sheet1
    return sheet

def ensure_headers(sheet):
    if sheet.row_values(1) != ["Product", "Expiry Date", "Added On"]:
        sheet.insert_row(["Product", "Expiry Date", "Added On"], 1)

# ══════════════════════════════════════════════════════════════════════════════
# TOOL FUNCTIONS — these are the actions the agent can take
# ══════════════════════════════════════════════════════════════════════════════

def add_items(items: list) -> str:
    """Save a list of grocery items with expiry dates to the sheet."""
    try:
        sheet = get_sheet()
        ensure_headers(sheet)
        today_str = date.today().isoformat()
        rows = [[item["product"], item["expiry"], today_str] for item in items]
        sheet.append_rows(rows)
        names = ", ".join(item["product"] for item in items)
        return f"Successfully added: {names}"
    except Exception as e:
        return f"Error adding items: {e}"


def delete_item(product_name: str) -> str:
    """Delete an item from the sheet by product name."""
    try:
        sheet = get_sheet()
        all_rows = sheet.get_all_values()
        for i, row in enumerate(all_rows):
            if row and row[0].lower() == product_name.lower():
                sheet.delete_rows(i + 1)
                return f"Successfully removed {product_name} from your fridge."
        return f"{product_name} was not found in your fridge."
    except Exception as e:
        return f"Error deleting item: {e}"


def get_all_items() -> str:
    """Get all items currently in the fridge."""
    try:
        sheet = get_sheet()
        rows = sheet.get_all_records()
        if not rows:
            return "Your fridge tracker is empty."
        lines = ["Here's everything in your fridge:\n"]
        for row in rows:
            lines.append(f"• {row['Product']} → expires {row['Expiry Date']}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error reading items: {e}"


def get_expiring_soon() -> str:
    """Get items expiring in the next 7 days."""
    try:
        sheet = get_sheet()
        rows = sheet.get_all_records()
        if not rows:
            return "Your fridge tracker is empty."
        today = date.today()
        expiring = []
        for row in rows:
            try:
                expiry = datetime.strptime(row["Expiry Date"], "%Y-%m-%d").date()
                days_left = (expiry - today).days
                if days_left <= 7:
                    expiring.append((row["Product"], expiry, days_left))
            except:
                continue
        if not expiring:
            return "Nothing is expiring in the next 7 days. You're all good!"
        lines = ["Items expiring soon:\n"]
        for product, expiry, days in sorted(expiring, key=lambda x: x[2]):
            if days < 0:
                lines.append(f"• {product} → EXPIRED {abs(days)} days ago!")
            elif days == 0:
                lines.append(f"• {product} → expires TODAY!")
            elif days == 1:
                lines.append(f"• {product} → expires TOMORROW!")
            else:
                lines.append(f"• {product} → expires in {days} days ({expiry})")
        return "\n".join(lines)
    except Exception as e:
        return f"Error checking expiry: {e}"


def send_whatsapp_message(message: str) -> str:
    """Send a WhatsApp message to the user."""
    try:
        client = TwilioClient(
            os.getenv("TWILIO_ACCOUNT_SID"),
            os.getenv("TWILIO_AUTH_TOKEN")
        )
        client.messages.create(
            from_=f"whatsapp:{os.getenv('TWILIO_WHATSAPP_FROM')}",
            to=f"whatsapp:{os.getenv('YOUR_PHONE_NUMBER')}",
            body=message
        )
        return "Message sent."
    except Exception as e:
        return f"Error sending message: {e}"


# ══════════════════════════════════════════════════════════════════════════════
# TOOL DEFINITIONS — tell Gemini what tools exist and what they do
# ══════════════════════════════════════════════════════════════════════════════

TOOLS = [
    types.Tool(function_declarations=[

        types.FunctionDeclaration(
            name="add_items",
            description="Add grocery items with expiry dates to the fridge tracker.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "items": types.Schema(
                        type=types.Type.ARRAY,
                        description="List of items to add",
                        items=types.Schema(
                            type=types.Type.OBJECT,
                            properties={
                                "product": types.Schema(type=types.Type.STRING, description="Product name"),
                                "expiry": types.Schema(type=types.Type.STRING, description="Expiry date in YYYY-MM-DD format"),
                            },
                            required=["product", "expiry"]
                        )
                    )
                },
                required=["items"]
            )
        ),

        types.FunctionDeclaration(
            name="delete_item",
            description="Remove an item from the fridge tracker when the user says they finished or used it.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "product_name": types.Schema(type=types.Type.STRING, description="Name of the product to remove"),
                },
                required=["product_name"]
            )
        ),

        types.FunctionDeclaration(
            name="get_all_items",
            description="Get a list of all items currently in the fridge tracker.",
            parameters=types.Schema(type=types.Type.OBJECT, properties={})
        ),

        types.FunctionDeclaration(
            name="get_expiring_soon",
            description="Check which items are expiring in the next 7 days.",
            parameters=types.Schema(type=types.Type.OBJECT, properties={})
        ),

    ])
]

# Map tool names to actual functions
TOOL_MAP = {
    "add_items": add_items,
    "delete_item": delete_item,
    "get_all_items": get_all_items,
    "get_expiring_soon": get_expiring_soon,
}

# ══════════════════════════════════════════════════════════════════════════════
# AGENT LOOP — the core of the agent
# ══════════════════════════════════════════════════════════════════════════════

def run_agent(user_message: str) -> str:
    """
    The agent loop:
    1. Send user message + tools to Gemini
    2. Gemini decides which tool to call
    3. We call the tool and get the result
    4. Send result back to Gemini
    5. Repeat until Gemini gives a final text response
    """
    today = date.today().isoformat()

    system_prompt = f"""You are a helpful fridge assistant. Today is {today}.
You help users track grocery expiry dates via WhatsApp.
You have tools to add items, delete items, check expiry, and list all items.
Always be friendly and conversational. Keep replies short and clear."""

    # Start conversation
    messages = [
        types.Content(role="user", parts=[types.Part(text=user_message)])
    ]

    # Agent loop — keep going until Gemini gives a text response
    for _ in range(5):  # max 5 iterations to prevent infinite loops
        response = client_ai.models.generate_content(
            model="gemini-2.5-flash",
            contents=messages,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                tools=TOOLS,
            )
        )

        part = response.candidates[0].content.parts[0]

        # If Gemini returns text — we're done!
        if hasattr(part, "text") and part.text:
            return part.text

        # If Gemini wants to call a tool
        if hasattr(part, "function_call") and part.function_call:
            fn_name = part.function_call.name
            fn_args = dict(part.function_call.args)

            print(f"Agent calling tool: {fn_name} with args: {fn_args}")

            # Call the actual function
            if fn_name in TOOL_MAP:
                tool_result = TOOL_MAP[fn_name](**fn_args)
            else:
                tool_result = f"Unknown tool: {fn_name}"

            print(f"Tool result: {tool_result}")

            # Add Gemini's tool call + our result to the conversation
            messages.append(types.Content(role="model", parts=[part]))
            messages.append(types.Content(
                role="user",
                parts=[types.Part(
                    function_response=types.FunctionResponse(
                        name=fn_name,
                        response={"result": tool_result}
                    )
                )]
            ))

    return "Sorry, I couldn't process that. Please try again."


# ══════════════════════════════════════════════════════════════════════════════
# WHATSAPP WEBHOOK
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    incoming = request.form.get("Body", "").strip()
    print(f"Received: {incoming}")

    resp = MessagingResponse()

    if not incoming:
        resp.message("Hi! Tell me about your groceries or ask what's expiring soon.")
        return str(resp)

    try:
        reply = run_agent(incoming)
        resp.message(reply)
    except Exception as e:
        print(f"Agent error: {e}")
        resp.message(f"Sorry, something went wrong: {e}")

    return str(resp)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
