import json
import mimetypes
from collections import deque
import os
import re
import threading
import requests
import openai
import gspread
from flask import Flask, request
from oauth2client.service_account import ServiceAccountCredentials
from gtts import gTTS
from dotenv import load_dotenv
import nest_asyncio
from pydub import AudioSegment
import uuid

# allow Flask in Jupyter
nest_asyncio.apply()

# load config
# —– Credentials (hard-coded) —–
WHATSAPP_TOKEN      = "EAAKE7ig6UCgBO77z83kqjhghkx5485QnhyiMo96P4ZBcg36AfmiQvZC5f6kyk6GZBItQHoXQK7yQvmZC7plM1h9DbvmCvUzXN0PFopPOEApi3uUFO4FLFZAkrtL9tgysbtDZAM2Kx5uVfqtSSNdHdGzOsbWuFLAtUvlS6avuGbugIqlWtFZCh96YCWqpXcD"
WHATSAPP_PHONE_ID   = "679431781920863"
VERIFY_TOKEN        = "new_verify_token"
os.getenv("GOOGLE_CRED_PATH")
creds_dict = json.loads(GOOGLE_CRED_PATH)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
CONTACT_SHEET_ID    = "1ZVTMO4cW2YZ3DaWZPv5HrTyiqMODBGFRk6NwODS-E0o"
ACCOM_SHEET_ID      = "1ZVTMO4cW2YZ3DaWZPv5HrTyiqMODBGFRk6NwODS-E0o"
LOG_SHEET_ID        = "1AcNgJGbcW4oTQb7gvCKCZGicpTln9SJ768hvkv6HVfA"



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
openai.api_key = OPENAI_API_KEY

# initialize Google Sheets
scope = ["https://spreadsheets.google.com/feeds","https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_CRED_PATH, scope)
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

EMERGENCY = """🚨 Emergency Response 🚨
Please call on-ground helpdesk:
Moiz Calcuttawala – +918686131482
Abdul Tambawala – +918247778793
"""
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
    url = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {"messaging_product":"whatsapp","to":to,"text":{"body":body}}
    return requests.post(url, headers=headers, json=data)


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

# audio transcription + Tanglish translator
def transcribe_audio(media_id):
    try:
        print("📥 Getting media URL for:", media_id)
        murl = f"https://graph.facebook.com/v18.0/{media_id}"
        info = requests.get(murl, params={"access_token": WHATSAPP_TOKEN}).json()
        print("🧾 Media Info:", info)

        url = info.get("url")
        if not url:
            print("❌ No URL found in media info")
            return ""

        # Get the audio data
        headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
        res = requests.get(url, headers=headers, stream=True)

        if res.status_code != 200:
            print(f"❌ Failed to download media: {res.status_code}")
            return ""

        fn = "tmp.ogg"
        with open(fn, "wb") as f:
            for chunk in res.iter_content(1024):
                f.write(chunk)

        # Verify file isn't empty or too short
        if os.path.getsize(fn) < 1000:
            print("❌ Audio file is too small or corrupted.")
            return ""

        print("📂 Audio file saved. Transcribing...")
        with open(fn, "rb") as f:
            result = openai.Audio.transcribe("whisper-1", f)

        print("📝 Transcription result:", result)
        return result["text"]

    except Exception as e:
        print("❌ Error in transcribe_audio:", e)
        return ""
        
        

def to_tanglish(txt):
    sys = (
        "You are a professional Telugu translator for Vizag visitors. "
        "Convert English sentences into spoken‐style Telugu (Tanglish) in Roman letters — "
        "no script, no explanations, only Tanglish output.\n\n"
        "Examples:\n"
        "User: I am hungry\n"
        "Tanglish: Nenu akale padutunna\n\n"
        "User: Where is the hospital?\n"
        "Tanglish: Hospital ekkada undi?\n\n"
        "User: Can you help me?\n"
        "Tanglish: Nuvvu naaku help chesthava?\n\n"
        "User: I want to go to the beach\n"
        "Tanglish: Nenu beach ki veyyali anukuntunna\n\n"
        "User: What's your name?\n"
        "Tanglish: Nee peru enti?\n\n"
        "Now translate the following:"
    )
    chat = [
        {"role":"system","content":sys},
        {"role":"user","content":txt}
    ]
    r = openai.ChatCompletion.create(model="gpt-4o-mini", messages=chat)
    return r.choices[0].message.content.strip()


#updated tts code
def generate_tts(text, out="resp.ogg"):
    # Step 1: Generate MP3 using gTTS
    tts = gTTS(text=text, lang="en")
    tts.save("temp.mp3")

    # Step 2: Convert MP3 to OGG (Opus) format
    mp3_audio = AudioSegment.from_mp3("temp.mp3")
    mp3_audio.export(out, format="ogg", codec="libopus")

    return out
    

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

Always personalize your replies by including the user's name ({name}) when appropriate,
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

    
    resp = openai.ChatCompletion.create(
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

