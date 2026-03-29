 FridgeBot — AI-Powered Fridge Expiry Tracker

An AI agent that helps track grocery expiry dates and plan meals — all via WhatsApp.

## What it does
- Add groceries
- Smart reminders
- Delete items
- Check your fridge
- Meal planning
- Remembers your preferences
- New recipe ideas


## Architecture
You (WhatsApp)
     ↓
Twilio (WhatsApp bridge)
     ↓
aiagent.py (Flask webhook)
     ↓
Gemini AI (decides which tool to call)
     ↓
Tools: add, delete, list, expiry check, meal suggest, preferences
     ↓
Google Sheets (database)

Daily 8am (GitHub Actions)
     ↓
remind1.py → Gemini AI → Twilio → WhatsApp → You
```

## Tech Stack
| Python + Flask 
| Google Gemini API
| Twilio 
| Google Sheets 
| GitHub Actions


## How the AI Agent works
The agent has 7 tools:
- `add_items` — saves groceries to Google Sheets
- `delete_item` — removes an item when used
- `get_all_items` — lists everything in the fridge
- `get_expiring_soon` — checks what expires in 7 days
- `save_preference` — remembers your cooking habits
- `get_preferences` — reads your saved preferences
- `suggest_meals` — generates personalised meal plans



