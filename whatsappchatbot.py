import requests
import json
from flask import Flask, request

app = Flask(__name__)

ACCESS_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_ID")

@app.route("/chatBot", methods=["POST"])
def webhook():
    data = request.get_json()

    if "messages" in data["entry"][0]["changes"][0]["value"]:
        message = data["entry"][0]["changes"][0]["value"]["messages"][0]
        sender = message["from"]

        if message.get("text", {}).get("body", "").lower() in ["hi", "hello"]:
            send_interactive_message(sender)

        elif message.get("button"):
            button_text = message["button"]["text"]
            handle_button_click(sender, button_text)

    return "ok", 200


def send_interactive_message(recipient):
    """Send buttons for user selection."""
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": "Thanks for contacting Smart Road Assist.\nPlease choose an option below:"},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "report_pothole", "title": "🕳️ Report Pothole"}},
                    {"type": "reply", "reply": {"id": "register_complaint", "title": "📝 Register Complaint"}},
                    {"type": "reply", "reply": {"id": "check_status", "title": "📊 Check Status"}}
                ]
            }
        }
    }

    requests.post(url, headers=headers, json=payload)


def handle_button_click(recipient, button_text):
    """Handle user selection."""
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    if "Report" in button_text:
        msg = "Please report potholes using: https://smartroads.gov/report"
    elif "Register" in button_text:
        msg = "You can register complaints here: https://smartroads.gov/complaints"
    elif "Status" in button_text:
        msg = "Track your issue here: https://smartroads.gov/status"
    else:
        msg = "Please select a valid option."

    payload = {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "text",
        "text": {"body": msg}
    }

    requests.post(url, headers=headers, json=payload)


if __name__ == "__main__":
    app.run(port=5000)


