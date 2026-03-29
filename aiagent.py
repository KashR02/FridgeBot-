"""
agent.py — True AI Agent for Fridge Expiry Tracker
Tools: add_items, delete_item, get_all_items, get_expiring_soon,
       save_preference, get_preferences, suggest_meals
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

def get_sheet(sheet_name=None):
    creds = Credentials.from_service_account_file("google_creds.json", scopes=SCOPES)
    client = gspread.authorize(creds)
    workbook = client.open(os.getenv("SHEET_NAME", "Fridgebot"))
    if sheet_name:
        try:
            return workbook.worksheet(sheet_name)
        except:
            # Create the sheet if it doesn't exist
            return workbook.add_worksheet(title=sheet_name, rows=100, cols=5)
    return workbook.sheet1

def ensure_headers(sheet, headers):
    if sheet.row_values(1) != headers:
        sheet.insert_row(headers, 1)

# ══════════════════════════════════════════════════════════════════════════════
# TOOL FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def add_items(items: list) -> str:
    """Save a list of grocery items with expiry dates to the sheet."""
    try:
        sheet = get_sheet()
        ensure_headers(sheet, ["Product", "Expiry Date", "Added On"])
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


def save_preference(ingredient: str, dish: str) -> str:
    """Save a user's cooking preference — which dish they make with an ingredient."""
    try:
        sheet = get_sheet("Preferences")
        ensure_headers(sheet, ["Ingredient", "My Dish"])
        # Check if ingredient already exists and update it
        all_rows = sheet.get_all_values()
        for i, row in enumerate(all_rows):
            if row and row[0].lower() == ingredient.lower():
                sheet.update_cell(i + 1, 2, dish)
                return f"Updated your preference: {ingredient} → {dish}"
        # Otherwise add new row
        sheet.append_row([ingredient, dish])
        return f"Got it! I'll remember that you make {dish} with {ingredient} 😊"
    except Exception as e:
        return f"Error saving preference: {e}"


def get_preferences() -> str:
    """Get all saved cooking preferences."""
    try:
        sheet = get_sheet("Preferences")
        rows = sheet.get_all_records()
        if not rows:
            return "No preferences saved yet."
        lines = []
        for row in rows:
            lines.append(f"• {row['Ingredient']} → {row['My Dish']}")
        return "Your cooking preferences:\n" + "\n".join(lines)
    except Exception as e:
        return f"Error reading preferences: {e}"


def suggest_meals(mode: str) -> str:
    """
    Suggest meals based on expiring items and user preferences.
    mode: 'usual' = suggest dishes user already makes, 'new' = suggest new recipes
    """
    try:
        # Get expiring items
        sheet = get_sheet()
        rows = sheet.get_all_records()
        today = date.today()
        expiring = []
        for row in rows:
            try:
                expiry = datetime.strptime(row["Expiry Date"], "%Y-%m-%d").date()
                days_left = (expiry - today).days
                if days_left <= 7:
                    expiring.append(f"{row['Product']} (expires in {days_left} days)")
            except:
                continue

        # Get preferences
        pref_sheet = get_sheet("Preferences")
        pref_rows = pref_sheet.get_all_records()
        preferences = [f"{row['Ingredient']} → {row['My Dish']}" for row in pref_rows]

        if not expiring:
            return "Nothing is expiring soon so no urgent meal suggestions needed!"

        # Ask Gemini to suggest meals
        expiring_str = "\n".join(expiring)
        pref_str = "\n".join(preferences) if preferences else "No preferences saved yet."

        if mode == "usual":
            prompt = f"""The user wants to cook something they usually make.

Items expiring soon:
{expiring_str}

Their cooking preferences (ingredient → dish they usually make):
{pref_str}

Suggest 2-3 meals they can make using the expiring ingredients, 
prioritizing their saved preferences. Be specific and friendly.
Keep it short — this is a WhatsApp message."""
        else:
            prompt = f"""The user wants to try something new.

Items expiring soon:
{expiring_str}

Their usual preferences (so you can suggest something DIFFERENT):
{pref_str}

Suggest 2-3 new creative recipes using the expiring ingredients 
that are different from their usual dishes. Be specific and friendly.
Keep it short — this is a WhatsApp message."""

        response = client_ai.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        return response.text.strip()

    except Exception as e:
        return f"Error suggesting meals: {e}"


# ══════════════════════════════════════════════════════════════════════════════
# TOOL DEFINITIONS
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

        types.FunctionDeclaration(
            name="save_preference",
            description="Save the user's cooking preference — what dish they usually make with a specific ingredient.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "ingredient": types.Schema(type=types.Type.STRING, description="The ingredient"),
                    "dish": types.Schema(type=types.Type.STRING, description="The dish they usually make with it"),
                },
                required=["ingredient", "dish"]
            )
        ),

        types.FunctionDeclaration(
            name="get_preferences",
            description="Get all the user's saved cooking preferences.",
            parameters=types.Schema(type=types.Type.OBJECT, properties={})
        ),

        types.FunctionDeclaration(
            name="suggest_meals",
            description="Suggest meals based on expiring items. Use mode='usual' when user wants familiar dishes, mode='new' when they want to try something different.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "mode": types.Schema(
                        type=types.Type.STRING,
                        description="'usual' for familiar dishes, 'new' for creative new recipes"
                    ),
                },
                required=["mode"]
            )
        ),

    ])
]

# Map tool names to actual functions
TOOL_MAP = {
    "add_items": add_items,
    "delete_item": delete_item,
    "get_all_items": get_all_items,
    "get_expiring_soon": get_expiring_soon,
    "save_preference": save_preference,
    "get_preferences": get_preferences,
    "suggest_meals": suggest_meals,
}

# ══════════════════════════════════════════════════════════════════════════════
# AGENT LOOP
# ══════════════════════════════════════════════════════════════════════════════

def run_agent(user_message: str) -> str:
    today = date.today().isoformat()

    system_prompt = f"""You are a friendly fridge assistant. Today is {today}.
You help users track grocery expiry dates and plan meals via WhatsApp.

You have these tools:
- add_items: when user mentions groceries with expiry dates
- delete_item: when user says they finished or used something
- get_all_items: when user asks what's in their fridge
- get_expiring_soon: when user asks what's expiring
- save_preference: when user says "I usually make X with Y"
- get_preferences: when user asks what their preferences are
- suggest_meals: when user asks what to cook
  - use mode='usual' for "what should I cook" or "something usual"
  - use mode='new' for "suggest something new" or "try something different"

Always be warm, short and conversational. This is WhatsApp."""

    messages = [
        types.Content(role="user", parts=[types.Part(text=user_message)])
    ]

    for _ in range(5):
        response = client_ai.models.generate_content(
            model="gemini-2.5-flash",
            contents=messages,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                tools=TOOLS,
            )
        )

        part = response.candidates[0].content.parts[0]

        if hasattr(part, "text") and part.text:
            return part.text

        if hasattr(part, "function_call") and part.function_call:
            fn_name = part.function_call.name
            fn_args = dict(part.function_call.args)

            print(f"Agent calling tool: {fn_name} with args: {fn_args}")

            if fn_name in TOOL_MAP:
                tool_result = TOOL_MAP[fn_name](**fn_args)
            else:
                tool_result = f"Unknown tool: {fn_name}"

            print(f"Tool result: {tool_result}")

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
        resp.message("Hi! Tell me about your groceries, ask what's expiring, or ask what to cook!")
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
