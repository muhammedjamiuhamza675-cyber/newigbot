import sqlite3
import time
import random
import os
import logging
from datetime import datetime
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# ================= LOGGING =================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ================= CONFIG =================
BOT_TOKEN = "8042789426:AAEKHcwcs12zw_rPltc6LhCBTSxISYIJ7TE"
ADMIN_ID = 7443685686
BOT_USERNAME = "hamzzyhacket"

BANK_NAME = "OPAY"
ACCOUNT_NUMBER = "9032741650"
ACCOUNT_NAME = "MUHAMMED JAMIU HAMZA"
WHATSAPP_NUMBER = "2349167685658"

LOW_STOCK_LIMIT = 3
REFERRAL_BONUS = 250

PRODUCTS = {
    "0 (#1000)": 1000, "30-40 (#1500)": 1500, "50-80 (#2000)": 2000,
    "90-100 (#3000)": 3000, "200 (#4000)": 4000, "300 (#5000)": 5000,
    "400 (#5500)": 5500, "500 (#6000)": 6000, "600 (#6500)": 6500,
    "700 (#7000)": 7000, "800 (#7500)": 7500, "900 (#8000)": 8000,
    "1000 (#8500)": 8500
}

# ================= DATABASE =================
DB_PATH = "bot.db"
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

cursor.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, balance INTEGER DEFAULT 0)")
cursor.execute("CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, type TEXT, amount INTEGER, details TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS stats (key TEXT PRIMARY KEY, value INTEGER)")
cursor.execute("CREATE TABLE IF NOT EXISTS deposits (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, sender_name TEXT, ref TEXT, amount INTEGER DEFAULT 0, status TEXT DEFAULT 'pending', decline_reason TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS reports (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, issue_type TEXT, description TEXT, status TEXT DEFAULT 'open', admin_response TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
cursor.execute("CREATE TABLE IF NOT EXISTS stock (id INTEGER PRIMARY KEY AUTOINCREMENT, product_name TEXT, email TEXT, status TEXT DEFAULT 'available')")
cursor.execute("CREATE TABLE IF NOT EXISTS sales_log (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, product_name TEXT, amount INTEGER, sale_date DATE)")
cursor.execute("CREATE TABLE IF NOT EXISTS referrals (id INTEGER PRIMARY KEY AUTOINCREMENT, referrer_id INTEGER, referred_id INTEGER UNIQUE)")
cursor.execute("CREATE TABLE IF NOT EXISTS referral_earnings (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount INTEGER, from_user_id INTEGER)")
cursor.execute("CREATE TABLE IF NOT EXISTS broadcast_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, admin_id INTEGER, message TEXT, total_sent INTEGER, total_failed INTEGER, sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
cursor.execute("CREATE TABLE IF NOT EXISTS restock_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, admin_id INTEGER, product_name TEXT, quantity INTEGER, restock_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
cursor.execute("CREATE TABLE IF NOT EXISTS cart (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, product_name TEXT, price INTEGER, quantity INTEGER DEFAULT 1)")
conn.commit()

for k in ["revenue", "orders"]:
    cursor.execute("INSERT OR IGNORE INTO stats (key,value) VALUES (?,0)", (k,))
conn.commit()

print("✅ Database initialized!")

# ================= BOT =================
bot = telebot.TeleBot(BOT_TOKEN)

# ================= MEMORY =================
pending_approvals = {}
fraud_tracker = {}
blocked_users = set()
user_support_mode = {}
user_data = {}

# ================= HELPERS =================
def get_balance(uid):
    cursor.execute("SELECT balance FROM users WHERE user_id=?", (uid,))
    r = cursor.fetchone()
    return r[0] if r else 0

def add_user(uid):
    cursor.execute("INSERT OR IGNORE INTO users (user_id,balance) VALUES (?,0)", (uid,))
    conn.commit()

def update_stat(k, v):
    cursor.execute("UPDATE stats SET value=value+? WHERE key=?", (v, k))
    conn.commit()

def get_stat(k):
    cursor.execute("SELECT value FROM stats WHERE key=?", (k,))
    r = cursor.fetchone()
    return r[0] if r else 0

def log(uid, t, amt, d):
    cursor.execute("INSERT INTO transactions (user_id,type,amount,details) VALUES (?,?,?,?)", (uid, t, amt, d))
    conn.commit()

def generate_ref():
    return f"REF-{random.randint(100000,999999)}"

def get_stock_count(product_name):
    cursor.execute("SELECT COUNT(*) FROM stock WHERE product_name=? AND status='available'", (product_name,))
    return cursor.fetchone()[0]

def get_all_stock():
    stock = {}
    for name in PRODUCTS:
        cursor.execute("SELECT COUNT(*) FROM stock WHERE product_name=? AND status='available'", (name,))
        stock[name] = cursor.fetchone()[0]
    return stock

def get_item_from_stock(product_name):
    cursor.execute("SELECT id, email FROM stock WHERE product_name=? AND status='available' LIMIT 1", (product_name,))
    return cursor.fetchone()

def mark_item_sold(item_id):
    cursor.execute("UPDATE stock SET status='sold' WHERE id=?", (item_id,))
    conn.commit()

def add_to_stock(product_name, email):
    cursor.execute("SELECT id FROM stock WHERE email=? AND status='available'", (email,))
    if cursor.fetchone():
        return False
    cursor.execute("INSERT INTO stock (product_name, email) VALUES (?,?)", (product_name, email))
    conn.commit()
    return True

def add_bulk_to_stock(product_name, emails):
    added = 0
    for email in emails:
        if add_to_stock(product_name, email):
            added += 1
    return added

def clear_all_stock():
    cursor.execute("DELETE FROM stock")
    conn.commit()

def clear_product_stock(product_name):
    cursor.execute("DELETE FROM stock WHERE product_name=?", (product_name,))
    conn.commit()

def extract_stock(product_name):
    cursor.execute("SELECT email FROM stock WHERE product_name=? AND status='available'", (product_name,))
    rows = cursor.fetchall()
    return [r[0] for r in rows]

def get_cart(user_id):
    cursor.execute("SELECT id, product_name, price, quantity FROM cart WHERE user_id=?", (user_id,))
    return cursor.fetchall()

def add_to_cart(user_id, product_name, price):
    cursor.execute("SELECT id, quantity FROM cart WHERE user_id=? AND product_name=?", (user_id, product_name))
    row = cursor.fetchone()
    if row:
        cursor.execute("UPDATE cart SET quantity=quantity+1 WHERE id=?", (row[0],))
    else:
        cursor.execute("INSERT INTO cart (user_id, product_name, price, quantity) VALUES (?,?,?,1)", (user_id, product_name, price))
    conn.commit()

def remove_from_cart(user_id, cart_id):
    cursor.execute("DELETE FROM cart WHERE id=? AND user_id=?", (cart_id, user_id))
    conn.commit()

def clear_cart(user_id):
    cursor.execute("DELETE FROM cart WHERE user_id=?", (user_id,))
    conn.commit()

def get_cart_total(user_id):
    cursor.execute("SELECT SUM(price * quantity) FROM cart WHERE user_id=?", (user_id,))
    r = cursor.fetchone()
    return r[0] if r[0] else 0

def generate_referral_link(user_id):
    return f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"

def get_items_from_stock(product_name, quantity):
    cursor.execute("SELECT id, email FROM stock WHERE product_name=? AND status='available' LIMIT ?", (product_name, quantity))
    return cursor.fetchall()

# ================= AUTO-RESPONDER =================
AUTO_RESPONSES = {
    "price": "💰 Prices: ₦1000 – ₦8500. Check 📦 Check Stock.",
    "how": "📋 Buy uncreated Gmail → Create it → Instagram 'Forgot Password' → Reset → Own both!",
    "gmail": "📧 We sell UNCREATED Gmail addresses. You create them yourself.",
    "buy": "🛒 Fund wallet → Buy Products → Click BUY to purchase instantly → Confirm → Get email!",
    "fund": f"💳 Click '➕ Fund Wallet' → Transfer to {BANK_NAME} ({ACCOUNT_NUMBER}) → Send name → Upload screenshot.",
    "stock": "📦 Check /stock or press '📦 Check Stock'.",
    "referral": f"🤝 Earn ₦{REFERRAL_BONUS} per referral! Use /refer or press '🤝 Refer & Earn'.",
    "contact": f"📞 WhatsApp: {WHATSAPP_NUMBER}",
    "help": "📋 Use the buttons on the menu. For quick support, click '🤖 Expert Support'.",
}

def get_auto_reply(text):
    text_lower = text.lower()
    for key, response in AUTO_RESPONSES.items():
        if key in text_lower:
            return response
    return None

# ================= LOADING ANIMATION =================
def show_loading_animation(message, chat_id, text="Processing your order..."):
    frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    sent = bot.send_message(chat_id, f"🔄 **{text}**\n\n`⠋ [░░░░░░░░░░] 0%`", parse_mode='Markdown')
    
    for i in range(10):
        frame = frames[i % len(frames)]
        progress = (i + 1) * 10
        bar = "█" * (i + 1) + "░" * (9 - i)
        try:
            bot.edit_message_text(
                f"⚡ **{text}**\n\n"
                f"`{frame} [{bar}] {progress}%`\n"
                f"`🤖 AI Processing...`",
                chat_id=chat_id,
                message_id=sent.message_id,
                parse_mode='Markdown'
            )
            time.sleep(0.15)
        except:
            pass
    
    return sent

def show_welcome_loading(message):
    frames = ["✨", "🌟", "⭐", "💫", "🔥"]
    sent = bot.send_message(message.chat.id, "🎯 **Initializing Bot...**\n\n`⠋ [░░░░░░░░░░] 0%`", parse_mode='Markdown')
    
    for i in range(10):
        frame = frames[i % len(frames)]
        progress = (i + 1) * 10
        bar = "█" * (i + 1) + "░" * (9 - i)
        try:
            bot.edit_message_text(
                f"{frame} **Initializing Bot...**\n\n"
                f"`[{bar}] {progress}%`\n"
                f"`🤖 Loading Features...`",
                chat_id=message.chat.id,
                message_id=sent.message_id,
                parse_mode='Markdown'
            )
            time.sleep(0.15)
        except:
            pass
    
    return sent

# ================= KEYBOARDS =================
def get_main_keyboard(user_id):
    menu = [
        ["💰 Wallet", "➕ Fund Wallet"],
        ["📦 Check Stock", "🧾 My History"],
        ["💳 My Deposits", "🛒 Buy Products"],
        ["🤖 Expert Support", "📝 Report Issue"],
        ["🤝 Refer & Earn", "🛒 My Cart"],
        ["📋 Help & FAQ", "📞 Contact"]
    ]
    if user_id == ADMIN_ID:
        menu.append(["👑 Admin Panel"])
    return ReplyKeyboardMarkup(menu, resize_keyboard=True)

def get_admin_keyboard():
    kb = [
        ["📊 Stats", "📥 Pending"],
        ["📝 Reports", "💰 Add Funds"],
        ["💸 Deduct Funds", "📈 Sales"],
        ["📦 Restock", "📢 Broadcast"],
        ["💬 Message User", "👤 View Balance"],
        ["🚫 Block/Unblock", "🗑 Clear Stock"],
        ["📤 Extract Stock", "🔄 User Menu"]
    ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

# ================= COMMANDS =================
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    add_user(user_id)
    user_support_mode.pop(user_id, None)
    
    # Show welcome loading
    show_welcome_loading(message)
    
    if message.text and "ref_" in message.text:
        try:
            referrer_id = int(message.text.split("ref_")[1].strip())
            if referrer_id != user_id:
                cursor.execute("SELECT id FROM referrals WHERE referred_id=?", (user_id,))
                if not cursor.fetchone() and referrer_id != user_id:
                    cursor.execute("INSERT INTO referrals (referrer_id, referred_id) VALUES (?,?)", (referrer_id, user_id))
                    cursor.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (REFERRAL_BONUS, referrer_id))
                    cursor.execute("INSERT INTO referral_earnings (user_id, amount, from_user_id) VALUES (?,?,?)", (referrer_id, REFERRAL_BONUS, user_id))
                    log(referrer_id, "credit", REFERRAL_BONUS, f"referral_from_{user_id}")
                    conn.commit()
                    try: bot.send_message(referrer_id, f"🎉 New referral! +₦{REFERRAL_BONUS}")
                    except: pass
        except: pass

    cart_count = len(get_cart(user_id))
    cart_text = f" | 🛒 {cart_count} items" if cart_count > 0 else ""

    bot.send_message(
        user_id,
        f"🛒 **Store Bot**{cart_text}\n\n"
        f"📧 Buy uncreated Gmail → Create → Recover IG\n"
        f"🤝 Earn ₦{REFERRAL_BONUS}/referral!\n"
        f"📞 Contact: WhatsApp {WHATSAPP_NUMBER}",
        reply_markup=get_main_keyboard(user_id),
        parse_mode='Markdown'
    )

@bot.message_handler(commands=['admin'])
def admin_command(message):
    if message.from_user.id != ADMIN_ID: return
    bot.send_message(message.chat.id, "👑 **ADMIN PANEL**", reply_markup=get_admin_keyboard(), parse_mode='Markdown')

# ================= CONTACT =================
@bot.message_handler(func=lambda m: m.text == "📞 Contact")
def contact_handler(message):
    bot.send_message(
        message.chat.id,
        f"📞 **CONTACT US**\n\n📱 WhatsApp: `{WHATSAPP_NUMBER}`\n👤 Bot Owner: @{BOT_USERNAME}",
        parse_mode='Markdown'
    )

# ================= WALLET =================
@bot.message_handler(func=lambda m: m.text == "💰 Wallet")
def wallet(message):
    bot.send_message(message.chat.id, f"💰 Balance: ₦{get_balance(message.from_user.id)}")

# ================= FUND =================
@bot.message_handler(func=lambda m: m.text == "➕ Fund Wallet")
def fund(message):
    ref = generate_ref()
    user_data[message.from_user.id] = {"fund_ref": ref}
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ I've Made Payment", callback_data=f"pay:{ref}"))
    bot.send_message(
        message.chat.id,
        f"💳 **FUND YOUR WALLET**\n\n🏦 {BANK_NAME}\n🔢 {ACCOUNT_NUMBER}\n👤 {ACCOUNT_NAME}\n\n🆔 {ref}\n\n📝 Send SENDER NAME first.",
        reply_markup=markup,
        parse_mode='Markdown'
    )
    bot.register_next_step_handler(message, process_fund_name, ref)

def process_fund_name(message, ref):
    user_id = message.from_user.id
    sender_name = message.text
    user_data[user_id] = {"sender_name": sender_name, "ref": ref}
    bot.send_message(user_id, "📸 Now send SCREENSHOT of your payment.")
    bot.register_next_step_handler(message, process_fund_screenshot)

def process_fund_screenshot(message):
    user_id = message.from_user.id
    if not message.photo:
        bot.send_message(user_id, "❌ Please send a photo.")
        return
    photo_id = message.photo[-1].file_id
    data = user_data.get(user_id, {})
    sender_name = data.get("sender_name", "Unknown")
    ref = data.get("ref", generate_ref())
    
    cursor.execute("INSERT INTO deposits (user_id, sender_name, ref, status) VALUES (?,?,?,?)", (user_id, sender_name, ref, "pending"))
    conn.commit()
    pending_approvals[user_id] = {"sender_name": sender_name, "photo_id": photo_id, "ref": ref, "full_name": message.from_user.full_name}
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✅ Approve", callback_data=f"approve:{user_id}"))
    kb.add(InlineKeyboardButton("❌ Reject", callback_data=f"reject:{user_id}"))
    bot.send_photo(ADMIN_ID, photo_id, caption=f"💳 **NEW DEPOSIT**\n👤 {message.from_user.full_name}\n🆔 {user_id}\n🏦 {sender_name}\n🔢 {ref}", reply_markup=kb, parse_mode='Markdown')
    bot.send_message(user_id, "✅ Submitted! Waiting for approval.")

# ================= STOCK =================
@bot.message_handler(func=lambda m: m.text == "📦 Check Stock")
def user_stock(message):
    msg = "📦 **STOCK**\n\n"
    stock = get_all_stock()
    for name in PRODUCTS:
        msg += f"{'✅' if stock[name] > 0 else '❌'} {name}: {stock[name]} available\n"
    bot.send_message(message.chat.id, msg, parse_mode='Markdown')

# ================= HISTORY =================
@bot.message_handler(func=lambda m: m.text == "🧾 My History")
def history(message):
    uid = message.from_user.id
    cursor.execute("SELECT type,amount,details FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 10", (uid,))
    rows = cursor.fetchall()
    if not rows:
        bot.send_message(message.chat.id, "📭 No transactions yet")
        return
    msg = "🧾 **YOUR HISTORY**\n\n"
    for t, a, d in rows:
        msg += f"{'➕' if t=='credit' else '➖'} ₦{a} - {d}\n"
    bot.send_message(message.chat.id, msg, parse_mode='Markdown')

# ================= DEPOSITS =================
@bot.message_handler(func=lambda m: m.text == "💳 My Deposits")
def my_deposits(message):
    uid = message.from_user.id
    cursor.execute("SELECT ref, amount, status, decline_reason FROM deposits WHERE user_id=? ORDER BY id DESC LIMIT 5", (uid,))
    rows = cursor.fetchall()
    if not rows:
        bot.send_message(message.chat.id, "📭 No deposits yet")
        return
    msg = "💳 **YOUR DEPOSITS**\n\n"
    for r, a, s, dr in rows:
        emoji = "✅" if s == "approved" else "⏳" if s == "pending" else "❌"
        msg += f"{emoji} {r}: {'₦'+str(a) if a else '...'} ({s})\n"
        if dr:
            msg += f"   📋 {dr}\n"
    bot.send_message(message.chat.id, msg, parse_mode='Markdown')

# ================= BUY PRODUCTS =================
@bot.message_handler(func=lambda m: m.text == "🛒 Buy Products")
def buy_products_menu(message):
    k = InlineKeyboardMarkup(row_width=1)
    k.add(InlineKeyboardButton("📧 Small (0-100)", callback_data="cat_small"))
    k.add(InlineKeyboardButton("📧 Medium (200-500)", callback_data="cat_medium"))
    k.add(InlineKeyboardButton("📧 Large (600-1000)", callback_data="cat_large"))
    k.add(InlineKeyboardButton("📦 All", callback_data="cat_all"))
    bot.send_message(message.chat.id, "🛒 **BUY PRODUCTS**\n\nSelect category:", reply_markup=k, parse_mode='Markdown')

# ================= CART =================
@bot.message_handler(func=lambda m: m.text == "🛒 My Cart")
def view_cart(message):
    u = message.from_user
    items = get_cart(u.id)
    if not items:
        k = InlineKeyboardMarkup()
        k.add(InlineKeyboardButton("🛒 Browse Products", callback_data="cat_all"))
        bot.send_message(message.chat.id, "🛒 Cart empty!", reply_markup=k)
        return
    total = get_cart_total(u.id)
    bal = get_balance(u.id)
    msg = f"🛒 **YOUR CART**\n\n"
    kb = InlineKeyboardMarkup(row_width=2)
    for item in items:
        cart_id, pn, pr, qty = item
        msg += f"📦 {pn}\n   Qty: {qty} × ₦{pr} = ₦{pr*qty}\n\n"
        kb.add(InlineKeyboardButton(f"➕", callback_data=f"qtyadd_{cart_id}"), InlineKeyboardButton(f"➖", callback_data=f"qtysub_{cart_id}"), InlineKeyboardButton(f"❌", callback_data=f"rmcart_{cart_id}"))
    msg += f"━━━━━━━━━━━━━━━\n💰 **Total: ₦{total}**\n💳 Balance: ₦{bal}\n"
    if total > 0 and bal >= total:
        msg += f"\n✅ You have enough funds!"
        kb.add(InlineKeyboardButton("✅ CHECKOUT NOW", callback_data="checkout"))
    elif total > 0:
        msg += f"\n⚠️ Insufficient! Need ₦{total - bal} more."
    kb.add(InlineKeyboardButton("🗑 Clear Cart", callback_data="clearcart"))
    kb.add(InlineKeyboardButton("🛒 Continue Shopping", callback_data="cat_all"))
    bot.send_message(message.chat.id, msg, reply_markup=kb, parse_mode='Markdown')

# ================= SUPPORT =================
@bot.message_handler(func=lambda m: m.text == "🤖 Expert Support")
def expert_support(message):
    user_support_mode[message.from_user.id] = True
    bot.send_message(message.chat.id, "🤖 **SUPPORT**\n\nAsk me anything!\nType 'exit' to leave.", reply_markup=ReplyKeyboardMarkup([["❌ Exit Support"]], resize_keyboard=True), parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text == "❌ Exit Support")
def exit_support(message):
    user_support_mode.pop(message.from_user.id, None)
    start(message)

# ================= REPORT =================
@bot.message_handler(func=lambda m: m.text == "📝 Report Issue")
def report_issue(message):
    k = InlineKeyboardMarkup(row_width=1)
    k.add(InlineKeyboardButton("📧 Gmail Taken", callback_data="report_taken"))
    k.add(InlineKeyboardButton("📷 IG Not Linked", callback_data="report_notlinked"))
    k.add(InlineKeyboardButton("💳 Payment", callback_data="report_payment"))
    k.add(InlineKeyboardButton("❓ Other", callback_data="report_other"))
    bot.send_message(message.chat.id, "📝 **FILE A REPORT**\n\nSelect type:", reply_markup=k, parse_mode='Markdown')

# ================= REFER =================
@bot.message_handler(func=lambda m: m.text == "🤝 Refer & Earn")
def refer_earn_menu(message):
    bot.send_message(message.chat.id, f"🤝 **REFER & EARN ₦{REFERRAL_BONUS}**\n\n🔗 `{generate_referral_link(message.from_user.id)}`", parse_mode='Markdown')

# ================= HELP =================
@bot.message_handler(func=lambda m: m.text == "📋 Help & FAQ")
def help_faq(message):
    k = InlineKeyboardMarkup(row_width=1)
    k.add(InlineKeyboardButton("📋 How It Works", callback_data="faq_how"))
    k.add(InlineKeyboardButton("💳 How to Fund", callback_data="faq_fund"))
    k.add(InlineKeyboardButton("🛒 How to Buy", callback_data="faq_buy"))
    k.add(InlineKeyboardButton("🛒 Using Cart", callback_data="faq_cart"))
    k.add(InlineKeyboardButton("🔄 Replacements", callback_data="faq_replace"))
    bot.send_message(message.chat.id, "📋 **HELP & FAQ**", reply_markup=k, parse_mode='Markdown')

# ================= ADMIN PANEL =================
@bot.message_handler(func=lambda m: m.text == "👑 Admin Panel")
def admin_panel(message):
    if message.from_user.id != ADMIN_ID: return
    bot.send_message(message.chat.id, "👑 **ADMIN PANEL**", reply_markup=get_admin_keyboard(), parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text == "📊 Stats")
def stats(message):
    if message.from_user.id != ADMIN_ID: return
    cursor.execute("SELECT COUNT(*) FROM users")
    u = cursor.fetchone()[0]
    bot.send_message(message.chat.id, f"📊 Users: {u}\n📦 Orders: {get_stat('orders')}\n💰 Revenue: ₦{get_stat('revenue')}", parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text == "📥 Pending")
def pending_deposits(message):
    if message.from_user.id != ADMIN_ID: return
    if not pending_approvals:
        bot.send_message(message.chat.id, "✅ No pending")
        return
    for uid, data in pending_approvals.items():
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("✅ Approve", callback_data=f"approve:{uid}"))
        kb.add(InlineKeyboardButton("❌ Reject", callback_data=f"reject:{uid}"))
        try:
            bot.send_photo(ADMIN_ID, data["photo_id"], caption=f"💳 {uid}\n👤 {data.get('full_name','?')}\n🏦 {data['sender_name']}\n🔢 {data['ref']}", reply_markup=kb)
        except: pass

@bot.message_handler(func=lambda m: m.text == "📝 Reports")
def view_reports(message):
    if message.from_user.id != ADMIN_ID: return
    cursor.execute("SELECT id, user_id, issue_type, description FROM reports WHERE status='open' ORDER BY id DESC LIMIT 10")
    rows = cursor.fetchall()
    if not rows:
        bot.send_message(message.chat.id, "✅ No reports")
        return
    for rid, uid, it, desc in rows:
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("✅ Resolve", callback_data=f"resolve_{rid}"))
        kb.add(InlineKeyboardButton("💬 Reply", callback_data=f"reply_{rid}"))
        kb.add(InlineKeyboardButton("💰 Add", callback_data=f"addfund_{uid}"))
        bot.send_message(message.chat.id, f"📝 #{rid} | 👤 {uid} | 🏷 {it}\n📄 {desc[:200]}", reply_markup=kb, parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text == "💰 Add Funds")
def admin_addfund_start(message):
    if message.from_user.id != ADMIN_ID: return
    bot.send_message(message.chat.id, "💰 **ADD FUNDS**\n\nEnter USER ID then AMOUNT:\nFormat: `user_id amount`", parse_mode='Markdown')
    bot.register_next_step_handler(message, process_admin_addfund)

def process_admin_addfund(message):
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.send_message(message.chat.id, "❌ Format: user_id amount")
            return
        tid, amt = int(parts[0]), int(parts[1])
        add_user(tid)
        cursor.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amt, tid))
        conn.commit()
        log(tid, "credit", amt, "admin_addfund")
        bot.send_message(message.chat.id, f"✅ Added ₦{amt} to {tid}")
    except:
        bot.send_message(message.chat.id, "❌ Error! Format: user_id amount")

@bot.message_handler(func=lambda m: m.text == "💸 Deduct Funds")
def admin_deductfund_start(message):
    if message.from_user.id != ADMIN_ID: return
    bot.send_message(message.chat.id, "💸 **DEDUCT FUNDS**\n\nEnter USER ID then AMOUNT:\nFormat: `user_id amount`", parse_mode='Markdown')
    bot.register_next_step_handler(message, process_admin_deductfund)

def process_admin_deductfund(message):
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.send_message(message.chat.id, "❌ Format: user_id amount")
            return
        tid, amt = int(parts[0]), int(parts[1])
        if get_balance(tid) < amt:
            bot.send_message(message.chat.id, f"⚠️ Only ₦{get_balance(tid)}")
            return
        cursor.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (amt, tid))
        conn.commit()
        log(tid, "debit", amt, "admin_deduct")
        bot.send_message(message.chat.id, f"✅ Deducted ₦{amt}")
    except:
        bot.send_message(message.chat.id, "❌ Error! Format: user_id amount")

@bot.message_handler(func=lambda m: m.text == "👤 View Balance")
def view_balance_start(message):
    if message.from_user.id != ADMIN_ID: return
    bot.send_message(message.chat.id, "👤 **VIEW USER BALANCE**\n\nEnter USER ID:", parse_mode='Markdown')
    bot.register_next_step_handler(message, process_view_balance)

def process_view_balance(message):
    try:
        uid = int(message.text.strip())
        bal = get_balance(uid)
        bot.send_message(message.chat.id, f"👤 User: {uid}\n💰 Balance: ₦{bal}")
    except:
        bot.send_message(message.chat.id, "❌ Invalid ID!")

@bot.message_handler(func=lambda m: m.text == "📈 Sales")
def sales_menu(message):
    if message.from_user.id != ADMIN_ID: return
    cursor.execute("SELECT COUNT(*), COALESCE(SUM(amount),0) FROM sales_log WHERE sale_date=date('now')")
    td = cursor.fetchone()
    cursor.execute("SELECT COUNT(*), COALESCE(SUM(amount),0) FROM sales_log WHERE sale_date>=date('now','-7 days')")
    wk = cursor.fetchone()
    bot.send_message(message.chat.id, f"📈 **SALES**\n\n📆 Today: {td[0]} orders, ₦{td[1]}\n📅 Week: {wk[0]} orders, ₦{wk[1]}\n💰 All: ₦{get_stat('revenue')}", parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text == "📢 Broadcast")
def broadcast_menu(message):
    if message.from_user.id != ADMIN_ID: return
    bot.send_message(message.chat.id, "📢 **BROADCAST**\n\nSend your message:", parse_mode='Markdown')
    bot.register_next_step_handler(message, process_broadcast)

def process_broadcast(message):
    if message.from_user.id != ADMIN_ID: return
    msg = message.text
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    sent = 0
    failed = 0
    for (uid,) in users:
        try:
            bot.send_message(uid, f"📢 {msg}")
            sent += 1
        except:
            failed += 1
    bot.send_message(message.chat.id, f"✅ Done!\n✅ Sent: {sent}\n❌ Failed: {failed}")

@bot.message_handler(func=lambda m: m.text == "💬 Message User")
def message_user_start(message):
    if message.from_user.id != ADMIN_ID: return
    bot.send_message(message.chat.id, "💬 **MESSAGE USER**\n\nEnter USER ID:", parse_mode='Markdown')
    bot.register_next_step_handler(message, process_msg_user)

def process_msg_user(message):
    try:
        uid = int(message.text.strip())
        bot.send_message(message.chat.id, f"👤 User: {uid}\n\nSend your message:")
        bot.register_next_step_handler(message, process_send_msg, uid)
    except:
        bot.send_message(message.chat.id, "❌ Invalid ID!")

def process_send_msg(message, uid):
    try:
        bot.send_message(uid, f"📬 **Message from Admin:**\n\n{message.text}")
        bot.send_message(message.chat.id, f"✅ Sent to {uid}!")
    except:
        bot.send_message(message.chat.id, f"❌ Failed to send to {uid}")

@bot.message_handler(func=lambda m: m.text == "🚫 Block/Unblock")
def block_unblock_menu(message):
    if message.from_user.id != ADMIN_ID: return
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🚫 Block User", callback_data="block_menu"))
    kb.add(InlineKeyboardButton("✅ Unblock User", callback_data="unblock_menu"))
    kb.add(InlineKeyboardButton("📋 View Blocked", callback_data="blocked_list"))
    bot.send_message(message.chat.id, "🚫 **BLOCK/UNBLOCK**", reply_markup=kb, parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text == "🗑 Clear Stock")
def clear_stock_menu(message):
    if message.from_user.id != ADMIN_ID: return
    stock = get_all_stock()
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🗑 CLEAR ALL", callback_data="clearstock_all"))
    for name, count in stock.items():
        if count > 0:
            kb.add(InlineKeyboardButton(f"🗑 {name} ({count})", callback_data=f"clearstock_{name}"))
    kb.add(InlineKeyboardButton("❌ Cancel", callback_data="clearstock_cancel"))
    bot.send_message(message.chat.id, "🗑 **CLEAR STOCK**", reply_markup=kb, parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text == "📤 Extract Stock")
def extract_stock_menu(message):
    if message.from_user.id != ADMIN_ID: return
    stock = get_all_stock()
    kb = InlineKeyboardMarkup()
    for name, count in stock.items():
        if count > 0:
            kb.add(InlineKeyboardButton(f"📤 {name} ({count})", callback_data=f"extract_{name}"))
    kb.add(InlineKeyboardButton("📤 ALL", callback_data="extract_all"))
    bot.send_message(message.chat.id, "📤 **EXTRACT STOCK**", reply_markup=kb, parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text == "📦 Restock")
def restock_menu(message):
    if message.from_user.id != ADMIN_ID: return
    stock = get_all_stock()
    kb = InlineKeyboardMarkup(row_width=1)
    for n in PRODUCTS:
        kb.add(InlineKeyboardButton(f"{n} - {stock[n]}", callback_data=f"restock_{n}"))
    kb.add(InlineKeyboardButton("🔙 Back", callback_data="back_to_admin"))
    bot.send_message(message.chat.id, "📦 **RESTOCK**", reply_markup=kb, parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text == "🔄 User Menu")
def switch_to_user_menu(message):
    if message.from_user.id != ADMIN_ID: return
    bot.send_message(message.chat.id, "🔄 Switched to User Menu", reply_markup=get_main_keyboard(message.from_user.id))

# ================= CALLBACK HANDLER =================
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    data = call.data
    
    # Handle payment
    if data.startswith("pay:"):
        ref = data.split(":")[1]
        bot.send_message(call.message.chat.id, f"💳 REF: {ref}\n\n📝 Send SENDER NAME.")
        bot.register_next_step_handler(call.message, process_fund_name, ref)
        bot.answer_callback_query(call.id)
        return
    
    # Handle buy categories
    if data.startswith("cat_"):
        cat = data.replace("cat_", "")
        if cat == "small":
            p = {k: v for k, v in PRODUCTS.items() if v <= 3000}
            t = "Small"
        elif cat == "medium":
            p = {k: v for k, v in PRODUCTS.items() if 4000 <= v <= 6000}
            t = "Medium"
        elif cat == "large":
            p = {k: v for k, v in PRODUCTS.items() if v >= 6500}
            t = "Large"
        else:
            p = PRODUCTS
            t = "All"
        msg = f"**{t}**\n\n🛒 Click to BUY NOW | ➕ Click to ADD TO CART\n\n"
        kb = InlineKeyboardMarkup(row_width=2)
        for n, pr in p.items():
            s = get_stock_count(n)
            msg += f"{'✅' if s > 0 else '❌'} {n}: {s} available - ₦{pr}\n"
            if s > 0:
                kb.add(InlineKeyboardButton(f"🛒 BUY {n}", callback_data=f"buy_{n}"), InlineKeyboardButton(f"➕ Cart", callback_data=f"addcart_{n}"))
        kb.add(InlineKeyboardButton("🔙 Back", callback_data="back_to_categories"))
        bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, reply_markup=kb, parse_mode='Markdown')
        bot.answer_callback_query(call.id)
        return
    
    if data == "back_to_categories":
        k = InlineKeyboardMarkup(row_width=1)
        k.add(InlineKeyboardButton("📧 Small (0-100)", callback_data="cat_small"))
        k.add(InlineKeyboardButton("📧 Medium (200-500)", callback_data="cat_medium"))
        k.add(InlineKeyboardButton("📧 Large (600-1000)", callback_data="cat_large"))
        k.add(InlineKeyboardButton("📦 All", callback_data="cat_all"))
        bot.edit_message_text("🛒 **BUY PRODUCTS**\n\nSelect category:", call.message.chat.id, call.message.message_id, reply_markup=k, parse_mode='Markdown')
        bot.answer_callback_query(call.id)
        return
    
    # Handle buy product
    if data.startswith("buy_"):
        pn = data.replace("buy_", "")
        if pn not in PRODUCTS:
            return
        pr = PRODUCTS[pn]
        if get_stock_count(pn) == 0:
            bot.answer_callback_query(call.id, "❌ Out of stock!", show_alert=True)
            return
        bal = get_balance(user_id)
        if bal < pr:
            bot.answer_callback_query(call.id, f"❌ Insufficient! Need ₦{pr}", show_alert=True)
            return
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_{pn}"))
        kb.add(InlineKeyboardButton("❌ Cancel", callback_data="back_to_categories"))
        bot.edit_message_text(f"🛒 **CONFIRM**\n\n📦 {pn}\n💰 Price: ₦{pr}\n💳 Balance: ₦{bal}\n💳 After: ₦{bal-pr}", call.message.chat.id, call.message.message_id, reply_markup=kb, parse_mode='Markdown')
        bot.answer_callback_query(call.id)
        return
    
    # Handle confirm purchase with AI loading animation
    if data.startswith("confirm_"):
        pn = data.replace("confirm_", "")
        if pn not in PRODUCTS:
            return
        pr = PRODUCTS[pn]
        if get_balance(user_id) < pr:
            bot.answer_callback_query(call.id, "❌ Insufficient!", show_alert=True)
            return
        item = get_item_from_stock(pn)
        if not item:
            bot.answer_callback_query(call.id, "❌ Out of stock!", show_alert=True)
            return
        item_id, email = item
        
        # AI LOADING ANIMATION
        sent = bot.edit_message_text("🔄 **AI Processing Your Order...**\n\n`[░░░░░░░░░░] 0%`", call.message.chat.id, call.message.message_id, parse_mode='Markdown')
        for i in range(1, 11):
            percent = i * 10
            bar = "█" * i + "░" * (10 - i)
            bot.edit_message_text(f"⚡ **AI Processing Your Order...**\n\n`[{bar}] {percent}%`\n`🤖 AI Validating Stock...`", call.message.chat.id, call.message.message_id, parse_mode='Markdown')
            time.sleep(0.15)
        
        mark_item_sold(item_id)
        cursor.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (pr, user_id))
        conn.commit()
        update_stat("revenue", pr)
        update_stat("orders", 1)
        log(user_id, "purchase", pr, pn)
        new_bal = get_balance(user_id)
        
        receipt = f"""
╔══════════════════════════════════════╗
║         📄 PURCHASE RECEIPT          ║
╠══════════════════════════════════════╣
║  🆔 Order ID: #{random.randint(10000,99999)}
║  📅 Date: {time.strftime('%Y-%m-%d %H:%M')}
║  📦 Product: {pn}
║  📧 Email: `{email}`
║  💰 Amount: ₦{pr}
║  💳 Balance: ₦{new_bal}
║  ✅ Status: COMPLETED
╚══════════════════════════════════════╝
"""
        bot.edit_message_text(f"✅ **PURCHASED!**\n\n{receipt}", call.message.chat.id, call.message.message_id, parse_mode='Markdown')
        bot.answer_callback_query(call.id)
        return
    
    # Handle add to cart
    if data.startswith("addcart_"):
        pn = data.replace("addcart_", "")
        if pn not in PRODUCTS:
            return
        pr = PRODUCTS[pn]
        if get_stock_count(pn) == 0:
            bot.answer_callback_query(call.id, "❌ Out of stock!", show_alert=True)
            return
        add_to_cart(user_id, pn, pr)
        cart_count = len(get_cart(user_id))
        cart_total = get_cart_total(user_id)
        bot.answer_callback_query(call.id, f"✅ Added! 🛒 {cart_count} items | ₦{cart_total}", show_alert=True)
        return
    
    # Handle cart operations
    if data.startswith("rmcart_"):
        remove_from_cart(user_id, int(data.replace("rmcart_", "")))
        bot.answer_callback_query(call.id, "✅ Removed!")
        return
    if data.startswith("qtyadd_"):
        cursor.execute("UPDATE cart SET quantity=quantity+1 WHERE id=? AND user_id=?", (int(data.replace("qtyadd_", "")), user_id))
        conn.commit()
        bot.answer_callback_query(call.id, "✅ Added!")
        return
    if data.startswith("qtysub_"):
        cid = int(data.replace("qtysub_", ""))
        cursor.execute("SELECT quantity FROM cart WHERE id=? AND user_id=?", (cid, user_id))
        row = cursor.fetchone()
        if row and row[0] > 1:
            cursor.execute("UPDATE cart SET quantity=quantity-1 WHERE id=?", (cid,))
            conn.commit()
        else:
            remove_from_cart(user_id, cid)
        bot.answer_callback_query(call.id, "✅ Updated!")
        return
    if data == "clearcart":
        clear_cart(user_id)
        bot.answer_callback_query(call.id, "✅ Cart cleared!")
        return
    if data == "checkout":
        items = get_cart(user_id)
        if not items:
            bot.answer_callback_query(call.id, "Cart empty!", show_alert=True)
            return
        total = get_cart_total(user_id)
        if get_balance(user_id) < total:
            bot.answer_callback_query(call.id, f"❌ Need ₦{total}!", show_alert=True)
            return
        for item in items:
            if get_stock_count(item[1]) < item[3]:
                bot.answer_callback_query(call.id, f"❌ No stock for {item[1]}!", show_alert=True)
                return
        
        # AI LOADING ANIMATION FOR CART
        sent = bot.edit_message_text("🔄 **AI Processing Your Cart...**\n\n`[░░░░░░░░░░] 0%`", call.message.chat.id, call.message.message_id, parse_mode='Markdown')
        for i in range(1, 11):
            percent = i * 10
            bar = "█" * i + "░" * (10 - i)
            bot.edit_message_text(f"⚡ **AI Processing Your Cart...**\n\n`[{bar}] {percent}%`\n`🤖 AI Validating Stock...`", call.message.chat.id, call.message.message_id, parse_mode='Markdown')
            time.sleep(0.15)
        
        delivered = []
        total_spent = 0
        for item in items:
            for stock_item in get_items_from_stock(item[1], item[3]):
                mark_item_sold(stock_item[0])
                delivered.append(f"📦 {item[1]}: {stock_item[1]}")
                total_spent += item[2]
                update_stat("revenue", item[2])
                update_stat("orders", 1)
                log(user_id, "purchase", item[2], item[1])
        cursor.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (total_spent, user_id))
        conn.commit()
        clear_cart(user_id)
        new_bal = get_balance(user_id)
        
        receipt = f"""
╔══════════════════════════════════════╗
║         📄 PURCHASE RECEIPT          ║
╠══════════════════════════════════════╣
║  🆔 Order ID: #{random.randint(10000,99999)}
║  📅 Date: {time.strftime('%Y-%m-%d %H:%M')}
║  📦 Items:
"""
        for line in delivered:
            receipt += f"║     {line}\n"
        receipt += f"""║  💰 Total: ₦{total_spent}
║  💳 Balance After: ₦{new_bal}
║  ✅ Status: COMPLETED
╚══════════════════════════════════════╝
"""
        bot.edit_message_text(f"✅ **ORDER COMPLETE!**\n\n{receipt}", call.message.chat.id, call.message.message_id, parse_mode='Markdown')
        bot.answer_callback_query(call.id)
        return
    
    # Handle FAQ
    if data.startswith("faq_"):
        faq = data.replace("faq_", "")
        faqs = {
            "how": "📋 Buy uncreated Gmail → Create it → Instagram 'Forgot Password' → Enter Gmail → Reset password → Own both!",
            "fund": f"💳 Transfer to {BANK_NAME} ({ACCOUNT_NUMBER}) - {ACCOUNT_NAME} → Send name → Upload screenshot → Wait approval",
            "buy": "🛒 Fund wallet → Buy Products → Click BUY to purchase instantly → Confirm → Get email!",
            "cart": "🛒 Click ➕ Cart to add items → View Cart to manage → Adjust quantities → Checkout all at once!",
            "replace": "🔄 Replacement if Gmail taken or IG not linked. Report within 1 hour."
        }
        if faq in faqs:
            kb = InlineKeyboardMarkup()
            kb.add(InlineKeyboardButton("🔙 Back", callback_data="back_to_faq"))
            bot.edit_message_text(faqs[faq], call.message.chat.id, call.message.message_id, reply_markup=kb, parse_mode='Markdown')
        bot.answer_callback_query(call.id)
        return
    
    if data == "back_to_faq":
        k = InlineKeyboardMarkup(row_width=1)
        k.add(InlineKeyboardButton("📋 How It Works", callback_data="faq_how"))
        k.add(InlineKeyboardButton("💳 How to Fund", callback_data="faq_fund"))
        k.add(InlineKeyboardButton("🛒 How to Buy", callback_data="faq_buy"))
        k.add(InlineKeyboardButton("🛒 Using Cart", callback_data="faq_cart"))
        k.add(InlineKeyboardButton("🔄 Replacements", callback_data="faq_replace"))
        bot.edit_message_text("📋 **HELP & FAQ**", call.message.chat.id, call.message.message_id, reply_markup=k, parse_mode='Markdown')
        bot.answer_callback_query(call.id)
        return
    
    # Handle block/unblock
    if data == "block_menu":
        bot.send_message(call.message.chat.id, "🚫 Enter User ID to block:")
        bot.register_next_step_handler(call.message, process_block_user)
        bot.answer_callback_query(call.id)
        return
    if data == "unblock_menu":
        bot.send_message(call.message.chat.id, "✅ Enter User ID to unblock:")
        bot.register_next_step_handler(call.message, process_unblock_user)
        bot.answer_callback_query(call.id)
        return
    if data == "blocked_list":
        if not blocked_users:
            bot.edit_message_text("✅ No blocked users!", call.message.chat.id, call.message.message_id)
        else:
            msg = "🚫 **BLOCKED**\n\n"
            for uid in blocked_users:
                msg += f"🆔 {uid}\n"
            bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, parse_mode='Markdown')
        bot.answer_callback_query(call.id)
        return
    
    # Handle clear stock
    if data.startswith("clearstock_"):
        if data == "clearstock_all":
            clear_all_stock()
            bot.answer_callback_query(call.id, "✅ All stock deleted!", show_alert=True)
            bot.edit_message_text("✅ All stock deleted!", call.message.chat.id, call.message.message_id)
        elif data == "clearstock_cancel":
            bot.edit_message_text("❌ Cancelled.", call.message.chat.id, call.message.message_id)
        else:
            pn = data.replace("clearstock_", "")
            if pn in PRODUCTS:
                count = get_stock_count(pn)
                clear_product_stock(pn)
                bot.answer_callback_query(call.id, f"✅ {pn} cleared! ({count} items)", show_alert=True)
                bot.edit_message_text(f"✅ {pn} cleared! ({count} items)", call.message.chat.id, call.message.message_id)
        bot.answer_callback_query(call.id)
        return
    
    # Handle extract stock
    if data.startswith("extract_"):
        if data == "extract_all":
            all_emails = []
            for name in PRODUCTS:
                all_emails.extend(extract_stock(name))
            if not all_emails:
                bot.answer_callback_query(call.id, "❌ No stock!", show_alert=True)
                bot.edit_message_text("❌ No stock!", call.message.chat.id, call.message.message_id)
                return
            content = "\n".join(all_emails)
            with open("all_stock.txt", "w") as f:
                f.write(content)
            with open("all_stock.txt", "rb") as f:
                bot.send_document(ADMIN_ID, f, caption=f"📤 All Stock\n📦 {len(all_emails)} items")
            os.remove("all_stock.txt")
            bot.answer_callback_query(call.id, f"✅ Exported {len(all_emails)} items!", show_alert=True)
            bot.edit_message_text(f"✅ Exported {len(all_emails)} items!", call.message.chat.id, call.message.message_id)
        else:
            pn = data.replace("extract_", "")
            if pn in PRODUCTS:
                emails = extract_stock(pn)
                if not emails:
                    bot.answer_callback_query(call.id, "❌ No stock!", show_alert=True)
                    bot.edit_message_text("❌ No stock!", call.message.chat.id, call.message.message_id)
                    return
                content = "\n".join(emails)
                filename = f"{pn.replace(' ','_').replace('(','').replace(')','')}.txt"
                with open(filename, "w") as f:
                    f.write(content)
                with open(filename, "rb") as f:
                    bot.send_document(ADMIN_ID, f, caption=f"📤 {pn}\n📦 {len(emails)} items")
                os.remove(filename)
                bot.answer_callback_query(call.id, f"✅ Exported {pn}: {len(emails)} items!", show_alert=True)
                bot.edit_message_text(f"✅ Exported {pn}: {len(emails)} items!", call.message.chat.id, call.message.message_id)
        bot.answer_callback_query(call.id)
        return
    
    # Handle restock
    if data.startswith("restock_"):
        pn = data.replace("restock_", "")
        if pn in PRODUCTS:
            bot.send_message(call.message.chat.id, f"📦 RESTOCK: {pn}\n\nSend .txt file with emails:")
            bot.register_next_step_handler(call.message, process_restock_file, pn)
        bot.answer_callback_query(call.id)
        return
    
    if data == "back_to_admin":
        bot.edit_message_text("👑 **ADMIN PANEL**", call.message.chat.id, call.message.message_id, reply_markup=get_admin_keyboard(), parse_mode='Markdown')
        bot.answer_callback_query(call.id)
        return
    
    # Handle reports
    if data.startswith("report_"):
        it = data.replace("report_", "")
        if it in ["taken", "notlinked", "payment", "other"]:
            prompts = {
                "taken": "📧 Gmail Already Taken",
                "notlinked": "📷 Instagram Not Linked",
                "payment": "💳 Payment Issue",
                "other": "❓ Other Issue"
            }
            kb = InlineKeyboardMarkup()
            kb.add(InlineKeyboardButton("📝 SUBMIT REPORT", callback_data=f"report_submit_{it}"))
            kb.add(InlineKeyboardButton("❌ Cancel", callback_data="report_cancel"))
            bot.edit_message_text(f"📝 **{prompts.get(it)}**\n\nSend description then click Submit.", call.message.chat.id, call.message.message_id, reply_markup=kb, parse_mode='Markdown')
        bot.answer_callback_query(call.id)
        return
    
    if data.startswith("report_submit_"):
        it = data.replace("report_submit_", "")
        bot.send_message(call.message.chat.id, "📝 Send your description:")
        bot.register_next_step_handler(call.message, process_report_submit, it)
        bot.answer_callback_query(call.id)
        return
    
    if data == "report_cancel":
        bot.edit_message_text("❌ Report cancelled.", call.message.chat.id, call.message.message_id)
        bot.answer_callback_query(call.id)
        return
    
    # Handle resolve report
    if data.startswith("resolve_"):
        rid = int(data.replace("resolve_", ""))
        cursor.execute("UPDATE reports SET status='resolved' WHERE id=?", (rid,))
        conn.commit()
        cursor.execute("SELECT user_id FROM reports WHERE id=?", (rid,))
        row = cursor.fetchone()
        if row:
            try:
                bot.send_message(row[0], f"✅ Your report #{rid} has been resolved!")
            except:
                pass
        bot.answer_callback_query(call.id, f"✅ Report #{rid} resolved!", show_alert=True)
        bot.edit_message_text(f"✅ Report #{rid} resolved.", call.message.chat.id, call.message.message_id)
        return
    
    # Handle reply report
    if data.startswith("reply_"):
        rid = int(data.replace("reply_", ""))
        bot.send_message(call.message.chat.id, f"💬 Reply to report #{rid}:\n\nSend your message:")
        bot.register_next_step_handler(call.message, process_reply_report, rid)
        bot.answer_callback_query(call.id)
        return
    
    # Handle add funds from report
    if data.startswith("addfund_"):
        uid = int(data.replace("addfund_", ""))
        bot.send_message(call.message.chat.id, f"💰 Amount for user {uid}:")
        bot.register_next_step_handler(call.message, process_addfund_from_report, uid)
        bot.answer_callback_query(call.id)
        return

def process_block_user(message):
    try:
        uid = int(message.text.strip())
        if uid in blocked_users:
            bot.send_message(message.chat.id, f"ℹ️ Already blocked.")
            return
        blocked_users.add(uid)
        bot.send_message(message.chat.id, f"🚫 User {uid} BLOCKED!")
        try:
            bot.send_message(uid, "🚫 You have been blocked!")
        except:
            pass
    except:
        bot.send_message(message.chat.id, "❌ Invalid ID!")

def process_unblock_user(message):
    try:
        uid = int(message.text.strip())
        if uid not in blocked_users:
            bot.send_message(message.chat.id, f"ℹ️ Not blocked.")
            return
        blocked_users.discard(uid)
        if uid in fraud_tracker:
            fraud_tracker[uid] = {"last": 0, "count": 0}
        bot.send_message(message.chat.id, f"✅ User {uid} UNBLOCKED!")
        try:
            bot.send_message(uid, "✅ You have been unblocked!")
        except:
            pass
    except:
        bot.send_message(message.chat.id, "❌ Invalid ID!")

def process_restock_file(message, pn):
    try:
        if not message.document:
            bot.send_message(message.chat.id, "❌ Please send a .txt file.")
            return
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        content = downloaded_file.decode('utf-8', errors='ignore')
        new = [l.strip() for l in content.split('\n') if l.strip() and '@' in l]
        if not new:
            bot.send_message(message.chat.id, "❌ No emails found!")
            return
        old = get_stock_count(pn)
        added = add_bulk_to_stock(pn, new)
        bot.send_message(message.chat.id, f"✅ Restocked!\n📦 {pn}\n📊 {old}→{get_stock_count(pn)} (+{added})")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Error: {str(e)}")

def process_report_submit(message, it):
    desc = message.text
    user_id = message.from_user.id
    issue_names = {
        "taken": "📧 Gmail Already Taken",
        "notlinked": "📷 Instagram Not Linked",
        "payment": "💳 Payment Issue",
        "other": "❓ Other Issue"
    }
    cursor.execute("INSERT INTO reports (user_id, issue_type, description) VALUES (?,?,?)", (user_id, it, desc[:500]))
    conn.commit()
    rid = cursor.lastrowid
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✅ Resolve", callback_data=f"resolve_{rid}"))
    kb.add(InlineKeyboardButton("💬 Reply", callback_data=f"reply_{rid}"))
    kb.add(InlineKeyboardButton("💰 Add Funds", callback_data=f"addfund_{user_id}"))
    
    try:
        bot.send_message(ADMIN_ID, f"📝 **NEW REPORT #{rid}**\n\n👤 {message.from_user.full_name}\n🆔 {user_id}\n🏷 {issue_names.get(it, it)}\n📄 {desc[:800]}", reply_markup=kb, parse_mode='Markdown')
    except:
        pass
    
    bot.send_message(message.chat.id, f"✅ **Report #{rid} Submitted!**")

def process_reply_report(message, rid):
    try:
        cursor.execute("SELECT user_id FROM reports WHERE id=?", (rid,))
        row = cursor.fetchone()
        if row:
            bot.send_message(row[0], f"📬 **Admin Response (#{rid})**\n\n{message.text}")
            cursor.execute("UPDATE reports SET admin_response=? WHERE id=?", (message.text[:500], rid))
            conn.commit()
            bot.send_message(message.chat.id, "✅ Reply sent!")
        else:
            bot.send_message(message.chat.id, "❌ Report not found!")
    except:
        bot.send_message(message.chat.id, "❌ Error!")

def process_addfund_from_report(message, uid):
    try:
        amt = int(message.text.strip())
        if amt <= 0:
            bot.send_message(message.chat.id, "❌ Positive amount")
            return
        add_user(uid)
        old_bal = get_balance(uid)
        cursor.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amt, uid))
        conn.commit()
        log(uid, "credit", amt, "admin_addfund")
        new_bal = get_balance(uid)
        bot.send_message(message.chat.id, f"✅ Added ₦{amt} to user {uid}\n💳 Previous: ₦{old_bal}\n💳 New: ₦{new_bal}")
        try:
            bot.send_message(uid, f"💰 Admin added ₦{amt}!\n💳 Balance: ₦{old_bal} → ₦{new_bal}")
        except:
            pass
    except:
        bot.send_message(message.chat.id, "❌ Invalid amount!")

# ================= HANDLE APPROVE/REJECT =================
@bot.callback_query_handler(func=lambda call: call.data.startswith("approve:") or call.data.startswith("reject:"))
def handle_approve_reject(call):
    data = call.data
    user_id = int(data.split(":")[1])
    
    if data.startswith("approve:"):
        if user_id not in pending_approvals:
            bot.answer_callback_query(call.id, "⚠️ Already processed!", show_alert=True)
            return
        bot.send_message(call.message.chat.id, f"💰 Amount for user {user_id}:")
        bot.register_next_step_handler(call.message, process_approve_amount, user_id)
        bot.answer_callback_query(call.id)
        return
    
    if data.startswith("reject:"):
        if user_id not in pending_approvals:
            bot.answer_callback_query(call.id, "❌ Not found!", show_alert=True)
            return
        info = pending_approvals[user_id]
        cursor.execute("UPDATE deposits SET status='rejected' WHERE ref=?", (info.get('ref'),))
        conn.commit()
        try:
            bot.send_message(user_id, "❌ **PAYMENT DECLINED**\n\nContact admin.", parse_mode='Markdown')
        except:
            pass
        pending_approvals.pop(user_id, None)
        bot.answer_callback_query(call.id, "✅ Rejected!", show_alert=True)
        bot.edit_message_text("✅ Rejected!", call.message.chat.id, call.message.message_id)
        return

def process_approve_amount(message, uid):
    try:
        amt = int(message.text.strip())
        if amt <= 0:
            bot.send_message(message.chat.id, "❌ Positive amount")
            return
        if uid not in pending_approvals:
            bot.send_message(message.chat.id, "⚠️ Already processed!")
            return
        info = pending_approvals[uid]
        old_bal = get_balance(uid)
        cursor.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amt, uid))
        conn.commit()
        cursor.execute("UPDATE deposits SET amount=?, status='approved' WHERE ref=?", (amt, info.get('ref')))
        conn.commit()
        new_bal = get_balance(uid)
        log(uid, "credit", amt, "deposit")
        try:
            bot.send_message(uid, f"✅ **PAYMENT APPROVED!**\n\n💰 Amount: ₦{amt}\n💳 Previous: ₦{old_bal}\n💳 New: ₦{new_bal}\n\nThank you! You can now purchase products.", parse_mode='Markdown')
        except:
            pass
        bot.send_message(message.chat.id, f"✅ Approved ₦{amt} for user {uid}\n💳 Previous: ₦{old_bal}\n💳 New: ₦{new_bal}")
        pending_approvals.pop(uid, None)
    except:
        bot.send_message(message.chat.id, "❌ Send valid number")

# ================= TEXT HANDLER =================
@bot.message_handler(func=lambda m: True)
def handle_text(message):
    user_id = message.from_user.id
    text = message.text
    
    # Auto-responder for support mode
    if user_support_mode.get(user_id):
        if text == "❌ Exit Support":
            user_support_mode.pop(user_id, None)
            start(message)
            return
        msg = text.lower()
        if "how" in msg or "work" in msg:
            r = "📋 Buy uncreated Gmail → Create it → Instagram 'Forgot Password' → Reset → Own both!"
        elif "cart" in msg:
            r = "🛒 Use '➕ Cart' to add items → View Cart to manage → Checkout all at once!"
        elif "create" in msg or "gmail" in msg:
            r = "🔧 Gmail.com → Create Account → Enter our address → Create password → Done!"
        elif "price" in msg or "cost" in msg:
            r = "💰 ₦1000-₦8500. Click '📦 Check Stock'."
        elif "pay" in msg or "fund" in msg:
            r = f"💳 Click '➕ Fund Wallet' → Transfer to {BANK_NAME} ({ACCOUNT_NUMBER}) → Send name → Upload screenshot."
        else:
            r = "🤖 Ask me anything!"
        bot.send_message(user_id, r)
        return
    
    # Auto-responder for normal messages
    if not user_support_mode.get(user_id):
        auto_reply = get_auto_reply(text)
        if auto_reply:
            bot.send_message(user_id, auto_reply)
            return
    
    # If no auto-reply, ignore
    if text not in ["💰 Wallet", "➕ Fund Wallet", "📦 Check Stock", "🧾 My History", "💳 My Deposits", "🛒 Buy Products", "🛒 My Cart", "🤖 Expert Support", "📝 Report Issue", "🤝 Refer & Earn", "📋 Help & FAQ", "📞 Contact", "👑 Admin Panel", "📊 Stats", "📥 Pending", "📝 Reports", "💰 Add Funds", "💸 Deduct Funds", "👤 View Balance", "📈 Sales", "📦 Restock", "📢 Broadcast", "💬 Message User", "🚫 Block/Unblock", "🗑 Clear Stock", "📤 Extract Stock", "🔄 User Menu", "❌ Exit Support"]:
        bot.send_message(user_id, "❌ Please use the buttons below.", reply_markup=get_main_keyboard(user_id))

# ================= MAIN =================
print("=" * 50)
print("✅ BOT RUNNING!")
print("🛒 BUY = Instant purchase | ➕ Cart = Add to cart")
print("💰 Approval shows Previous & New balance")
print("👤 /balance [id] - View user balance")
print("📞 Contact: WhatsApp", WHATSAPP_NUMBER)
print("=" * 50)

bot.infinity_polling(timeout=10, long_polling_timeout=10)
