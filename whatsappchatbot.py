import json
import subprocess
import ast
import mimetypes
from collections import deque
import os
import re
import threading
import requests
from openai import OpenAI
import gspread
from flask import Flask, request
from oauth2client.service_account import ServiceAccountCredentials
from gtts import gTTS
from dotenv import load_dotenv
import nest_asyncio
import uuid
import time

# allow Flask in Jupyter
nest_asyncio.apply()

# load config
# —– Credentials —–
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
PLACES_API_KEY = os.getenv("PLACES_API_KEY")


GOOGLE_CRED_JSON = os.getenv("GOOGLE_CRED_JSON")
creds_dict = json.loads(GOOGLE_CRED_JSON)

CONTACT_SHEET_ID    = os.getenv("CONTACT_SHEET_ID")
ACCOM_SHEET_ID      = os.getenv("ACCOM_SHEET_ID")
LOG_SHEET_ID        = os.getenv("LOG_SHEET_ID")



# in the next cell, before reading any env vars:
from dotenv import load_dotenv
from pathlib import Path

env_path = Path(os.getcwd()) / ".env"
print("Loading .env from", env_path)
load_dotenv(dotenv_path=env_path)

# sanity‐check:
import os
print("GOOGLE_CRED_PATH=", os.getenv("GOOGLE_CRED_PATH"))


# initialize OpenAI
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# initialize Google Sheets
scope = ["https://spreadsheets.google.com/feeds","https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
gc = gspread.authorize(creds)
contact_sheet = gc.open_by_key(CONTACT_SHEET_ID).sheet1
# accommodation uses a second sheet within same file
acc_ws = gc.open_by_key(ACCOM_SHEET_ID).get_worksheet(1)  # sheet index 1 → gid=15985547
log_sheet = gc.open_by_key(LOG_SHEET_ID).sheet1

# keep the last 10 turns per user
conversation_history = {}  # maps user_id → deque of message dicts
HISTORY_SIZE = 10

def record_message(user_id: str, role: str, content: str):
    """
    Append a message to the user's history deque.
    role is 'user' or 'assistant'.
    """
    hist = conversation_history.setdefault(user_id, deque(maxlen=HISTORY_SIZE))
    hist.append({"role": role, "content": content})
    

# in-memory session store
sessions = {}

REQUEST_LOC = "Please share your live location (📎 icon → 📍 Location → Share here)."
SCHEDULE = """📝Schedule for Today📝
9:30 AM – Reporting to Masjid/Markaz
10:30 AM – Waaz (live)
1:30 PM – Zohar Asar
2:00 PM – Lunch
5:30 PM – Istibsaar
6:35 PM – Magrib-Isha
7:15 PM – Majlis (live)
8:00 PM – Dinner
"""
FALLBACK = ("I’m sorry, I can’t help with that. "
            "Please send 'Hi' or ask something event-related.")

# WhatsApp send helpers
def send_text(to, body):
    # url = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_ID}/messages"
    # headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    # data = {"messaging_product":"whatsapp","to":to,"text":{"body":body}}
    # return requests.post(url, headers=headers, json=data)

    #temp code
    url = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "text": {"body": body}
    }
    res = requests.post(url, headers=headers, json=data)
    print("📤 Send response:", res.status_code, res.text)
    return res
    #temp code


#updated send auido function
def send_audio(to, path):
    # 1. Upload the audio file to WhatsApp
    up_url = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_ID}/media"
    
    mime_type = mimetypes.guess_type(path)[0] or "audio/ogg"  # fallback
    
    files = {
        "file": (
            path,
            open(path, "rb"),
            mime_type  # <- explicitly set MIME type
        )
    }

    params = {
        "messaging_product": "whatsapp",
        "type": "audio",
        "access_token": WHATSAPP_TOKEN
    }

    upload_res = requests.post(up_url, files=files, data=params)
    upload_data = upload_res.json()
    print("📤 Upload response:", upload_data)

    media_id = upload_data.get("id")
    if not media_id:
        print("❌ Failed to upload audio file to WhatsApp:", upload_data)
        return

    # 2. Send the uploaded audio to the user
    msg_url = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "audio",
        "audio": {"id": media_id}
    }

    send_res = requests.post(msg_url, headers=headers, json=payload)
    print("✅ Audio sent. Response:", send_res.json())
    return send_res

    

# Google Sheets lookups
def fetch_contact(sector):
    for row in contact_sheet.get_all_records():
        if row.get("Sector","").lower()==sector.lower():
            return (f"The contact for {sector} is:\n"
                    f"Name: {row['Name']}\nContact: {row['Contact']}")
    return "Contact info not found."


#updated fecth acc
def fetch_accommodation(its=None, name=None):
    for row in acc_ws.get_all_records():
        if its and str(row.get("ITSnumber", "")).strip() == str(its).strip():
            return (f"📋 *Accommodation Details for {row['Name']}*:\n"
                    f"🏠 Accommodation: {row['Accommodation']}\n"
                    f"📍 Screening: {row['Screening']}\n"
                    f"🍽️ Jaman: {row['Jaman']}")
        if name and row.get("Name", "").lower().strip() == name.lower().strip():
            return (f"📋 *Accommodation Details for {row['Name']}*:\n"
                    f"🏠 Accommodation: {row['Accommodation']}\n"
                    f"📍 Screening: {row['Screening']}\n"
                    f"🍽️ Jaman: {row['Jaman']}")
    return None

# Google Places helper
def get_nearby(lat,lng,cat):
    type_map = {
        "hospital":("hospital","hospital"),
        "medical":("pharmacy","medical store"),
        "grocery":("supermarket","grocery"),
        "hotel":("hotel","hotel"),
        "rental":("bike","bike rental"),
        "laundry":("laundry","laundry service"),
    }
    pt,kw = type_map[cat]
    url = ("https://maps.googleapis.com/maps/api/place/nearbysearch/json"
           f"?location={lat},{lng}&rankby=distance&type={pt}"
           f"&keyword={kw}&key={PLACES_API_KEY}")
    js = requests.get(url).json().get("results",[])[:2]
    emojis = {"hospital":"🏥","medical":"💊","grocery":"🛒","hotel":"🏨","rental":"🚲","laundry":"🧺"}
    note = ""
    if cat=="laundry":
        note = ("ℹ️ Data below is for laundry services. "
                "If religious needs matter, please verify with the provider.\n\n")
    out = note + "\n\n".join(
        f"{emojis[cat]} {cat.title()}\n"
        f"📍 {p['name']}\n"
        f"https://www.google.com/maps/search/?api=1&query="
        f"{p['geometry']['location']['lat']},{p['geometry']['location']['lng']}"
        for p in js
    )
    return out or "No places found nearby."


def transcribe_audio(media_id):
    print(f"📥 Getting media URL for: {media_id}")
    url = f"https://graph.facebook.com/v18.0/{media_id}"
    params = {"access_token": WHATSAPP_TOKEN}
    res = requests.get(url, params=params)
    media_url = res.json().get("url")
    
    if not media_url:
        print("❌ Media URL not found.")
        return None

    # Get the actual media bytes
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    audio_bytes = requests.get(media_url, headers=headers).content

    # Save to file
    with open("tmp.ogg", "wb") as f:
        f.write(audio_bytes)

    print("📂 Audio file saved. Transcribing...")

    # Use OpenAI Whisper API (make sure openai is initialized correctly)
    try:
        with open("tmp.ogg", "rb") as f:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="text"
            )
        print("📝 Transcription result:", transcript)
        return transcript.strip()
    except Exception as e:
        print("❌ Transcription error:", e)
        return None

        
        

def to_tanglish(txt):
    sys = (
    "You are a Tanglish translator helping Vizag visitors. Convert English sentences into natural Telugu, written using Roman letters only. "
    "Your replies must sound conversational and local to Vizag. Do not translate into Telugu script, do not give explanations, do not wrap output in quotes. "
    "Only return the Tanglish line — nothing else.\n\n"
    "Examples:\n"
    "I am hungry → Nenu akale padutunna\n"
    "Where is the hospital? → Hospital ekkada undi?\n"
    "Can you help me? → Nuvvu naaku help chesthava?\n"
    "I want to go to the beach → Nenu beach ki veyyali anukuntunna\n"
    "What's your name? → Nee peru enti?\n"
    "Hi, I am lost → Naku daari teliyatledu\n"
    "Can you help me? -> Nuvvu naaku help chesthava\n"
    "I want to go to the beach -> Nenu beach ki veyyali anukuntunna\n"
    "What's your name? -> Nee peru enti\n"
    "How are you? -> Ela unnavu\n"
    "Hi, I am lost -> Naku daari teliyatledu\n"
    "How much will you charge -> Miru enta vasulu cestaru\n"
    "\nTranslate this:"
)
    chat = [
        {"role":"system","content":sys},
        {"role":"user","content":txt}
    ]
    r = client.chat.completions.create(model="gpt-4o-mini", messages=chat)
    return r.choices[0].message.content.strip()




# def generate_tts(text, mp3_path="resp.mp3", ogg_path="resp.ogg"):
#     # Step 1: Generate MP3 using gTTS
#     tts = gTTS(text=text, lang="en")
#     tts.save(mp3_path)

#     # Step 2: Convert MP3 to OGG using FFmpeg
#     try:
#         subprocess.run(["ffmpeg", "-y", "-i", mp3_path, "-c:a", "libopus", ogg_path], check=True)
#         print("✅ Audio converted and saved:", ogg_path)
#     except subprocess.CalledProcessError as e:
#         print("❌ FFmpeg conversion failed:", e)
#         return None

#     return ogg_path

def generate_tts(text, mp3_path="resp.mp3", ogg_path="resp.ogg", retries=3, delay=3):
    for attempt in range(retries):
        try:
            print("🔊 Generating TTS (attempt", attempt + 1, ")")
            tts = gTTS(text=text, lang="en")
            tts.save(mp3_path)
            break  # exit the retry loop if successful
        except Exception as e:
            print("❌ TTS generation failed:", e)
            if attempt < retries - 1:
                print(f"⏳ Retrying in {delay} seconds...")
                time.sleep(delay)
            else:
                return None  # fail silently

    try:
        subprocess.run(["ffmpeg", "-y", "-i", mp3_path, "-c:a", "libopus", ogg_path], check=True)
        print("✅ Audio converted and saved:", ogg_path)
    except subprocess.CalledProcessError as e:
        print("❌ FFmpeg conversion failed:", e)
        return None

    return ogg_path
    
 

# Flask webhook
app = Flask(__name__)

@app.route("/chatBot", methods=["GET","POST"])
def chatBot():
    if request.method == "GET":
        mode  = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        if mode == "subscribe" and token == VERIFY_TOKEN:
            return request.args.get("hub.challenge"), 200
        return "Forbidden", 403


    #temp code for response
    if request.method == "POST":
        # ✅ Handle incoming WhatsApp messages
        data = request.get_json()
        print("📩 Incoming webhook:", data, flush=True)

        # Check if there’s a message
        if "entry" in data:
            for entry in data["entry"]:
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    messages = value.get("messages")
                    if messages:
                        msg = messages[0]
                        from_number = msg["from"]  # sender
                        text = msg.get("text", {}).get("body")  # message text
                        
                        print(f"💬 Got message from {from_number}: {text}", flush=True)

                        # TODO: call your reply function here
                        # send_message(from_number, "Hi! I got your message.")

        return "EVENT_RECEIVED", 200


        if messages:
            msg = messages[0]
            from_number = msg["from"]
            text = msg.get("text", {}).get("body")

            print(f"💬 Got message from {from_number}: {text}", flush=True)

            # ✅ Send reply back
            send_text(from_number, f"👋 Hi! You said: {text}")
        #tempcde above

    
    data = request.get_json(force=True)
    try:
        msg     = data["entry"][0]["changes"][0]["value"]["messages"][0]
        wa_from = data["entry"][0]["changes"][0]["value"]["contacts"][0]["wa_id"]
        wa_name = data["entry"][0]["changes"][0]["value"]["contacts"][0]["profile"]["name"]

        # ─── record the incoming text or location ───
        mtype = msg.get("type")
        if mtype == "text":
            txt = msg["text"]["body"]
            record_message(wa_from, "user", txt)
        elif mtype == "location":
            lat = msg["location"]["latitude"]
            lng = msg["location"]["longitude"]
            # store a simple representation of the location
            record_message(wa_from, "user", f"Location:{lat},{lng}")

        # ─── dispatch to your existing handlers ───
        handle(wa_from, msg, wa_name)

    except Exception as e:
        print("err", e)

    return "OK", 200


def handle(user, msg, userName):
    ts    = msg.get("timestamp")
    mtype = msg.get("type")
    content = ""

    if mtype == "text":
        txt     = msg["text"]["body"]
        content = txt
        branch_text(user, txt, userName)


    elif mtype == "audio":
        aid = msg["audio"]["id"]
        print(f"🎙️ Received audio message with ID: {aid}")
    
        # Step 1: Transcribe the audio
        txt = transcribe_audio(aid)
        print("📝 Transcript:", txt)

        if not txt:
            send_text(user, "Sorry, I had trouble understanding the audio message.")
            return

        # Step 2: Translate to Tanglish
        tang = to_tanglish(txt)
        print("🗣️ Tanglish Output:", tang)

        # Step 3: Generate TTS from Tanglish text
        path = generate_tts(tang)  # default is "resp.mp3"
        print("🔊 Audio path:", path)

        # Step 4: Send audio back to user
        send_audio(user, path)  

            
    elif mtype == "location":
        lat     = msg["location"]["latitude"]
        lng     = msg["location"]["longitude"]
        content = f"Loc:{lat},{lng}"
        branch_location(user, lat, lng)

    # append log to Google Sheets
    log_sheet.append_row([ts, user, mtype, content])


    
def branch_text(u, txt, name):
    l = txt.lower().strip()

    # ← Record the incoming user message
    record_message(u, "user", txt)

    """
    Uses OpenAI to generate a conversational reply based on the user's message.
    Personalizes with the user's name and handles everything—greetings, 
    schedule, emergency, directions, amenities, small talk—dynamically.
    """
    # 1) Build the system prompt once
    system_prompt = f"""
You are a friendly, interactive WhatsApp assistant for visitors to Vizag.
Whenever the user greets you (by saying “hi”, “hello”, or “hey”), reply **exactly** with this message, substituting in their name:

👋 Welcome to Vizag {name}!
Here’s your guide:
💬 Want to communicate with people in the local language Telugu, just send a voice note in English.
🗺️ Type "accomodation or venue" Enter your 8-digit ITS number.
📅 Type "schedule" for today’s schedule.
🏨 Type "hotel" for nearby hotels.
🏥 Type "hospital" for nearest hospitals.
💊 Type "medical" for medical stores.
🛒 Type "grocery" for supermarkets.
🚲 Type "rental" for bike rentals.
🧺 Type "laundry" for laundry.
🆘 Type "emergency" for helpdesk contacts.
🤖 Any BOT related queries please contact Mustafa Totanawala-+917032778652.

Your job is to understand any user message—typos, slang, short phrases—and reply 
in a conversational, helpful way. You know about:
- Providing today's schedule when asked.
- Giving emergency contacts when requested.
- Asking for location when the user wants nearby hotels, hospitals, etc.
- Answering follow‑ups like "I don't want this" by asking what they do want.
- If the user sends an 8-digit ITS number (e.g. 40450256), you don’t need to reply directly. Just wait for the backend to respond with the person's accommodation and screening details.
- Handling small talk politely.

Always personalize your replies by including the user's name ({name}) when it is appropriate,
and keep responses concise and friendly.
"""

#for fetching data from the sheet

    if txt.isdigit() and len(txt) == 8:
        acc_info = fetch_accommodation(its=txt)
        if acc_info:
            send_text(u, acc_info)
        else:
            send_text(u, "Sorry, I couldn't find any data for that ITS number.")
        return
    

    
    # ─── 3) Build the full message history ───
    history = list(conversation_history.get(u, []))
    # messages = [system] + history + [current user turn]
    messages = (
        [{"role": "system", "content": system_prompt}]
        + history
        + [{"role": "user", "content": txt}]
    )

    
    resp = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=messages,
        temperature=0.7,
    )
    assistant_reply = resp.choices[0].message.content.strip()

    
        # ─── 5) Your amenity shortcut (unchanged) ───
    for cat in ["hospital", "medical", "grocery", "hotel", "rental", "laundry"]:
        if cat in l:
            # record and ask for location
            record_message(u, "assistant", REQUEST_LOC)
            send_text(u, REQUEST_LOC)
            sessions[u] = {"category": cat}
            return
            

    # ─── 6) Record & send the assistant’s reply ───
    record_message(u, "assistant", assistant_reply)
    send_text(u, assistant_reply)


def branch_location(u, lat, lng):
    s = sessions.get(u, {})
    cat = s.get("category")
    if cat in ["hospital","medical","grocery","hotel","rental","laundry"]:
        send_text(u, get_nearby(lat,lng,cat))
        sessions.pop(u, None)
    else:
        send_text(u, "Location received but I’m not sure what you need. Please specify again.")


# run in background
def run_app():
    app.run(port=5000)

threading.Thread(target=run_app,daemon=True).start()

























