import sqlite3
import time
import random
import threading
import requests

# ================= تنظیمات اصلی بات =================
TOKEN = "178609715:ILF2qscrUoYUfzBoMDI378xxyiZjKvwSmuU"
BASE_URL = f"https://tapi.bale.ai/bot{TOKEN}/"

# اگر میخوای بات فقط تو گپ TTF کار کنه، آیدی عددی گپ رو بذار اینجا (None یعنی همه جا کار کنه)
ALLOWED_CHAT_ID = None  # مثال: -100123456789

# تایمرها (به ثانیه)
ANGOSHT_COOLDOWN = 90          # ۱ دقیقه و ۳۰ ثانیه
BANK_PROFIT_COOLDOWN = 86400   # ۲۴ ساعت
DAILY_COOLDOWN = 86400         # ۲۴ ساعت
ROB_COOLDOWN = 600             # ۱۰ دقیقه
DOOZ_TURN_TIMEOUT = 60         # ۶۰ ثانیه مهلت هر نوبت دوز
HAMSTER_HUNGER_LIMIT = 3600    # ۱ ساعت گرسنه بمونه لولش میفته

# تنظیمات مزرعه هویج: (مدت زمان رشد به ثانیه، هزینه کاشت، تعداد برداشت، امتیاز غذا برای همستر)
CARROT_CONFIG = {
    "معمولی": {"cooldown": 180, "cost": 0, "yield": 2, "feed_xp": 1},     # ۳ دقیقه
    "طلایی": {"cooldown": 600, "cost": 10, "yield": 1, "feed_xp": 3},     # ۱۰ دقیقه
    "الماسی": {"cooldown": 1800, "cost": 30, "yield": 1, "feed_xp": 10},  # ۳۰ دقیقه
}

# درآمد همستر در دقیقه بر اساس لول
HAMSTER_INCOME = {1: 5, 2: 69, 3: 439}

# سوالات بازی گنج (۳ مرحله‌ای)
TREASURE_STAGES = {
    1: [
        {"q": "اون چیه که هرچی ازش برمی‌داری بزرگ‌تر میشه؟", "a": "چاله"},
        {"q": "فلزی که هم گرونه هم زرده؟", "a": "طلا"},
        {"q": "غذای محبوب همستر تو مزرعه ما چیه؟", "a": "هویج"},
    ],
    2: [
        {"q": "پایتخت ایران کجاست؟", "a": "تهران"},
        {"q": "اون چیه که پا نداره ولی راه میره، صدا هم میده؟", "a": "ساعت"},
        {"q": "اسم گپ خفن ما چیه؟ (به انگلیسی و حروف کوچک یا بزرگ)", "a": "ttf"},
    ],
    3: [
        {"q": "کدام حیوان نماد این باته؟", "a": "همستر"},
        {"q": "برعکس کلمه «گنج» چی میشه؟", "a": "جنگ"},
        {"q": "با کدوم کامند هر ۱:۳۰ دقیقه ۱ کوین میگیری؟", "a": "انگشت"},
    ]
}

# ================= دیتابیس (SQLite) =================
db_lock = threading.Lock()
conn = sqlite3.connect("hamester_ttf.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    coins INTEGER DEFAULT 0,
    bank_coins INTEGER DEFAULT 0,
    last_angosht REAL DEFAULT 0,
    last_bank_profit REAL DEFAULT 0,
    last_daily REAL DEFAULT 0,
    last_rob REAL DEFAULT 0,
    carrot_normal INTEGER DEFAULT 0,
    carrot_gold INTEGER DEFAULT 0,
    carrot_diamond INTEGER DEFAULT 0,
    farm_type TEXT DEFAULT NULL,
    farm_time REAL DEFAULT 0,
    hamster_name TEXT DEFAULT 'همستر بی‌نام',
    hamster_level INTEGER DEFAULT 0,
    hamster_xp INTEGER DEFAULT 0,
    hamster_last_fed REAL DEFAULT 0,
    hamster_last_claim REAL DEFAULT 0,
    treasure_stage INTEGER DEFAULT 0,
    treasure_q_idx INTEGER DEFAULT -1
)
""")
conn.commit()

# ================= وضعیت بازی دوز =================
active_dooz = None  # فقط یک بازی همزمان مجازه
dooz_lock = threading.Lock()

# ================= توابع کمکی =================
def fa_to_en(text):
    """تبدیل اعداد فارسی به انگلیسی"""
    fa_digits = "۰۱۲۳۴۵۶۷۸۹"
    en_digits = "0123456789"
    for f, e in zip(fa_digits, en_digits):
        text = text.replace(f, e)
    return text

def send_message(chat_id, text, reply_to=None, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_to:
        payload["reply_to_message_id"] = reply_to
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        return requests.post(BASE_URL + "sendMessage", json=payload, timeout=10).json()
    except Exception as e:
        print(f"Error send_message: {e}")
        return None

def edit_message(chat_id, message_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        requests.post(BASE_URL + "editMessageText", json=payload, timeout=10)
    except Exception as e:
        print(f"Error edit_message: {e}")

def answer_callback(callback_id, text=""):
    payload = {"callback_query_id": callback_id, "text": text}
    try:
        requests.post(BASE_URL + "answerCallbackQuery", json=payload, timeout=5)
    except:
        pass

def get_or_create_user(user_id, username, first_name):
    username = username.lower() if username else ""
    with db_lock:
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            cursor.execute(
                "INSERT INTO users (user_id, username, first_name) VALUES (?, ?, ?)",
                (user_id, username, first_name)
            )
            conn.commit()
            cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
        else:
            cursor.execute(
                "UPDATE users SET username = ?, first_name = ? WHERE user_id = ?",
                (username, first_name, user_id)
            )
            conn.commit()
        return row

def get_user_dict(user_id):
    with db_lock:
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            return None
        cols = [col[0] for col in cursor.description]
        return dict(zip(cols, row))

def find_user_by_username(username):
    username = username.lstrip("@").lower()
    with db_lock:
        cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        if not row:
            return None
        cols = [col[0] for col in cursor.description]
        return dict(zip(cols, row))

def calculate_player_level(total_coins):
    """محاسبه لول پلیر طبق راهنمای لول‌آپ"""
    if total_coins >= 50:
        return 5
    elif total_coins >= 35:
        return 4
    elif total_coins >= 16:
        return 3
    elif total_coins >= 5:
        return 2
    else:
        return 1

def sync_hamster(user_id):
    """محاسبه درآمد همستر و چک کردن گرسنگی"""
    u = get_user_dict(user_id)
    if not u or u["hamster_level"] == 0:
        return 0, None

    now = time.time()
    h_lvl = u["hamster_level"]
    last_fed = u["hamster_last_fed"]
    last_claim = u["hamster_last_claim"]
    msg = None

    # بررسی گرسنگی
    if now - last_fed > HAMSTER_HUNGER_LIMIT:
        # تا زمانی که گرسنه بوده تا مرز ۱ ساعت درآمد میده، بعدش لول کم میشه
        effective_end = last_fed + HAMSTER_HUNGER_LIMIT
        minutes = max(0, int((effective_end - last_claim) // 60))
        earned = minutes * HAMSTER_INCOME.get(h_lvl, 5)

        new_lvl = max(1, h_lvl - 1)
        with db_lock:
            cursor.execute("""
                UPDATE users 
                SET coins = coins + ?, hamster_level = ?, hamster_last_fed = ?, hamster_last_claim = ?, hamster_xp = 0
                WHERE user_id = ?
            """, (earned, new_lvl, now, now, user_id))
            conn.commit()
        if new_lvl < h_lvl:
            msg = f"⚠️ همسترت از گشنگی تلف شد و لولش افتاد روی {new_lvl}! زود بهش هویج بده!"
        else:
            msg = "⚠️ همسترت شدیداً گشنه‌ست! بهش هویج بده تا کوین جمع کنه."
        return earned, msg
    else:
        minutes = int((now - last_claim) // 60)
        if minutes > 0:
            earned = minutes * HAMSTER_INCOME.get(h_lvl, 5)
            new_claim_time = last_claim + (minutes * 60)
            with db_lock:
                cursor.execute("""
                    UPDATE users SET coins = coins + ?, hamster_last_claim = ? WHERE user_id = ?
                """, (earned, new_claim_time, user_id))
                conn.commit()
            return earned, None
        return 0, None

# ================= سیستم دوز =================
def get_dooz_keyboard(board):
    symbols = {" ": "⬜", "X": "❌", "O": "⭕"}
    inline_kb = []
    for row in range(3):
        btn_row = []
        for col in range(3):
            idx = row * 3 + col
            btn_row.append({
                "text": symbols[board[idx]],
                "callback_data": f"dooz_move_{idx}"
            })
        inline_kb.append(btn_row)
    return {"inline_keyboard": inline_kb}

def check_dooz_winner(b):
    wins = [(0,1,2), (3,4,5), (6,7,8), (0,3,6), (1,4,7), (2,5,8), (0,4,8), (2,4,6)]
    for x, y, z in wins:
        if b[x] != " " and b[x] == b[y] == b[z]:
            return b[x]
    if " " not in b:
        return "DRAW"
    return None

def dooz_timeout_watcher():
    """چک کردن تایم‌اوت نوبت دوز و جریمه ۲ برابر ورودی"""
    global active_dooz
    while True:
        time.sleep(3)
        with dooz_lock:
            if not active_dooz or active_dooz["status"] != "playing":
                continue
            now = time.time()
            if now - active_dooz["turn_time"] > DOOZ_TURN_TIMEOUT:
                loser_id = active_dooz["turn_user"]
                winner_id = active_dooz["p1"] if loser_id == active_dooz["p2"] else active_dooz["p2"]
                loser_name = active_dooz["p1_name"] if loser_id == active_dooz["p1"] else active_dooz["p2_name"]
                winner_name = active_dooz["p2_name"] if loser_id == active_dooz["p1"] else active_dooz["p1_name"]
                
                entry = active_dooz["entry"]
                penalty = entry * 2  # دو برابر ورودی کم میشه

                with db_lock:
                    cursor.execute("UPDATE users SET coins = MAX(0, coins - ?) WHERE user_id = ?", (penalty, loser_id))
                    cursor.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (penalty, winner_id))
                    conn.commit()

                send_message(
                    active_dooz["chat_id"],
                    f"⏰ وقت تموم شد!\n"
                    f"کاربر {loser_name} نوبتشو نزد!\n"
                    f"طبق قانون، ۲ برابر ورودی یعنی **{penalty} کوین** ازش کم شد و رفت تو جیب {winner_name}! 💸"
                )
                active_dooz = None

threading.Thread(target=dooz_timeout_watcher, daemon=True).start()

# ================= پردازش پیام‌ها و کامندها =================
def handle_message(msg):
    global active_dooz
    chat_id = msg["chat"]["id"]
    if ALLOWED_CHAT_ID and chat_id != ALLOWED_CHAT_ID:
        return

    if "text" not in msg or "from" not in msg:
        return

    user_id = msg["from"]["id"]
    username = msg["from"].get("username", "")
    first_name = msg["from"].get("first_name", "کاربر")
    msg_id = msg["message_id"]
    text = fa_to_en(msg["text"].strip())

    get_or_create_user(user_id, username, first_name)
    sync_hamster(user_id)
    u = get_user_dict(user_id)
    total_wealth = u["coins"] + u["bank_coins"]
    p_level = calculate_player_level(total_wealth)

    # ۱. کامند راهنمایی
    if text in ["راهنمایی", "راهنما", "کمک"]:
        help_text = (
            "🐹 **راهنمای کامل همستر بات (اختصاصی گپ TTF)** 🐹\n"
            "━━━━━━━━━━━━━━━\n"
            "📌 **کامندهای اصلی (بدون نیاز به /):**\n\n"
            "👈 `انگشت`\n"
            "هر ۱:۳۰ دقیقه ۱ کوین میگیری.\n\n"
            "👈 `پروفایل` | `موجودی`\n"
            "نمایش لول، کوین‌ها، هویج‌ها و وضعیت همستر.\n\n"
            "👈 `لیدربرد`\n"
            "لیست ۱۰ نفر اول و پولدارترین‌های گپ TTF.\n\n"
            "👈 `روزانه`\n"
            "دریافت جایزه روزانه (هرچی لولت بالاتر باشه جایزه بیشتره).\n\n"
            "🚜 **بخش مزرعه:**\n"
            "• `مزرعه` : وضعیت مزرعه و انبار هویج\n"
            "• `کاشت معمولی` : رایگان (رشد: ۳ دقیقه)\n"
            "• `کاشت طلایی` : ۱۰ کوین (رشد: ۱۰ دقیقه)\n"
            "• `کاشت الماسی` : ۳۰ کوین (رشد: ۳۰ دقیقه)\n"
            "• `برداشت` : درو کردن هویج کاشته شده\n\n"
            "🏦 **بخش بانک:**\n"
            "• `بانک` : موجودی بانک\n"
            "• `واریز [عدد]` : گذاشتن کوین تو بانک\n"
            "• `برداشت بانک [عدد]` : کشیدن کوین از بانک\n"
            "• `سود بانک` : دریافت سود رندوم روزانه\n\n"
            "🐹 **بخش همستر (مخصوص لول ۳ به بالا):**\n"
            "• `ساخت همستر` : تولید همستر پول‌ساز\n"
            "• `همستر` : وضعیت همستر و جمع‌آوری درآمد\n"
            "• `اسم همستر [نام]` : تغییر اسم همستر\n"
            "• `غذا دادن [معمولی/طلایی/الماسی]` : سیر کردن و لول‌آپ همستر\n\n"
            "🎮 **بخش بازی و سرگرمی:**\n"
            "• `دوز [عدد شرط]` : شروع بازی دوز (ورودی نصف عدد شرطه)\n"
            "• `گنج` : بازی معمایی ۳ مرحله‌ای با جایزه نقدی\n"
            "• `جواب [پاسخ]` : جواب دادن به سوال گنج\n"
            "• `سرقت [@آیدی]` (یا ریپلای `سرقت`) : دزدی کوین از بقیه!\n"
            "• `پرداخت [@آیدی] [عدد]` : انتقال کوین به رفقا\n"
            "━━━━━━━━━━━━━━━\n"
            "📈 **راهنمای لول‌آپ پلیر:**\n"
            "• ۵ کوین ⬅️ لول ۲\n"
            "• ۱۶ کوین ⬅️ لول ۳ (باز شدن ساخت همستر)\n"
            "• ۳۵ کوین ⬅️ لول ۴\n"
            "• ۵۰ کوین ⬅️ لول ۵ (لول آخر)"
        )
        send_message(chat_id, help_text, reply_to=msg_id)
        return

    # ۲. کامند انگشت
    if text == "انگشت":
        now = time.time()
        elapsed = now - u["last_angosht"]
        if elapsed < ANGOSHT_COOLDOWN:
            rem = int(ANGOSHT_COOLDOWN - elapsed)
            m, s = divmod(rem, 60)
            send_message(chat_id, f"⏳ عجله نکن ستون! {m} دقیقه و {s} ثانیه دیگه می‌تونی انگشت کنی.", reply_to=msg_id)
            return

        with db_lock:
            cursor.execute("UPDATE users SET coins = coins + 1, last_angosht = ? WHERE user_id = ?", (now, user_id))
            conn.commit()

        send_message(chat_id, "آفرین همستر انگشت کردی .\nانگشت بعدیت ۱:۳۰ دقیقه بعد", reply_to=msg_id)
        return

    # ۳. کامند لیدربرد
    if text in ["لیدربرد", "برترین ها", "رتبه"]:
        with db_lock:
            cursor.execute("""
                SELECT first_name, coins, bank_coins, hamster_level 
                FROM users 
                ORDER BY (coins + bank_coins) DESC LIMIT 10
            """)
            rows = cursor.fetchall()

        lb_text = "🏆 **لیدربرد سلاطین گپ TTF** 🏆\n━━━━━━━━━━━━━━━\n"
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        for idx, r in enumerate(rows):
            fname, c, bc, hlvl = r
            tot = c + bc
            lvl = calculate_player_level(tot)
            h_tag = f" | 🐹 لول {hlvl}" if hlvl > 0 else ""
            lb_text += f"{medals[idx]} **{fname}** ⬅️ `{tot}` کوین (لول {lvl}{h_tag})\n"

        send_message(chat_id, lb_text, reply_to=msg_id)
        return

    # ۴. پروفایل و موجودی
    if text in ["پروفایل", "موجودی"]:
        h_status = "نداری (لول ۳ شو و بزن: ساخت همستر)" if u["hamster_level"] == 0 else f"{u['hamster_name']} (لول {u['hamster_level']})"
        prof_text = (
            f"👤 **پروفایل {first_name}**\n"
            f"━━━━━━━━━━━━━━━\n"
            f"⭐ لول پلیر: **{p_level}**\n"
            f"💰 کوین جیب: **{u['coins']}**\n"
            f"🏦 کوین بانک: **{u['bank_coins']}**\n"
            f"🐹 همستر: **{h_status}**\n"
            f"🥕 هویج‌ها: معمولی ({u['carrot_normal']}) | طلایی ({u['carrot_gold']}) | الماسی ({u['carrot_diamond']})"
        )
        send_message(chat_id, prof_text, reply_to=msg_id)
        return

    # ۵. جایزه روزانه (بر اساس لول)
    if text == "روزانه":
        now = time.time()
        if now - u["last_daily"] < DAILY_COOLDOWN:
            rem = int(DAILY_COOLDOWN - (now - u["last_daily"]))
            h, rem = divmod(rem, 3600)
            m, _ = divmod(rem, 60)
            send_message(chat_id, f"⏳ جایزه روزانه‌تو گرفتی! {h} ساعت و {m} دقیقه دیگه بیا.", reply_to=msg_id)
            return

        daily_rewards = {1: 5, 2: 12, 3: 25, 4: 50, 5: 100}
        reward = daily_rewards.get(p_level, 5)
        with db_lock:
            cursor.execute("UPDATE users SET coins = coins + ?, last_daily = ? WHERE user_id = ?", (reward, now, user_id))
            conn.commit()
        send_message(chat_id, f"🎁 به خاطر اینکه **لول {p_level}** هستی، جایزه روزانه‌ت **{reward} کوین** به حسابت نشست!", reply_to=msg_id)
        return

    # ۶. بخش مزرعه
    if text == "مزرعه":
        farm_info = "خالی (آماده کاشت)"
        if u["farm_type"]:
            cfg = CARROT_CONFIG[u["farm_type"]]
            rem = int(cfg["cooldown"] - (time.time() - u["farm_time"]))
            if rem <= 0:
                farm_info = f"✅ هویج **{u['farm_type']}** رسیده! بزن `برداشت`"
            else:
                m, s = divmod(rem, 60)
                farm_info = f"🌱 هویج **{u['farm_type']}** در حال رشد ({m} دقیقه و {s} ثانیه مونده)"

        msg_farm = (
            f"🚜 **مزرعه اختصاصی {first_name}**\n"
            f"━━━━━━━━━━━━━━━\n"
            f"وضعیت زمین: {farm_info}\n\n"
            f"📦 **انبار هویج‌های تو:**\n"
            f"🥕 معمولی: `{u['carrot_normal']}`\n"
            f"🥕 طلایی: `{u['carrot_gold']}`\n"
            f"💎 الماسی: `{u['carrot_diamond']}`\n\n"
            f"برای کاشت بنویس:\n"
            f"`کاشت معمولی` (رایگان - ۳ دقیقه)\n"
            f"`کاشت طلایی` (۱۰ کوین - ۱۰ دقیقه)\n"
            f"`کاشت الماسی` (۳۰ کوین - ۳۰ دقیقه)"
        )
        send_message(chat_id, msg_farm, reply_to=msg_id)
        return

    if text.startswith("کاشت "):
        c_type = text.replace("کاشت ", "").strip()
        if c_type not in CARROT_CONFIG:
            send_message(chat_id, "❌ نوع هویج نامعتبره! بنویس: `کاشت معمولی`، `کاشت طلایی` یا `کاشت الماسی`", reply_to=msg_id)
            return
        if u["farm_type"] is not None:
            send_message(chat_id, "⚠️ زمینت پره! اول قبلی رو `برداشت` کن.", reply_to=msg_id)
            return

        cfg = CARROT_CONFIG[c_type]
        if u["coins"] < cfg["cost"]:
            send_message(chat_id, f"❌ کوینت کمه! برای کاشت هویج {c_type} به {cfg['cost']} کوین نیاز داری.", reply_to=msg_id)
            return

        with db_lock:
            cursor.execute("""
                UPDATE users SET coins = coins - ?, farm_type = ?, farm_time = ? WHERE user_id = ?
            """, (cfg["cost"], c_type, time.time(), user_id))
            conn.commit()

        send_message(chat_id, f"🌱 بذر هویج **{c_type}** کاشته شد! {cfg['cooldown']//60} دقیقه دیگه بیا بزن `برداشت`.", reply_to=msg_id)
        return

    if text == "برداشت":
        if not u["farm_type"]:
            send_message(chat_id, "❌ چیزی تو مزرعه نکاشتی که بخوای برداشت کنی!", reply_to=msg_id)
            return

        c_type = u["farm_type"]
        cfg = CARROT_CONFIG[c_type]
        elapsed = time.time() - u["farm_time"]
        if elapsed < cfg["cooldown"]:
            rem = int(cfg["cooldown"] - elapsed)
            m, s = divmod(rem, 60)
            send_message(chat_id, f"⏳ هنوز نرسیده! {m} دقیقه و {s} ثانیه دیگه صبر کن.", reply_to=msg_id)
            return

        col_map = {"معمولی": "carrot_normal", "طلایی": "carrot_gold", "الماسی": "carrot_diamond"}
        col = col_map[c_type]
        with db_lock:
            cursor.execute(f"""
                UPDATE users SET {col} = {col} + ?, farm_type = NULL, farm_time = 0 WHERE user_id = ?
            """, (cfg["yield"], user_id))
            conn.commit()

        send_message(chat_id, f"🎉 ایول! تعداد **{cfg['yield']} هویج {c_type}** برداشت کردی و رفت تو انبارت!", reply_to=msg_id)
        return

    # ۷. بخش بانک
    if text == "بانک":
        send_message(
            chat_id,
            f"🏦 **بانک مرکزی TTF**\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💰 موجودی بانک تو: **{u['bank_coins']} کوین**\n"
            f"👛 موجودی جیبت: **{u['coins']} کوین**\n\n"
            f"• `واریز [عدد]`\n"
            f"• `برداشت بانک [عدد]`\n"
            f"• `سود بانک` (دریافت سود رندوم روزانه)",
            reply_to=msg_id
        )
        return

    if text.startswith("واریز "):
        amt_str = text.replace("واریز ", "").strip()
        if not amt_str.isdigit() or int(amt_str) <= 0:
            send_message(chat_id, "❌ یه عدد درست وارد کن! مثال: `واریز 20`", reply_to=msg_id)
            return
        amt = int(amt_str)
        if u["coins"] < amt:
            send_message(chat_id, "❌ اینقدر کوین تو جیبت نداری!", reply_to=msg_id)
            return
        with db_lock:
            cursor.execute("UPDATE users SET coins = coins - ?, bank_coins = bank_coins + ? WHERE user_id = ?", (amt, amt, user_id))
            conn.commit()
        send_message(chat_id, f"✅ مقدار **{amt} کوین** با موفقیت رفت تو بانک!", reply_to=msg_id)
        return

    if text.startswith("برداشت بانک "):
        amt_str = text.replace("برداشت بانک ", "").strip()
        if not amt_str.isdigit() or int(amt_str) <= 0:
            send_message(chat_id, "❌ عدد درست بزن! مثال: `برداشت بانک 20`", reply_to=msg_id)
            return
        amt = int(amt_str)
        if u["bank_coins"] < amt:
            send_message(chat_id, "❌ اینقدر کوین تو بانکت نداری!", reply_to=msg_id)
            return
        with db_lock:
            cursor.execute("UPDATE users SET bank_coins = bank_coins - ?, coins = coins + ? WHERE user_id = ?", (amt, amt, user_id))
            conn.commit()
        send_message(chat_id, f"✅ مقدار **{amt} کوین** از بانک کشیدی بیرون و اومد تو جیبت!", reply_to=msg_id)
        return

    if text == "سود بانک":
        if u["bank_coins"] <= 0:
            send_message(chat_id, "❌ اول باید کوین بذاری تو بانک تا سود بگیری!", reply_to=msg_id)
            return
        now = time.time()
        if now - u["last_bank_profit"] < BANK_PROFIT_COOLDOWN:
            rem = int(BANK_PROFIT_COOLDOWN - (now - u["last_bank_profit"]))
            h, rem = divmod(rem, 3600)
            m, _ = divmod(rem, 60)
            send_message(chat_id, f"⏳ سود امروزتو گرفتی! {h} ساعت و {m} دقیقه دیگه بیا.", reply_to=msg_id)
            return

        percent = random.randint(5, 25)
        profit = max(1, (u["bank_coins"] * percent) // 100)
        with db_lock:
            cursor.execute("UPDATE users SET bank_coins = bank_coins + ?, last_bank_profit = ? WHERE user_id = ?", (profit, now, user_id))
            conn.commit()
        send_message(chat_id, f"📈 شانس باهات یار بود! امروز **{percent}%** سود بهت خورد و **{profit} کوین** رفت رو حساب بانکت!", reply_to=msg_id)
        return

    # ۸. بخش همستر (مخصوص لول ۳ به بالا)
    if text == "ساخت همستر":
        if p_level < 3:
            send_message(chat_id, f"❌ برای تولید همستر باید حداقل **لول ۳** باشی (۱۶ کوین داشته باشی). الان لول {p_level} هستی!", reply_to=msg_id)
            return
        if u["hamster_level"] > 0:
            send_message(chat_id, "🐹 تو که همستر داری ستون! بزن `همستر` تا وضعیتشو ببینی.", reply_to=msg_id)
            return
        now = time.time()
        with db_lock:
            cursor.execute("""
                UPDATE users SET hamster_level = 1, hamster_last_fed = ?, hamster_last_claim = ? WHERE user_id = ?
            """, (now, now, user_id))
            conn.commit()
        send_message(
            chat_id,
            "🎉 **مبارکه! همسترت متولد شد!** 🐹\n"
            "الان **لول ۱** هست و دقیقه‌ای **۵ کوین** برات استخراج می‌کنه.\n"
            "• برای تغییر اسمش بزن: `اسم همستر [نام]`\n"
            "• یادت نره با هویج‌های مزرعه بهش غذا بدی (`غذا دادن معمولی`) وگرنه گشنه میمونه و لولش میفته!",
            reply_to=msg_id
        )
        return

    if text == "همستر":
        if u["hamster_level"] == 0:
            send_message(chat_id, "❌ هنوز همستر نداری! وقتی رسیدی به **لول ۳**، بنویس `ساخت همستر`.", reply_to=msg_id)
            return
        earned, hunger_msg = sync_hamster(user_id)
        u = get_user_dict(user_id)
        hlvl = u["hamster_level"]
        inc = HAMSTER_INCOME[hlvl]
        rem_hunger = max(0, int(HAMSTER_HUNGER_LIMIT - (time.time() - u["hamster_last_fed"])))
        m_h, s_h = divmod(rem_hunger, 60)

        status_txt = (
            f"🐹 **وضعیت همستر: {u['hamster_name']}**\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🔼 لول همستر: **{hlvl}** (نهایت لول ۳)\n"
            f"⚡ درآمد فعلی: **دقیقه‌ای {inc} کوین**\n"
            f"🍖 تایمر گرسنگی: **{m_h} دقیقه و {s_h} ثانیه**\n"
            f"📊 امتیاز غذا برای لول بعد: `{u['hamster_xp']} / {hlvl * 5}`\n"
        )
        if earned > 0:
            status_txt += f"\n💰 همین الان **{earned} کوین** از درآمد همسترت رفت تو جیبت!"
        if hunger_msg:
            status_txt += f"\n\n{hunger_msg}"

        send_message(chat_id, status_txt, reply_to=msg_id)
        return

    if text.startswith("اسم همستر "):
        if u["hamster_level"] == 0:
            send_message(chat_id, "❌ اول همستر بساز بعد براش اسم بذار!", reply_to=msg_id)
            return
        new_name = text.replace("اسم همستر ", "").strip()[:25]
        with db_lock:
            cursor.execute("UPDATE users SET hamster_name = ? WHERE user_id = ?", (new_name, user_id))
            conn.commit()
        send_message(chat_id, f"✅ اسم همسترت عوض شد به: **{new_name}** 🐹", reply_to=msg_id)
        return

    if text.startswith("غذا دادن "):
        if u["hamster_level"] == 0:
            send_message(chat_id, "❌ تو هنوز همستر نداری!", reply_to=msg_id)
            return
        c_type = text.replace("غذا دادن ", "").strip()
        col_map = {"معمولی": "carrot_normal", "طلایی": "carrot_gold", "الماسی": "carrot_diamond"}
        if c_type not in col_map:
            send_message(chat_id, "❌ بنویس: `غذا دادن معمولی`، `غذا دادن طلایی` یا `غذا دادن الماسی`", reply_to=msg_id)
            return

        col = col_map[c_type]
        if u[col] <= 0:
            send_message(chat_id, f"❌ هویج **{c_type}** تو انبارت نداری! برو تو `مزرعه` بکار.", reply_to=msg_id)
            return

        xp_gain = CARROT_CONFIG[c_type]["feed_xp"]
        hlvl = u["hamster_level"]
        new_xp = u["hamster_xp"] + xp_gain
        needed_xp = hlvl * 5
        lvl_up_msg = ""

        if hlvl < 3 and new_xp >= needed_xp:
            hlvl += 1
            new_xp = 0
            lvl_up_msg = f"\n🔥 **ایول! همسترت لول‌آپ شد به لول {hlvl}!** الان دقیقه‌ای **{HAMSTER_INCOME[hlvl]} کوین** میده!"

        now = time.time()
        with db_lock:
            cursor.execute(f"""
                UPDATE users 
                SET {col} = {col} - 1, hamster_level = ?, hamster_xp = ?, hamster_last_fed = ?
                WHERE user_id = ?
            """, (hlvl, new_xp, now, user_id))
            conn.commit()

        send_message(chat_id, f"🥕 یه هویج **{c_type}** دادی به **{u['hamster_name']}** و سیر شد! (+{xp_gain} XP){lvl_up_msg}", reply_to=msg_id)
        return

    # ۹. بخش پرداخت (Pay)
    if text.startswith("پرداخت "):
        parts = text.split()
        # حالت ریپلای: پرداخت 100
        if "reply_to_message" in msg and len(parts) == 2 and parts[1].isdigit():
            amt = int(parts[1])
            target_msg = msg["reply_to_message"]["from"]
            target_id = target_msg["id"]
            target_name = target_msg.get("first_name", "کاربر")
            get_or_create_user(target_id, target_msg.get("username", ""), target_name)
        elif len(parts) >= 3 and parts[-1].isdigit():
            amt = int(parts[-1])
            target_username = parts[1]
            target_user = find_user_by_username(target_username)
            if not target_user:
                send_message(chat_id, "❌ این یوزرنیم تو دیتابیس پیدا نشد! (طرف باید حداقل یه پیام تو گپ داده باشه یا روش ریپلای کنی)", reply_to=msg_id)
                return
            target_id = target_user["user_id"]
            target_name = target_user["first_name"]
        else:
            send_message(chat_id, "❌ فرمت درست:\n`پرداخت @username 100`\nیا روی پیام طرف ریپلای کن بنویس: `پرداخت 100`", reply_to=msg_id)
            return

        if amt <= 0:
            send_message(chat_id, "❌ عدد باید بیشتر از صفر باشه!", reply_to=msg_id)
            return
        if target_id == user_id:
            send_message(chat_id, "😐 به خودت میخوای پول بدی؟!", reply_to=msg_id)
            return
        if u["coins"] < amt:
            send_message(chat_id, "❌ اینقدر کوین تو جیبت نداری!", reply_to=msg_id)
            return

        with db_lock:
            cursor.execute("UPDATE users SET coins = coins - ? WHERE user_id = ?", (amt, user_id))
            cursor.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amt, target_id))
            conn.commit()

        send_message(chat_id, f"💸 انتقال موفق!\n**{amt} کوین** از طرف {first_name} واریز شد به حساب **{target_name}**.", reply_to=msg_id)
        return

    # ۱۰. بخش گنج (بازی با کلمات چند مرحله‌ای)
    if text == "گنج":
        stage = u["treasure_stage"]
        if stage == 0:
            stage = 1
            q_idx = random.randint(0, len(TREASURE_STAGES[1]) - 1)
            with db_lock:
                cursor.execute("UPDATE users SET treasure_stage = 1, treasure_q_idx = ? WHERE user_id = ?", (q_idx, user_id))
                conn.commit()
        else:
            q_idx = u["treasure_q_idx"]

        question = TREASURE_STAGES[stage][q_idx]["q"]
        send_message(
            chat_id,
            f"🗺️ **گنجینه TTF - مرحله {stage} از 3**\n"
            f"━━━━━━━━━━━━━━━\n"
            f"❓ سوال: **{question}**\n\n"
            f"برای پاسخ بنویس: `جواب [پاسخ تو]`",
            reply_to=msg_id
        )
        return

    if text.startswith("جواب "):
        if u["treasure_stage"] == 0:
            send_message(chat_id, "❌ هنوز وارد بازی گنج نشدی! اول بنویس `گنج`.", reply_to=msg_id)
            return

        ans = text.replace("جواب ", "").strip().lower()
        stage = u["treasure_stage"]
        q_idx = u["treasure_q_idx"]
        correct_ans = TREASURE_STAGES[stage][q_idx]["a"].lower()

        if ans == correct_ans:
            if stage < 3:
                next_stage = stage + 1
                next_q_idx = random.randint(0, len(TREASURE_STAGES[next_stage]) - 1)
                with db_lock:
                    cursor.execute("UPDATE users SET treasure_stage = ?, treasure_q_idx = ? WHERE user_id = ?", (next_stage, next_q_idx, user_id))
                    conn.commit()
                next_q = TREASURE_STAGES[next_stage][next_q_idx]["q"]
                send_message(
                    chat_id,
                    f"✅ **درسته باریکلا! رفتی مرحله {next_stage}!**\n\n"
                    f"❓ سوال مرحله {next_stage}: **{next_q}**\n"
                    f"بنویس: `جواب [پاسخ]`",
                    reply_to=msg_id
                )
            else:
                prize = random.randint(30, 120)
                with db_lock:
                    cursor.execute("UPDATE users SET coins = coins + ?, treasure_stage = 0, treasure_q_idx = -1 WHERE user_id = ?", (prize, user_id))
                    conn.commit()
                send_message(chat_id, f"👑 **صندوق گنج رو باز کردی!** 👑\nهر ۳ مرحله رو ترکوندی و **{prize} کوین** جایزه رندوم از دل گنج کشیدی بیرون!", reply_to=msg_id)
        else:
            send_message(chat_id, "❌ جوابت اشتباهه! دوباره فکر کن.", reply_to=msg_id)
        return

    # ۱۱. قابلیت انتخابی: سرقت از بقیه!
    if text.startswith("سرقت"):
        now = time.time()
        if now - u["last_rob"] < ROB_COOLDOWN:
            rem = int(ROB_COOLDOWN - (now - u["last_rob"]))
            m, s = divmod(rem, 60)
            send_message(chat_id, f"🚓 پلیس دنبالته! {m} دقیقه و {s} ثانیه دیگه می‌تونی دوباره سرقت کنی.", reply_to=msg_id)
            return

        target_id = None
        target_name = None
        parts = text.split()
        if "reply_to_message" in msg:
            t_from = msg["reply_to_message"]["from"]
            target_id = t_from["id"]
            target_name = t_from.get("first_name", "کاربر")
            get_or_create_user(target_id, t_from.get("username", ""), target_name)
        elif len(parts) >= 2:
            t_user = find_user_by_username(parts[1])
            if t_user:
                target_id = t_user["user_id"]
                target_name = t_user["first_name"]

        if not target_id or target_id == user_id:
            send_message(chat_id, "❌ روی پیام قربانی ریپلای کن بنویس `سرقت` یا بنویس `سرقت @username`", reply_to=msg_id)
            return

        t_data = get_user_dict(target_id)
        if not t_data or t_data["coins"] < 5:
            send_message(chat_id, "😂 جیب این بنده خدا خالیه (کمتر از ۵ کوین تو جیبشه یا گذاشته تو بانک)!", reply_to=msg_id)
            return

        with db_lock:
            cursor.execute("UPDATE users SET last_rob = ? WHERE user_id = ?", (now, user_id))
            conn.commit()

        if random.random() < 0.5:
            stolen = random.randint(1, max(1, t_data["coins"] // 3))
            with db_lock:
                cursor.execute("UPDATE users SET coins = coins - ? WHERE user_id = ?", (stolen, target_id))
                cursor.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (stolen, user_id))
                conn.commit()
            send_message(chat_id, f"🥷 **سرقت موفق!**\nدزدکی دست کردی تو جیب {target_name} و **{stolen} کوین** کش رفتی!", reply_to=msg_id)
        else:
            fine = min(u["coins"], random.randint(2, 10))
            with db_lock:
                cursor.execute("UPDATE users SET coins = coins - ? WHERE user_id = ?", (fine, user_id))
                cursor.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (fine, target_id))
                conn.commit()
            send_message(chat_id, f"🚨 **گیر افتادی!**\nموقع دزدی از {target_name} لو رفتی و **{fine} کوین** غرامت دادی بهش!", reply_to=msg_id)
        return

    # ۱۲. بازی دوز (دوز [عدد شرط])
    if text.startswith("دوز "):
        bet_str = text.replace("دوز ", "").strip()
        if not bet_str.isdigit() or int(bet_str) < 2:
            send_message(chat_id, "❌ عدد شرط باید حداقل ۲ باشه! مثال: `دوز 100` (ورودی میشه ۵۰)", reply_to=msg_id)
            return

        bet = int(bet_str)
        entry = bet // 2  # طبق قانون: دوز ۱۰۰ یعنی ورودی ۵۰

        with dooz_lock:
            if active_dooz is not None:
                send_message(chat_id, "⚠️ یه بازی دوز همین الان بازه! تا اون تموم نشه نمیشه بازی جدید باز کرد.", reply_to=msg_id)
                return

            if u["coins"] < entry:
                send_message(chat_id, f"❌ برای باز کردن `دوز {bet}` باید حداقل ورودی یعنی **{entry} کوین** تو جیبت داشته باشی!", reply_to=msg_id)
                return

            active_dooz = {
                "chat_id": chat_id,
                "status": "waiting",
                "bet": bet,
                "entry": entry,
                "p1": user_id,
                "p1_name": first_name,
                "p2": None,
                "p2_name": None,
                "board": [" "] * 9,
                "turn_user": user_id,
                "turn_time": time.time(),
            }

            kb = {
                "inline_keyboard": [
                    [{"text": f"⚔️ قبول شرط (ورودی: {entry} کوین)", "callback_data": "dooz_join"}],
                    [{"text": "❌ انصراف سازنده", "callback_data": "dooz_cancel"}]
                ]
            }
            send_message(
                chat_id,
                f"🎲 **چالش بازی دوز باز شد!**\n"
                f"━━━━━━━━━━━━━━━\n"
                f"👤 سازنده: **{first_name}**\n"
                f"💰 کل جایزه میز: **{bet} کوین**\n"
                f"🎟️ ورودی هر نفر: **{entry} کوین**\n"
                f"⚠️ جریمه نزدن نوبت (۶۰ ثانیه): کسر ۲ برابر ورودی ({entry*2} کوین)!\n\n"
                f"کی جرات داره بیاد وسط؟ رو دکمه زیر بزن!",
                reply_to=msg_id,
                reply_markup=kb
            )
        return

# ================= پردازش دکمه‌های شیشه‌ای (دوز) =================
def handle_callback(cb):
    global active_dooz
    cb_id = cb["id"]
    user_id = cb["from"]["id"]
    first_name = cb["from"].get("first_name", "کاربر")
    username = cb["from"].get("username", "")
    chat_id = cb["message"]["chat"]["id"]
    msg_id = cb["message"]["message_id"]
    data = cb["data"]

    get_or_create_user(user_id, username, first_name)

    with dooz_lock:
        if not active_dooz:
            answer_callback(cb_id, "این بازی دیگه تموم شده!")
            return

        if data == "dooz_cancel":
            if user_id != active_dooz["p1"] or active_dooz["status"] != "waiting":
                answer_callback(cb_id, "فقط سازنده قبل از شروع میتونه لغو کنه!")
                return
            active_dooz = None
            edit_message(chat_id, msg_id, "❌ بازی دوز توسط سازنده لغو شد.")
            return

        if data == "dooz_join":
            if active_dooz["status"] != "waiting":
                answer_callback(cb_id, "بازی قبلاً شروع شده!")
                return
            if user_id == active_dooz["p1"]:
                answer_callback(cb_id, "با خودت که نمیتونی بازی کنی ستون!")
                return

            p1_data = get_user_dict(active_dooz["p1"])
            p2_data = get_user_dict(user_id)
            entry = active_dooz["entry"]

            if p1_data["coins"] < entry:
                active_dooz = None
                edit_message(chat_id, msg_id, "❌ سازنده بازی کوینش کم شد و بازی لغو شد!")
                return
            if p2_data["coins"] < entry:
                answer_callback(cb_id, f"کوینت کمه! {entry} کوین ورودی میخواد.")
                return

            # کسر ورودی از هر دو نفر
            with db_lock:
                cursor.execute("UPDATE users SET coins = coins - ? WHERE user_id = ?", (entry, active_dooz["p1"]))
                cursor.execute("UPDATE users SET coins = coins - ? WHERE user_id = ?", (entry, user_id))
                conn.commit()

            active_dooz["status"] = "playing"
            active_dooz["p2"] = user_id
            active_dooz["p2_name"] = first_name
            active_dooz["turn_user"] = active_dooz["p1"]
            active_dooz["turn_time"] = time.time()

            edit_message(
                chat_id,
                msg_id,
                f"⚔️ **بازی دوز شروع شد!** (جایزه: {active_dooz['bet']} کوین)\n"
                f"❌ {active_dooz['p1_name']}\n"
                f"⭕ {active_dooz['p2_name']}\n\n"
                f"👈 نوبت: **{active_dooz['p1_name']}** (۶۰ ثانیه وقت داری)",
                reply_markup=get_dooz_keyboard(active_dooz["board"])
            )
            return

        if data.startswith("dooz_move_"):
            if active_dooz["status"] != "playing":
                return
            if user_id != active_dooz["turn_user"]:
                answer_callback(cb_id, "نوبت تو نیست!")
                return

            idx = int(data.split("_")[-1])
            if active_dooz["board"][idx] != " ":
                answer_callback(cb_id, "این خونه پره!")
                return

            symbol = "X" if user_id == active_dooz["p1"] else "O"
            active_dooz["board"][idx] = symbol
            winner = check_dooz_winner(active_dooz["board"])

            if winner in ["X", "O"]:
                win_id = active_dooz["p1"] if winner == "X" else active_dooz["p2"]
                win_name = active_dooz["p1_name"] if winner == "X" else active_dooz["p2_name"]
                pot = active_dooz["bet"]
                with db_lock:
                    cursor.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (pot, win_id))
                    conn.commit()
                edit_message(
                    chat_id,
                    msg_id,
                    f"🏆 **پایان بازی دوز!**\n"
                    f"برنده میدان: **{win_name}** 🎉\n"
                    f"مقدار **{pot} کوین** رفت تو جیبش!",
                    reply_markup=get_dooz_keyboard(active_dooz["board"])
                )
                active_dooz = None
                return

            elif winner == "DRAW":
                entry = active_dooz["entry"]
                with db_lock:
                    cursor.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (entry, active_dooz["p1"]))
                    cursor.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (entry, active_dooz["p2"]))
                    conn.commit()
                edit_message(
                    chat_id,
                    msg_id,
                    f"🤝 **بازی مساوی شد!**\nورودی هر دو نفر ({entry} کوین) برگشت به جیبشون.",
                    reply_markup=get_dooz_keyboard(active_dooz["board"])
                )
                active_dooz = None
                return

            else:
                next_user = active_dooz["p2"] if user_id == active_dooz["p1"] else active_dooz["p1"]
                next_name = active_dooz["p2_name"] if user_id == active_dooz["p1"] else active_dooz["p1_name"]
                active_dooz["turn_user"] = next_user
                active_dooz["turn_time"] = time.time()

                edit_message(
                    chat_id,
                    msg_id,
                    f"⚔️ **بازی دوز در جریانه!** (جایزه: {active_dooz['bet']} کوین)\n"
                    f"❌ {active_dooz['p1_name']}\n"
                    f"⭕ {active_dooz['p2_name']}\n\n"
                    f"👈 نوبت: **{next_name}** (۶۰ ثانیه وقت داری)",
                    reply_markup=get_dooz_keyboard(active_dooz["board"])
                )

# ================= حلقه اصلی دریافت آپدیت‌های بله =================
def main():
    print("🐹 Hamester Bot (TTF Edition) is running...")
    offset = 0
    while True:
        try:
            resp = requests.get(
                BASE_URL + "getUpdates",
                params={"offset": offset, "timeout": 20},
                timeout=25
            ).json()

            if resp.get("ok"):
                for update in resp.get("result", []):
                    offset = update["update_id"] + 1
                    if "message" in update:
                        handle_message(update["message"])
                    elif "callback_query" in update:
                        handle_callback(update["callback_query"])
        except Exception as e:
            print(f"Polling error: {e}")
            time.sleep(2)

if __name__ == "__main__":
    main()
