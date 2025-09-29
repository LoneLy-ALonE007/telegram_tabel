from telegram import Update, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
import datetime
import json
import os
from datetime import datetime, timedelta
from collections import defaultdict
from calendar import monthrange
from math import radians, cos, sin, asin, sqrt
import openpyxl
from datetime import date
import pytz

# 📍 Ishxona koordinatalari (latitude, longitude)
WORK_LOCATION = (41.351179, 69.292921)  # Masalan: Toshkent markazi
MAX_DISTANCE_METERS = 100  # Lokatsiya aniqligi (necha metr radiusda ishlaydi)
CLEANUP_DAYS = 365
DEFAULT_ADMINS = [6008741577]
USERS_FILE = "users.json"
ATTENDANCE_FILE = "attendance.json"
TASHKENT_TZ = pytz.timezone("Asia/Tashkent")
now = datetime.now(TASHKENT_TZ)
timestamp = now.isoformat()

ADMIN_PANEL = ReplyKeyboardMarkup(
    [
        ["👥 Foydalanuvchilar", "📊 Statistika"],
    ],
    resize_keyboard=True
)
# JSON yuklash
def load_json(filename):
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}



def is_admin(user_id: int, users: dict) -> bool:
    if str(user_id) in users and users[str(user_id)].get("is_admin", False):
        return True
    if user_id in DEFAULT_ADMINS or str(user_id) in [str(x) for x in DEFAULT_ADMINS]:
        return True
    return False

# JSON saqlash
def save_json(file, data):
    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
# 🎯 Baza bilan ishlash

async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    user_id = str(update.effective_user.id)

    if not users.get(user_id, {}).get("is_admin", False):
        await update.message.reply_text("❌ Siz admin emassiz.")
        return

    msg = "👥 Foydalanuvchilar ro‘yxati:\n\n"
    for uid, info in users.items():
        role = "⭐ Admin" if info.get("is_admin") else ""
        msg += f"🆔 {uid}\n👤 {info['full_name']} {role}\n\n"

    await update.message.reply_text(msg)


# 🛠 Lokatsiya masofasini tekshiruvchi funksiya (Haversine)

def is_within_radius(lat1, lon1, lat2, lon2, radius_m=100):
    # km ga o‘tkazib hisoblaydi
    R = 6371000  # Yer radiusi metrlarda
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    distance = R * c
    return distance <= radius_m

# 🧑 Start komandasi
def load_users():
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            users = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        users = {}

    for admin_id in DEFAULT_ADMINS:
        if str(admin_id) not in users:
            users[str(admin_id)] = {
                "full_name": "Super Admin",
                "is_admin": True
            }
    return users

# 📂 JSON saqlash
def save_users(users):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=4)

# 🚀 Start komandasi → Faqat registratsiya uchun
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    user_id = str(update.effective_user.id)

    if user_id in users:
        full_name = users[user_id]["full_name"]
        if users[user_id].get("is_admin", False):
            await update.message.reply_text(
                f"✅ Xush kelibsiz, Admin {full_name}!",
                reply_markup=ADMIN_PANEL
            )
        else:
            await update.message.reply_text(
                f"✅ Xush kelibsiz, {full_name}!\nSiz allaqachon registratsiyadan o‘tgansiz."
            )
    else:
        await update.message.reply_text("👋 Salom! Iltimos, ism va familiyangizni yozing:")
        context.user_data["waiting_for_name"] = True

# 👤 Ism Familiyani qabul qilish
async def handle_name_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("waiting_for_name"):
        full_name = update.message.text.strip()

        if len(full_name.split()) < 2:
            await update.message.reply_text("⚠️ Iltimos, ism va familiya to‘liq yozing (masalan: Ali Valiyev).")
            return

        user_id = str(update.effective_user.id)
        users = load_users()

        users[user_id] = {
            "full_name": full_name,
            "username": update.effective_user.username or ""
        }
        save_users(users)

        context.user_data["waiting_for_name"] = False

        # ✅ Lokatsiya tugmasini chiqaramiz
        buttons = [[KeyboardButton("📍 Lokatsiya yuborish", request_location=True)]]
        await update.message.reply_text(
            f"✅ Registratsiya tugadi!\n👤 Sizning ismingiz: {full_name}\n\n"
            "Endi ish jarayonini boshlash uchun lokatsiya yuboring.",
            reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True)
        )

def get_today_buttons(context):
    today = date.today().isoformat()

    if context.user_data.get("last_date") != today:
        context.user_data["today_status"] = None
        context.user_data["last_date"] = today
        context.user_data["location_valid"] = False
        context.user_data["last_kettim_time"] = None

    status = context.user_data.get("today_status")
    location_ok = context.user_data.get("location_valid", False)

    # 🔹 Agar lokatsiya yo‘q – faqat lokatsiya tugmasi
    if not location_ok:
        return [[KeyboardButton("📍 Lokatsiya yuborish", request_location=True)]]

    # 🔹 Oxirgi "Kettim" vaqtini tekshiramiz
    last_kettim_time = context.user_data.get("last_kettim_time")
    if last_kettim_time:
        delta = datetime.now() - last_kettim_time
        if delta.total_seconds() < 10:  # ⏱ test uchun 10 sekund
            return [["⏳ Keyingi kelish uchun kuting"]]

    # 🔹 Hali kelmagan bo‘lsa → faqat Keldim
    if status is None:
        return [["✅ Keldim"]]

    # 🔹 Kelgan bo‘lsa → faqat Kettim
    if status == "keldi":
        return [["❌ Kettim"]]

    # 🔹 Ketgan bo‘lsa → yana lokatsiya tugmasi chiqadi
    if status == "kettim":
        return [[KeyboardButton("📍 Lokatsiya yuborish", request_location=True)]]

    return []

async def handle_location(update, context):
    location = update.message.location
    if is_within_radius(location.latitude, location.longitude, *WORK_LOCATION, MAX_DISTANCE_METERS):
        context.user_data["location_valid"] = True
        context.user_data["last_location"] = (location.latitude, location.longitude)

        # ✅ Lokatsiya tasdiqlanganda faqat Keldim tugmasi chiqadi
        buttons = [["✅ Keldim"]]
        await update.message.reply_text(
            "✅ Lokatsiya tasdiqlandi. Endi ishni boshlash uchun Keldim tugmasini bosing.",
            reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True)
        )
    else:
        context.user_data["location_valid"] = False
        await update.message.reply_text("❌ Siz ishxona hududida emassiz.")

# 📍 Lokatsiya kelganda ishlovchi funksiya


# ✅ Keldim tugmasi
MAX_LOCATION_AGE_SECONDS = 120  # 2 daqiqa

async def handle_keldim(update, context):
    if not context.user_data.get("location_valid", False):
        await update.message.reply_text("📍 Avval lokatsiyani yuboring.")
        return

    if context.user_data.get("today_status") == "keldi":
        await update.message.reply_text("⚠️ Bugun allaqachon kelganingiz qayd etilgan.")
        return

    log_attendance_json(update.effective_user.id, "Keldi", context.user_data.get("last_location"))
    context.user_data["today_status"] = "keldi"

    await update.message.reply_text(
        "✅ Bugun kelganingiz qayd etildi.",
        reply_markup=ReplyKeyboardMarkup(get_today_buttons(context), resize_keyboard=True)
    )


# ❌ Kettim tugmasi
# Kettim tugmasi
async def handle_kettim(update, context):
    if context.user_data.get("today_status") != "keldi":
        await update.message.reply_text("⚠️ Avval Keldim tugmasini bosing.")
        return

    log_attendance_json(update.effective_user.id, "Ketti", context.user_data.get("last_location"))
    context.user_data["today_status"] = "kettim"
    context.user_data["next_allowed_time"] = datetime.now() + timedelta(seconds=10)  # 10 soniya kutish

    # ⏱ Kutib turing tugmasini chiqaramiz
    buttons = [["⏱ Kutib turing"]]
    await update.message.reply_text(
        "⏱ Bugun ketganingiz qayd etildi. Endi kutib turing.",
        reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    )

    # 🔔 10 soniyadan keyin tugmalarni qayta yoqamiz
    context.job_queue.run_once(reenable_buttons, 10, data=update.effective_chat.id, name=str(update.effective_chat.id))

async def reenable_buttons(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.data
    # foydalanuvchi statusini reset qilamiz
    context.application.user_data[chat_id]["today_status"] = None
    context.application.user_data[chat_id]["location_valid"] = False

    # foydalanuvchiga xabar va tugma chiqaramiz
    buttons = [[KeyboardButton("📍 Lokatsiya yuborish", request_location=True)]]
    await context.bot.send_message(
        chat_id=chat_id,
        text="🔄 Yangi davr boshlandi! Lokatsiya yuboring.",
        reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    )


def log_attendance_json(user_id, action, location):
    data = load_json(ATTENDANCE_FILE)
    entry = {
        "action": action,
        "timestamp": datetime.now(ZoneInfo("Asia/Tashkent")).isoformat(),
        "latitude": location[0],
        "longitude": location[1]
    }
    user_id = str(user_id)
    if user_id not in data:
        data[user_id] = []
    data[user_id].append(entry)
    save_json(ATTENDANCE_FILE, data)

def cleanup_old_attendance():
    try:
        with open(ATTENDANCE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)  # expected dict: { user_id: [entries] }
    except FileNotFoundError:
        data = {}

    cutoff_dt = datetime.now() - timedelta(days=CLEANUP_DAYS)

    cleaned = {}
    removed_count = 0
    for uid, records in data.items():
        kept = []
        for rec in records:
            try:
                rec_dt = datetime.fromisoformat(rec["timestamp"])
            except Exception:
                # agar format noto'g'ri bo'lsa, o'tkazib yuborish
                continue
            if rec_dt >= cutoff_dt:
                kept.append(rec)
            else:
                removed_count += 1
        if kept:
            cleaned[uid] = kept

    with open(ATTENDANCE_FILE, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, indent=4, ensure_ascii=False)

    print(f"🧹 {removed_count} ta eski attendance yozuvi o'chirildi.")


# 📊 Oylik statistika
async def ask_month(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    user_id = update.effective_user.id

    if not is_admin(user_id, users):
        await update.message.reply_text("❌ Siz admin emassiz.")
        return

    context.user_data["awaiting_month"] = True
    await update.message.reply_text("📅 Qaysi oy uchun statistika kerak? Format: YYYY-MM (masalan: 2025-09)")

# 📁 Excel faylga yozish
def export_monthly_excel(month_str, users, attendance_data, year, month):
    # Yengil Excel eksport: har bir foydalanuvchi uchun name + kelgan kunlar ro'yxati
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = month_str

    ws.append(["Foydalanuvchi", "Sana", "Harakat", "Vaqt", "Latitude", "Longitude"])

    # start/end
    start_date = datetime(year, month, 1)
    end_day = monthrange(year, month)[1]
    end_date = datetime(year, month, end_day, 23, 59, 59)

    for uid, records in attendance_data.items():
        name = users.get(uid, {}).get("full_name", f"ID: {uid}")
        for r in records:
            try:
                ts = datetime.fromisoformat(r["timestamp"])
            except Exception:
                continue
            if not (start_date <= ts <= end_date):
                continue
            row = [
                name,
                ts.date().isoformat(),
                r.get("action", ""),
                ts.time().isoformat(timespec='seconds'),
                r.get("latitude", ""),
                r.get("longitude", "")
            ]
            ws.append(row)

    filename = f"attendance_{month_str}.xlsx"
    wb.save(filename)
    return filename

async def monthly_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_month"):
        return

    month_str = update.message.text.strip()
    try:
        year, month = map(int, month_str.split("-"))
    except:
        await update.message.reply_text("⚠️ Format noto‘g‘ri. Masalan: 2025-08")
        return

    users = load_json(USERS_FILE)
    attendance_data = load_json(ATTENDANCE_FILE)

    # Sana oralig'i
    start_date = datetime(year, month, 1)
    end_day = monthrange(year, month)[1]
    end_date = datetime(year, month, end_day, 23, 59, 59)

    msg = f"📊 *{month_str} oy statistikasi:*\n\n"

    # Ish kunlarini hisoblash uchun date obyektlari bilan ishlaymiz
    from datetime import date as date_cls
    total_days = [date_cls(year, month, d) for d in range(1, end_day+1)]
    sundays = [d for d in total_days if d.weekday() == 6]
    work_days = [d for d in total_days if d.weekday() != 6]

    for uid, records in attendance_data.items():
        name = users.get(uid, {}).get("full_name", f"ID: {uid}")

        # Filter records for this month and collect by date()
        days = defaultdict(lambda: {"Keldi": False})
        for r in records:
            try:
                ts = datetime.fromisoformat(r["timestamp"])
            except Exception:
                continue
            if not (start_date <= ts <= end_date):
                continue
            day = ts.date()
            if r.get("action") == "Keldi":
                days[day]["Keldi"] = True

        present_days = sum(1 for d in work_days if days[d]["Keldi"])
        msg += f"👤 {name}\n🗓 Umumiy ish kunlari: {len(work_days)}\n🛌 Dam olish kunlari: {len(sundays)}\n✅ Kelgan kunlar: {present_days}\n\n"

    await update.message.reply_text(msg, parse_mode="Markdown")

    # Excel yaratish va yuborish
    filename = export_monthly_excel(month_str, users, attendance_data, year, month)
    await update.message.reply_document(document=open(filename, "rb"))
    os.remove(filename)

    context.user_data["awaiting_month"] = False

# 🔄 Botni ishga tushirish
if __name__ == "__main__":
    app = ApplicationBuilder().token("8365590227:AAHwb0ugWQyLkQiO7sUr6XiYo5C6TGc6Qhw").build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.LOCATION, handle_location))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("Keldim"), handle_keldim))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("Kettim"), handle_kettim))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("📊 Statistika"), ask_month))
    app.add_handler(MessageHandler(filters.Regex("^👥 Foydalanuvchilar$"), list_users))
    app.add_handler(MessageHandler(filters.Regex(r"^\d{4}-\d{2}$"), monthly_statistics), group=2)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_name_input), group=1)
    print("✅ Bot ishga tushdi")
    app.run_polling()







