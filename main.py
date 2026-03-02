import asyncio
import os
import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import WebAppInfo, MenuButtonWebApp
import google.generativeai as genai
from pydub import AudioSegment
import speech_recognition as sr

# --- SOZLAMALAR ---
API_TOKEN = '8723075538:AAFbLfxeHP84blCo2sfPOXOC8gFkp-C_NAo'
GEMINI_KEY = 'AIzaSyAIMsyORC4hte71JE9L9x4gUhwtCfOkn7M'
WEBAPP_URL = 'https://cretivy.github.io/debate_app/'

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

import json

# --- MA'LUMOTLAR ---
waiting_room = []
private_rooms = {} # {room_code: {"creator_id": id, "creator_name": name, "match_id": mid}}
active_matches = {}
user_profiles = {} # Foydalanuvchi yutuqlari (wins, awards)

ROLES = ["Leader", "Evidence", "Refuter", "Attacker", "Concluder"]
TURN_ORDER = [("A", 0), ("B", 0)] # Test uchun har jamoadan 1 tadan

# --- OVOZNI MATNGA O'GIRISH ---
async def voice_to_text(file_path):
    recognizer = sr.Recognizer()
    try:
        audio = AudioSegment.from_file(file_path)
        audio.export("temp.wav", format="wav")
        with sr.AudioFile("temp.wav") as source:
            audio_data = recognizer.record(source)
            return recognizer.recognize_google(audio_data, language="uz-UZ")
    except Exception as e:
        return f"[Ovozni aniqlab bo'lmadi: {e}]"

# --- START ---
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    user_id = message.from_user.id
    print(f"User {user_id} started the bot.")
    if user_id not in user_profiles:
        user_profiles[user_id] = {"wins": 0, "awards": []}

    awards_text = "\n".join(user_profiles[user_id]["awards"]) or "Hozircha yutuqlar yo'q"
    
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🚀 Ilovani ochish", web_app=WebAppInfo(url=WEBAPP_URL))]
        ],
        resize_keyboard=True
    )

    await message.answer(
        f"🔥 **Talk Clash Voice!**\n\n"
        f"🏆 **Sizning yutuqlaringiz:**\n{awards_text}\n\n"
        f"Debatni boshlash uchun quyidagi tugmani bosing.",
        reply_markup=keyboard
    )

# --- WEB APP DATA ---
@dp.message(F.web_app_data)
async def handle_web_app_data(message: types.Message):
    raw_data = message.web_app_data.data
    user_id = message.from_user.id
    print(f"LOG: WebApp data received: {raw_data} from user {user_id}")
    
    try:
        data = json.loads(raw_data)
        action = data.get("action")
        
        if action == "start_search":
            await join_debate(message)
            
        elif action == "create_room":
            room_code = data.get("code")
            name = data.get("name")
            match_id = f"pw_{user_id}_{int(datetime.datetime.now().timestamp())}"
            private_rooms[room_code] = {
                "creator_id": user_id,
                "creator_name": name,
                "match_id": match_id
            }
            await message.answer(f"✅ Komnata yaratildi! Kod: `{room_code}`\n\nRaqibingizga ushbu kodni bering. U kirganda debat boshlanadi.")
            
        elif action == "join_room":
            room_code = data.get("code")
            name = data.get("name")
            
            if room_code in private_rooms:
                room_info = private_rooms.pop(room_code)
                creator_id = room_info["creator_id"]
                match_id = room_info["match_id"]
                
                # Match yaratish
                active_matches[match_id] = {
                    "group_a": {creator_id: "Leader"},
                    "group_b": {user_id: "Leader"},
                    "turn_index": 0,
                    "status": "waiting",
                    "transcript": []
                }
                
                link_a = f"{WEBAPP_URL}?match_id={match_id}&role=A"
                link_b = f"{WEBAPP_URL}?match_id={match_id}&role=B"

                builder_a = InlineKeyboardBuilder()
                builder_a.button(text="🎙 Debatga Kirish", web_app=WebAppInfo(url=link_a))
                
                builder_b = InlineKeyboardBuilder()
                builder_b.button(text="🎙 Debatga Kirish", web_app=WebAppInfo(url=link_b))

                await bot.send_message(creator_id, f"🎉 Raqib ({name}) komnataga kirdi! Debatni boshlang.", reply_markup=builder_a.as_markup())
                await bot.send_message(user_id, f"🎉 Komnataga kirdingiz! Creator: {room_info['creator_name']}. Debatni boshlang.", reply_markup=builder_b.as_markup())
            else:
                await message.answer("❌ Bunday kodli komnata topilmadi. Kodni tekshirib qayta urinib ko'ring.")
                
    except json.JSONDecodeError:
        # Eski versiyalar uchun fallback
        if raw_data == "start_search":
            await join_debate(message)
        else:
            print(f"LOG: Unknown or invalid WebApp data: {raw_data}")

# --- JOIN LOGIKASI ---
@dp.message(Command("join"))
async def join_debate(message: types.Message):
    user_id = message.from_user.id
    print(f"LOG: User {user_id} attempting to join queue. Current room: {waiting_room}")
    if user_id not in waiting_room:
        waiting_room.append(user_id)
        await message.answer(f"⏳ Navbatga qo'shildingiz: {len(waiting_room)}/2")
    else:
        await message.answer("Siz allaqachon navbatdasiz.")
    
    print(f"LOG: Waiting room updated: {waiting_room}")

    if len(waiting_room) >= 2:
        players = [waiting_room.pop(0), waiting_room.pop(0)]
        match_id = f"m_{players[0]}_{int(datetime.datetime.now().timestamp())}"
        
        # Team A (Player 0), Team B (Player 1)
        active_matches[match_id] = {
            "group_a": {players[0]: None},
            "group_b": {players[1]: None},
            "turn_index": 0,
            "status": "waiting",
            "transcript": []
        }
        print(f"LOG: Match created: {match_id}")

        link_a = f"{WEBAPP_URL}?match_id={match_id}&role=A"
        link_b = f"{WEBAPP_URL}?match_id={match_id}&role=B"

        builder_a = InlineKeyboardBuilder()
        builder_a.button(text="🎙 Jo'nli Debatga Kirish (Team A)", web_app=WebAppInfo(url=link_a))
        
        builder_b = InlineKeyboardBuilder()
        builder_b.button(text="🎙 Jo'nli Debatga Kirish (Team B)", web_app=WebAppInfo(url=link_b))

        await bot.send_message(players[0], "🎉 Raqib topildi! Pastdagi tugmani bosib jonli debatga kiring.", reply_markup=builder_a.as_markup())
        await bot.send_message(players[1], "🎉 Raqib topildi! Pastdagi tugmani bosib jonli debatga kiring.", reply_markup=builder_b.as_markup())

async def send_role_menu(user_id, match_id):
    builder = InlineKeyboardBuilder()
    for r in ROLES:
        builder.button(text=r, callback_data=f"role_{r}_{match_id}")
    builder.adjust(2)
    await bot.send_message(user_id, "Guruhdagi rolingizni tanlang:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("role_"))
async def process_role(callback: types.CallbackQuery):
    _, role, match_id = callback.data.split("_")
    m = active_matches.get(match_id)
    if not m: return

    uid = callback.from_user.id
    team = "group_a" if uid in m["group_a"] else "group_b"
    
    m[team][uid] = role
    await callback.message.edit_text(f"✅ Siz: {role}. Raqib kutilmoqda...")

    all_selected = all(v is not None for v in m["group_a"].values()) and \
                   all(v is not None for v in m["group_b"].values())
    if all_selected:
        await start_turns(match_id)

async def start_turns(match_id):
    active_matches[match_id]["status"] = "debating"
    await broadcast(match_id, "🎤 Debat boshlandi! Ovozli xabar yuboring.")
    await next_speaker(match_id)

async def next_speaker(match_id):
    m = active_matches[match_id]
    if m["turn_index"] >= len(TURN_ORDER):
        await finish_debate(match_id)
        return

    team_key, role_idx = TURN_ORDER[m["turn_index"]]
    role_name = ROLES[role_idx]
    team_dict = m["group_a"] if team_key == "A" else m["group_b"]
    speaker_id = list(team_dict.keys())[0]
    
    m["current_speaker"] = speaker_id
    builder = InlineKeyboardBuilder()
    builder.button(text="End ✅", callback_data=f"end_{match_id}")

    await broadcast(match_id, f"🔔 Navbat: Team {team_key}, {role_name}")
    await bot.send_message(speaker_id, "Sizning navbatingiz! Gapiring va End bosing.", reply_markup=builder.as_markup())

# --- OVOZNI QABUL QILISH ---
# Note: Real-time audio is handled via PeerJS in the WebApp.
# The following handlers are kept for reference or future transcript features.
@dp.message(F.voice)
async def handle_voice(message: types.Message):
    await message.answer("ℹ️ Jonli debatda ovozli xabarlar shart emas. Ilovada gapiring!")

@dp.callback_query(F.data.startswith("end_"))
async def end_turn(callback: types.CallbackQuery):
    await callback.answer("Debat ilova ichida yakunlanadi.")

# --- AI YAKUN ---
async def finish_debate(match_id):
    m = active_matches[match_id]
    await broadcast(match_id, "🏁 AI hakamlik qilmoqda...")

    full_text = "\n".join([f"{i['name']}: {i['text']}" for i in m["transcript"]])
    prompt = (f"Debat nutqlari:\n{full_text}\n\nG'olibni va eng yaxshi speakerni aniqla. "
              f"Faqat 'Winner: [Team], Best: [Name]' formatida javob ber.")

    try:
        response = model.generate_content(prompt)
        result = response.text
        await broadcast(match_id, f"🏆 **NATIJA:**\n\n{result}")
        
        # G'olibni profilga saqlash (Sodda tahlil)
        for speaker in m["transcript"]:
            if speaker["name"] in result:
                now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                user_profiles[speaker["id"]]["awards"].append(f"🏅 Best Speaker - {now}")
    except:
        await broadcast(match_id, "❌ AI xatosi.")
    
    del active_matches[match_id]

async def broadcast(match_id, text):
    m = active_matches[match_id]
    users = list(m["group_a"].keys()) + list(m["group_b"].keys())
    for u in users:
        try: await bot.send_message(u, text)
        except: pass

async def main():
    await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Debat App", web_app=WebAppInfo(url=WEBAPP_URL)))
    print("Bot ishga tushdi...")
    #await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
    
    
    
from fastapi import FastAPI, Request
import uvicorn

# FastAPI ilovasini yaratamiz
app = FastAPI()

@app.post("/webhook")
async def telegram_webhook(request: Request):
    # Telegramdan kelgan JSON xabarni qabul qilamiz
    update_data = await request.json()
    update = types.Update.model_validate(update_data, context={"bot": bot})
    # Dispatcher (dp) ga xabarni uzatamiz
    await dp.feed_update(bot, update)
    return {"ok": True}

# Serverni ishga tushirish (Render talabi)
if __name__ == "__main__":
    # Render avtomatik ravishda PORT muhit o'zgaruvchisini beradi
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
