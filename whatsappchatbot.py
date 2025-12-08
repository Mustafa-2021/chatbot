# import os
# import requests
# from flask import Flask, request

# app = Flask(__name__)

# ACCESS_TOKEN = os.getenv("WHATSAPP_TOKEN")
# PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_ID")

# @app.route("/chatBot", methods=["POST"])
# def webhook():
#     data = request.get_json()
#     if "messages" in data["entry"][0]["changes"][0]["value"]:
#         message = data["entry"][0]["changes"][0]["value"]["messages"][0]
#         sender = message["from"]
#         if message.get("type") == "text":
#             send_report_button(sender)
#     return "ok", 200

# def send_report_button(recipient):
#     """Send one CTA URL button to redirect user to report page."""
#     url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
#     headers = {
#         "Authorization": f"Bearer {ACCESS_TOKEN}",
#         "Content-Type": "application/json"
#     }

#     report_url = f"https://pothole-reporting-portal-922876587313.asia-south1.run.app/?user={recipient}"

#     payload = {
#         "messaging_product": "whatsapp",
#         "to": recipient,
#         "type": "interactive",
#         "interactive": {
#             "type": "cta_url",
#             "body": {
#                 "text": "👋 Welcome to Smart Road Assist!\nClick the button below to report a pothole."
#             },
#             "action": {
#                 "name": "cta_url",
#                 "parameters": {
#                     "display_text": "Report a Pothole",
#                     "url": report_url
#                 }
#             }
#         }
#     }

#     response = requests.post(url, headers=headers, json=payload)
#     if response.status_code != 200:
#         print("Error sending message:", response.text)
#     else:
#         print("✅ Message sent successfully!")

# if __name__ == "__main__":
#     app.run(port=5000)


import os
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

        # If user taps button
        if "interactive" in message:
            button_reply = message["interactive"]["button_reply"]["id"]

            if button_reply == "yes_report":
                send_cta_url(recipient=sender)

            elif button_reply == "no_exit":
                send_no_thanks(sender)

            return "ok", 200

        # If normal incoming message (text or otherwise)
        send_welcome_buttons(sender)

    return "ok", 200


def send_welcome_buttons(recipient):
    """Send welcome message with Yes/No reply buttons."""
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
            "body": {
                "text": "👋 Welcome to AP Pothole Reporting Portal!\nWould you like to report a pothole?"
            },
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {"id": "yes_report", "title": "Yes"}
                    },
                    {
                        "type": "reply",
                        "reply": {"id": "no_exit", "title": "No"}
                    }
                ]
            }
        }
    }

    requests.post(url, headers=headers, json=payload)


def send_cta_url(recipient):
    """Send CTA redirect button only after user selects YES."""

    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    report_url = f"https://pothole-reporting-portal-922876587313.asia-south1.run.app/?user={recipient}"

    payload = {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "interactive",
        "interactive": {
            "type": "cta_url",
            "body": {
                "text": "Great! Click below to report a pothole."
            },
            "action": {
                "name": "cta_url",
                "parameters": {
                    "display_text": "Report a Pothole",
                    "url": report_url
                }
            }
        }
    }

    requests.post(url, headers=headers, json=payload)


def send_no_thanks(recipient):
    """Send a thank-you message if user selects NO."""
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "text",
        "text": {"body": "Thank you for contacting us! If you wish to report a pothole later, just send a message anytime."}
    }

    requests.post(url, headers=headers, json=payload)


if __name__ == "__main__":
    app.run(port=5000)




