from flask import Flask, request
import requests
import os
import json

app = Flask(__name__)

# Your WhatsApp API credentials
ACCESS_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_ID")

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")

# --- Helper Function to Send Messages ---
def send_whatsapp_message(to, message):
    url = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message}
    }
    requests.post(url, headers=headers, data=json.dumps(payload))


@app.route("/chatBot", methods=["GET"])
def verify():
    if request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge")
    return "Invalid verification token"


@app.route("/chatBot", methods=["POST"])
def webhook():
    data = request.get_json()

    try:
        entry = data["entry"][0]["changes"][0]["value"]
        messages = entry.get("messages")

        if messages:
            phone_number = messages[0]["from"]
            user_message = messages[0]["text"]["body"].strip().lower()

            # --- Menu Logic ---
            if user_message in ["hi", "hello", "menu", "start"]:
                send_whatsapp_message(
                    phone_number,
                    "👋 Hello! Welcome to the *Smart Road Maintenance Assistant*.\n\n"
                    "Please select one of the options below:\n"
                    "1️⃣ Register an issue\n"
                    "2️⃣ Report a pothole\n"
                    "3️⃣ Track your complaint\n"
                    "4️⃣ About this service"
                )

            elif user_message == "1" or "register" in user_message:
                send_whatsapp_message(
                    phone_number,
                    "📝 To register an issue, please click the link below:\n"
                    "👉 https://smartroads.ap.gov/register?user=" + phone_number
                )

            elif user_message == "2" or "pothole" in user_message:
                send_whatsapp_message(
                    phone_number,
                    "📸 To report a pothole, please visit:\n"
                    "👉 https://smartroads.ap.gov/report?user=" + phone_number
                )

            elif user_message == "3" or "track" in user_message:
                send_whatsapp_message(
                    phone_number,
                    "🔍 Track your complaint status here:\n"
                    "👉 https://smartroads.ap.gov/track?user=" + phone_number
                )

            elif user_message == "4" or "about" in user_message:
                send_whatsapp_message(
                    phone_number,
                    "ℹ️ This service helps citizens report potholes and road issues directly "
                    "to the concerned authorities for faster response. Together, we can make AP pothole-free!"
                )

            else:
                send_whatsapp_message(
                    phone_number,
                    "🤖 Sorry, I didn’t understand that.\n"
                    "Type *menu* to see available options."
                )

    except Exception as e:
        print("Error:", e)

    return "OK", 200


if __name__ == "__main__":
    app.run(port=5000, debug=True)



