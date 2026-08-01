import sqlite3
import time
import random
import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# ================= CONFIG =================
BOT_TOKEN = "8042789426:AAEKHcwcs12zw_rPltc6LhCBTSxISYIJ7TE"
ADMIN_ID = 7443685686
BOT_USERNAME = "Expensiveig_bot"

BANK_NAME = "OPAY"
ACCOUNT_NUMBER = "9167685658"
ACCOUNT_NAME = "MUHAMMED JAMIU HAMZA"

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

for k in ["revenue","orders"]:
    cursor.execute("INSERT OR IGNORE INTO stats (key,value) VALUES (?,0)", (k,))
conn.commit()

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

def update_stat(k,v):
    cursor.execute("UPDATE stats SET value=value+? WHERE key=?", (v,k))
    conn.commit()

def get_stat(k):
    cursor.execute("SELECT value FROM stats WHERE key=?", (k,))
    r = cursor.fetchone()
    return r[0] if r else 0

def log(uid,t,amt,d):
    cursor.execute("INSERT INTO transactions (user_id,type,amount,details) VALUES (?,?,?,?)",(uid,t,amt,d))
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
    if cursor.fetchone(): return False
    cursor.execute("INSERT INTO stock (product_name, email) VALUES (?,?)", (product_name, email))
    conn.commit()
    return True

def add_bulk_to_stock(product_name, emails):
    added = 0
    for email in emails:
        if add_to_stock(product_name, email): added += 1
    return added

def clear_all_stock():
    cursor.execute("DELETE FROM stock"); conn.commit()

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

# ================= KEYBOARDS =================
def get_main_keyboard(user_id):
    if user_id == ADMIN_ID:
        return get_admin_keyboard()
    else:
        return get_user_keyboard()

def get_user_keyboard():
    menu = [
        ["💰 Wallet", "➕ Fund Wallet"],
        ["📦 Check Stock", "🧾 My History"],
        ["💳 My Deposits", "🛒 Buy Products"],
        ["🤖 Expert Support", "📝 Report Issue"],
        ["🤝 Refer & Earn", "🛒 My Cart"],
        ["📋 Help & FAQ"]
    ]
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

# ================= START =================
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    add_user(user_id)
    user_support_mode.pop(user_id, None)
    
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
                    try: 
                        bot.send_message(referrer_id, f"🎉 New referral! +₦{REFERRAL_BONUS}")
                    except: 
                        pass
        except: 
            pass

    cart_count = len(get_cart(user_id))
    cart_text = f" | 🛒 {cart_count} items" if cart_count > 0 else ""

    bot.send_message(
        user_id,
        f"🛒 **Store Bot**{cart_text}\n\n📧 Buy uncreated Gmail → Create → Recover IG\n🤝 Earn ₦{REFERRAL_BONUS}/referral!",
        reply_markup=get_main_keyboard(user_id),
        parse_mode='Markdown'
    )

# ================= ADMIN PANEL =================
@bot.message_handler(func=lambda m: m.text == "👑 Admin Panel")
def admin_panel(message):
    if message.from_user.id != ADMIN_ID: return
    bot.send_message(message.chat.id, "👑 **ADMIN PANEL**", reply_markup=get_admin_keyboard(), parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text == "🔄 User Menu")
def switch_to_user_menu(message):
    if message.from_user.id != ADMIN_ID: return
    menu = [["💰 Wallet", "➕ Fund Wallet"], ["📦 Check Stock", "🧾 My History"], ["💳 My Deposits", "🛒 Buy Products"], ["🤖 Expert Support", "📝 Report Issue"], ["🤝 Refer & Earn", "🛒 My Cart"], ["📋 Help & FAQ"], ["👑 Admin Panel"]]
    bot.send_message(message.chat.id, "🔄 Switched to User Menu", reply_markup=ReplyKeyboardMarkup(menu, resize_keyboard=True))

# ================= VIEW USER BALANCE (ADMIN) =================
@bot.message_handler(func=lambda m: m.text == "👤 View Balance")
def view_balance_start(message):
    if message.from_user.id != ADMIN_ID: return
    bot.send_message(message.chat.id, "👤 **VIEW USER BALANCE**\n\nEnter the USER ID:\n/cancel to abort")
    bot.register_next_step_handler(message, process_view_balance)

def process_view_balance(message):
    try:
        uid = int(message.text.strip())
        bal = get_balance(uid)
        try:
            target = bot.get_chat(uid)
            name = target.first_name
        except:
            name = f"User {uid}"
        bot.send_message(message.chat.id, f"👤 **{name}**\n🆔 ID: {uid}\n💰 Balance: ₦{bal}")
    except:
        bot.send_message(message.chat.id, "❌ Invalid ID. Use: /balance [user_id]")

@bot.message_handler(commands=['balance'])
def view_balance_command(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.send_message(message.chat.id, "Usage: /balance [user_id]")
            return
        uid = int(parts[1])
        bal = get_balance(uid)
        try:
            target = bot.get_chat(uid)
            name = target.first_name
        except:
            name = f"User {uid}"
        bot.send_message(message.chat.id, f"👤 **{name}**\n🆔 ID: {uid}\n💰 Balance: ₦{bal}")
    except:
        bot.send_message(message.chat.id, "❌ Invalid ID. Use: /balance [user_id]")

# ================= BLOCK/UNBLOCK =================
@bot.message_handler(func=lambda m: m.text == "🚫 Block/Unblock")
def block_unblock_menu(message):
    if message.from_user.id != ADMIN_ID: return
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🚫 Block User", callback_data="block_menu"))
    kb.add(InlineKeyboardButton("✅ Unblock User", callback_data="unblock_menu"))
    kb.add(InlineKeyboardButton("📋 View Blocked", callback_data="blocked_list"))
    bot.send_message(message.chat.id, "🚫 **BLOCK/UNBLOCK**", reply_markup=kb, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data in ["block_menu", "unblock_menu", "blocked_list"])
def block_unblock_callback(call):
    q = call
    user_id = q.from_user.id
    if user_id != ADMIN_ID: return
    d = q.data
    if d == "block_menu":
        bot.send_message(q.message.chat.id, "🚫 Enter User ID to block:\n/cancel")
        bot.register_next_step_handler(q.message, process_block_user)
    elif d == "unblock_menu":
        bot.send_message(q.message.chat.id, "✅ Enter User ID to unblock:\n/cancel")
        bot.register_next_step_handler(q.message, process_unblock_user)
    elif d == "blocked_list":
        if not blocked_users:
            bot.edit_message_text("✅ No blocked users!", q.message.chat.id, q.message.message_id)
        else:
            msg = "🚫 **BLOCKED**\n\n"
            for uid in blocked_users:
                msg += f"🆔 {uid}\n"
            bot.edit_message_text(msg, q.message.chat.id, q.message.message_id, parse_mode='Markdown')
    bot.answer_callback_query(q.id)

def process_block_user(message):
    try:
        uid = int(message.text.strip())
        if uid in blocked_users:
            bot.send_message(message.chat.id, f"ℹ️ Already blocked.")
            return
        blocked_users.add(uid)
        bot.send_message(message.chat.id, f"🚫 User {uid} BLOCKED!")
        try:
            bot.send_message(uid, "🚫 You have been blocked from submitting payment proofs.")
        except:
            pass
    except:
        bot.send_message(message.chat.id, "❌ Invalid ID")

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
        bot.send_message(message.chat.id, "❌ Invalid ID")

@bot.message_handler(commands=['block'])
def block_user_command(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.send_message(message.chat.id, "/block [user_id]")
            return
        uid = int(parts[1])
        if uid in blocked_users:
            bot.send_message(message.chat.id, f"ℹ️ Already blocked.")
            return
        blocked_users.add(uid)
        bot.send_message(message.chat.id, f"🚫 User {uid} BLOCKED!")
        try:
            bot.send_message(uid, "🚫 You have been blocked from submitting payment proofs.")
        except:
            pass
    except:
        bot.send_message(message.chat.id, "❌ Invalid ID")

@bot.message_handler(commands=['unblock'])
def unblock_command(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        parts = message.text.split()
        if len(parts) < 1:
            bot.send_message(message.chat.id, "/unblock [user_id]")
            return
        uid = int(parts[1])
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
        bot.send_message(message.chat.id, "❌ Invalid ID")

@bot.message_handler(commands=['blockedlist'])
def blocked_list_command(message):
    if message.from_user.id != ADMIN_ID: return
    if not blocked_users:
        bot.send_message(message.chat.id, "✅ No blocked users!")
        return
    msg = "🚫 **BLOCKED USERS**\n\n"
    for uid in blocked_users:
        msg += f"🆔 {uid}\n"
    bot.send_message(message.chat.id, msg, parse_mode='Markdown')

# ================= WALLET / FUND =================
@bot.message_handler(func=lambda m: m.text == "💰 Wallet")
def wallet(message):
    bot.send_message(message.chat.id, f"💰 Balance: ₦{get_balance(message.from_user.id)}")

@bot.message_handler(func=lambda m: m.text == "➕ Fund Wallet")
def fund(message):
    user_id = message.from_user.id
    ref = generate_ref()
    user_data[user_id] = {"fund_ref": ref}
    user_data[user_id]["awaiting_name"] = True
    bot.send_message(
        message.chat.id,
        f"💳 **FUND YOUR WALLET**\n\n🏦 {BANK_NAME}\n🔢 {ACCOUNT_NUMBER}\n👤 {ACCOUNT_NAME}\n\n🆔 {ref}\n\n📝 Send SENDER NAME first.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ I've Made Payment", callback_data=f"pay:{ref}")]])
    )
    bot.register_next_step_handler(message, process_fund_name, ref)

def process_fund_name(message, ref):
    user_id = message.from_user.id
    sender_name = message.text.strip()
    user_data[user_id]["sender_name"] = sender_name
    user_data[user_id]["ref"] = ref
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
    bot.send_photo(
        ADMIN_ID,
        photo_id,
        caption=f"💳 **NEW DEPOSIT**\n\n👤 {message.from_user.full_name}\n🆔 {user_id}\n🏦 {sender_name}\n🔢 {ref}",
        reply_markup=kb,
        parse_mode='Markdown'
    )
    bot.send_message(user_id, "✅ Submitted! Waiting for approval.")

@bot.callback_query_handler(func=lambda call: call.data.startswith("pay:"))
def pay_callback(call):
    ref = call.data.split(":")[1]
    bot.send_message(call.from_user.id, f"💳 REF: {ref}\n\n📝 Send SENDER NAME.")
    bot.register_next_step_handler(call.message, process_fund_name, ref)
    bot.answer_callback_query(call.id)

# ================= STOCK / HISTORY / DEPOSITS =================
@bot.message_handler(func=lambda m: m.text == "📦 Check Stock")
def user_stock(message):
    msg = "📦 **STOCK**\n\n"
    stock = get_all_stock()
    for name in PRODUCTS:
        msg += f"{'✅' if stock[name] > 0 else '❌'} {name}: {stock[name]} available\n"
    bot.send_message(message.chat.id, msg, parse_mode='Markdown')

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
        emoji = "✅" if s=="approved" else "⏳" if s=="pending" else "❌"
        msg += f"{emoji} {r}: {'₦'+str(a) if a else '...'} ({s})\n"
        if dr:
            msg += f"   📋 {dr}\n"
    bot.send_message(message.chat.id, msg, parse_mode='Markdown')

# ================= BUY PRODUCTS =================
@bot.message_handler(func=lambda m: m.text == "🛒 Buy Products")
def buy_products_menu(message):
    k = InlineKeyboardMarkup()
    k.add(InlineKeyboardButton("📧 Small (0-100)", callback_data="cat_small"))
    k.add(InlineKeyboardButton("📧 Medium (200-500)", callback_data="cat_medium"))
    k.add(InlineKeyboardButton("📧 Large (600-1000)", callback_data="cat_large"))
    k.add(InlineKeyboardButton("📦 All", callback_data="cat_all"))
    bot.send_message(message.chat.id, "🛒 **BUY PRODUCTS**\n\nSelect category to buy instantly or use Cart for bulk.", reply_markup=k, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith("cat_"))
def product_category_callback(call):
    q = call
    cat = q.data.replace("cat_","")
    if cat=="small":
        p = {k:v for k,v in PRODUCTS.items() if v<=3000}
        t = "SMALL"
    elif cat=="medium":
        p = {k:v for k,v in PRODUCTS.items() if 4000<=v<=6000}
        t = "MEDIUM"
    elif cat=="large":
        p = {k:v for k,v in PRODUCTS.items() if v>=6500}
        t = "LARGE"
    else:
        p = PRODUCTS
        t = "ALL"
    msg = f"**{t}**\n\n🛒 Click to BUY NOW | 🛒➕ Click to ADD TO CART\n\n"
    kb = InlineKeyboardMarkup()
    for n,pr in p.items():
        s = get_stock_count(n)
        msg += f"{'✅' if s>0 else '❌'} {n}: {s} available - ₦{pr}\n"
        if s>0:
            kb.add(InlineKeyboardButton(f"🛒 BUY {n}", callback_data=f"buy_{n}"))
            kb.add(InlineKeyboardButton(f"➕ Cart", callback_data=f"addcart_{n}"))
    kb.add(InlineKeyboardButton("🔙 Back to Categories", callback_data="back_to_categories"))
    bot.edit_message_text(msg, q.message.chat.id, q.message.message_id, reply_markup=kb, parse_mode='Markdown')
    bot.answer_callback_query(q.id)

@bot.callback_query_handler(func=lambda call: call.data == "back_to_categories")
def back_to_categories(call):
    q = call
    k = InlineKeyboardMarkup()
    k.add(InlineKeyboardButton("📧 Small (0-100)", callback_data="cat_small"))
    k.add(InlineKeyboardButton("📧 Medium (200-500)", callback_data="cat_medium"))
    k.add(InlineKeyboardButton("📧 Large (600-1000)", callback_data="cat_large"))
    k.add(InlineKeyboardButton("📦 All", callback_data="cat_all"))
    bot.edit_message_text("🛒 **BUY PRODUCTS**\n\nSelect category:", q.message.chat.id, q.message.message_id, reply_markup=k, parse_mode='Markdown')
    bot.answer_callback_query(q.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_"))
def buy_product_callback(call):
    q = call
    u = q.from_user
    pn = q.data.replace("buy_","")
    if pn not in PRODUCTS: return
    pr = PRODUCTS[pn]
    if get_stock_count(pn)==0:
        bot.answer_callback_query(q.id, "❌ Out of stock!", show_alert=True)
        return
    bal = get_balance(u.id)
    if bal < pr:
        bot.answer_callback_query(q.id, f"❌ Insufficient funds! Need ₦{pr}, you have ₦{bal}", show_alert=True)
        return
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✅ Confirm Purchase", callback_data=f"confirm_{pn}"))
    kb.add(InlineKeyboardButton("❌ Cancel", callback_data="back_to_categories"))
    bot.edit_message_text(
        f"🛒 **CONFIRM**\n\n📦 {pn}\n💰 Price: ₦{pr}\n💳 Balance: ₦{bal}\n💳 After: ₦{bal-pr}",
        q.message.chat.id,
        q.message.message_id,
        reply_markup=kb,
        parse_mode='Markdown'
    )
    bot.answer_callback_query(q.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_"))
def confirm_purchase_callback(call):
    q = call
    u = q.from_user
    pn = q.data.replace("confirm_","")
    if pn not in PRODUCTS: return
    pr = PRODUCTS[pn]
    if get_balance(u.id) < pr:
        bot.answer_callback_query(q.id, "❌ Insufficient!", show_alert=True)
        return
    item = get_item_from_stock(pn)
    if not item:
        bot.answer_callback_query(q.id, "❌ Out of stock!", show_alert=True)
        return
    item_id, email = item
    
    # Processing animation
    sent = bot.edit_message_text(
        f"⏳ **Processing your order...**\n\n📦 {pn}\n`[░░░░░░░░░░] 0%`",
        q.message.chat.id,
        q.message.message_id,
        parse_mode='Markdown'
    )
    for i in range(1, 11):
        percent = i * 10
        bar = "█" * i + "░" * (10 - i)
        try:
            bot.edit_message_text(
                f"⏳ **Processing your order...**\n\n📦 {pn}\n`[{bar}] {percent}%`",
                q.message.chat.id,
                q.message.message_id,
                parse_mode='Markdown'
            )
            time.sleep(0.15)
        except:
            pass
    
    mark_item_sold(item_id)
    cursor.execute("UPDATE users SET balance=balance-? WHERE user_id=?",(pr,u.id))
    conn.commit()
    update_stat("revenue",pr)
    update_stat("orders",1)
    log(u.id,"purchase",pr,pn)
    new_bal = get_balance(u.id)
    
    bot.edit_message_text(
        f"✅ **PURCHASED!**\n\n📦 {pn}\n💰 ₦{pr}\n📧 `{email}`\n\n💳 Balance: ₦{new_bal}",
        q.message.chat.id,
        q.message.message_id,
        parse_mode='Markdown'
    )
    bot.answer_callback_query(q.id, "✅ Purchase complete!", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data.startswith("addcart_"))
def add_to_cart_callback(call):
    q = call
    u = q.from_user
    pn = q.data.replace("addcart_","")
    if pn not in PRODUCTS: return
    pr = PRODUCTS[pn]
    if get_stock_count(pn)==0:
        bot.answer_callback_query(q.id, "❌ Out of stock!", show_alert=True)
        return
    add_to_cart(u.id, pn, pr)
    cart_count = len(get_cart(u.id))
    cart_total = get_cart_total(u.id)
    bot.answer_callback_query(q.id, f"✅ Added! 🛒 {cart_count} items | ₦{cart_total}", show_alert=True)

# ================= CART =================
@bot.message_handler(func=lambda m: m.text == "🛒 My Cart")
def view_cart(message):
    u = message.from_user
    items = get_cart(u.id)
    if not items:
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("🛒 Browse Products", callback_data="cat_all"))
        bot.send_message(message.chat.id, "🛒 Cart empty!", reply_markup=kb)
        return
    total = get_cart_total(u.id)
    bal = get_balance(u.id)
    msg = f"🛒 **YOUR CART**\n\n"
    kb = InlineKeyboardMarkup()
    for item in items:
        cart_id, pn, pr, qty = item
        msg += f"📦 {pn}\n   Qty: {qty} × ₦{pr} = ₦{pr*qty}\n\n"
        kb.add(InlineKeyboardButton(f"➕", callback_data=f"qtyadd_{cart_id}"))
        kb.add(InlineKeyboardButton(f"➖", callback_data=f"qtysub_{cart_id}"))
        kb.add(InlineKeyboardButton(f"❌", callback_data=f"rmcart_{cart_id}"))
    msg += f"━━━━━━━━━━━━━━━\n💰 **Total: ₦{total}**\n💳 Balance: ₦{bal}\n"
    if total > 0:
        if bal >= total:
            msg += f"\n✅ You have enough funds!"
            kb.add(InlineKeyboardButton("✅ CHECKOUT NOW", callback_data="checkout"))
        else:
            msg += f"\n⚠️ Insufficient! Need ₦{total - bal} more."
    kb.add(InlineKeyboardButton("🗑 Clear Cart", callback_data="clearcart"))
    kb.add(InlineKeyboardButton("🛒 Continue Shopping", callback_data="cat_all"))
    bot.send_message(message.chat.id, msg, reply_markup=kb, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data in ["addcart", "rmcart", "qtyadd", "qtysub", "clearcart", "checkout"])
def cart_callback(call):
    q = call
    u = q.from_user
    d = q.data
    
    if d == "addcart":
        # handled by add_to_cart_callback
        pass
    elif d.startswith("rmcart_"):
        remove_from_cart(u.id, int(d.replace("rmcart_","")))
        view_cart(q.message)
        bot.answer_callback_query(q.id, "✅ Removed!")
    elif d.startswith("qtyadd_"):
        cursor.execute("UPDATE cart SET quantity=quantity+1 WHERE id=? AND user_id=?", (int(d.replace("qtyadd_","")), u.id))
        conn.commit()
        view_cart(q.message)
        bot.answer_callback_query(q.id, "✅ Added!")
    elif d.startswith("qtysub_"):
        cid = int(d.replace("qtysub_",""))
        cursor.execute("SELECT quantity FROM cart WHERE id=? AND user_id=?", (cid, u.id))
        row = cursor.fetchone()
        if row and row[0] > 1:
            cursor.execute("UPDATE cart SET quantity=quantity-1 WHERE id=?", (cid,))
            conn.commit()
        else:
            remove_from_cart(u.id, cid)
        view_cart(q.message)
        bot.answer_callback_query(q.id, "✅ Updated!")
    elif d == "clearcart":
        clear_cart(u.id)
        view_cart(q.message)
        bot.answer_callback_query(q.id, "✅ Cart cleared!")
    elif d == "checkout":
        checkout_cart(q)

def checkout_cart(call):
    q = call
    u = q.from_user
    items = get_cart(u.id)
    if not items:
        bot.answer_callback_query(q.id, "Cart empty!", show_alert=True)
        return
    total = get_cart_total(u.id)
    if get_balance(u.id) < total:
        bot.answer_callback_query(q.id, f"❌ Need ₦{total}!", show_alert=True)
        return
    for item in items:
        if get_stock_count(item[1]) < item[3]:
            bot.edit_message_text(f"❌ Not enough stock for {item[1]}!", q.message.chat.id, q.message.message_id)
            return
    
    sent = bot.edit_message_text(
        f"⏳ **Processing your order...**\n\n`[░░░░░░░░░░] 0%`",
        q.message.chat.id,
        q.message.message_id,
        parse_mode='Markdown'
    )
    for i in range(1, 11):
        percent = i * 10
        bar = "█" * i + "░" * (10 - i)
        try:
            bot.edit_message_text(
                f"⏳ **Processing your order...**\n\n`[{bar}] {percent}%`",
                q.message.chat.id,
                q.message.message_id,
                parse_mode='Markdown'
            )
            time.sleep(0.15)
        except:
            pass
    
    delivered = []
    total_spent = 0
    for item in items:
        for stock_item in get_items_from_stock(item[1], item[3]):
            mark_item_sold(stock_item[0])
            delivered.append(f"📦 {item[1]}: {stock_item[1]}")
            total_spent += item[2]
            update_stat("revenue", item[2])
            update_stat("orders", 1)
            log(u.id, "purchase", item[2], item[1])
    cursor.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (total_spent, u.id))
    conn.commit()
    clear_cart(u.id)
    new_bal = get_balance(u.id)
    
    bot.edit_message_text(
        f"✅ **ORDER COMPLETE!**\n\n" + "\n".join(delivered) + f"\n\n💰 Total: ₦{total_spent}\n💳 Remaining: ₦{new_bal}",
        q.message.chat.id,
        q.message.message_id,
        parse_mode='Markdown'
    )
    bot.answer_callback_query(q.id, "✅ Order complete!", show_alert=True)

# ================= SUPPORT / REPORT / FAQ / REFER =================
@bot.message_handler(func=lambda m: m.text == "🤖 Expert Support")
def expert_support(message):
    user_support_mode[message.from_user.id] = True
    bot.send_message(
        message.chat.id,
        "🤖 **SUPPORT**\n\nAsk me anything!\nType 'exit' to leave.",
        reply_markup=ReplyKeyboardMarkup([["❌ Exit Support"]], resize_keyboard=True),
        parse_mode='Markdown'
    )

@bot.message_handler(func=lambda m: m.text == "❌ Exit Support")
def exit_support(message):
    user_support_mode.pop(message.from_user.id, None)
    start(message)

@bot.message_handler(func=lambda m: m.text == "📝 Report Issue")
def report_issue(message):
    k = InlineKeyboardMarkup()
    k.add(InlineKeyboardButton("📧 Gmail Taken", callback_data="report_taken"))
    k.add(InlineKeyboardButton("📷 IG Not Linked", callback_data="report_notlinked"))
    k.add(InlineKeyboardButton("💳 Payment", callback_data="report_payment"))
    k.add(InlineKeyboardButton("❓ Other", callback_data="report_other"))
    bot.send_message(message.chat.id, "📝 **FILE A REPORT**\n\nSelect type:", reply_markup=k, parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text == "🤝 Refer & Earn")
def refer_earn_menu(message):
    bot.send_message(
        message.chat.id,
        f"🤝 **REFER & EARN ₦{REFERRAL_BONUS}**\n\n🔗 `{generate_referral_link(message.from_user.id)}`",
        parse_mode='Markdown'
    )

@bot.message_handler(func=lambda m: m.text == "📋 Help & FAQ")
def help_faq(message):
    k = InlineKeyboardMarkup()
    k.add(InlineKeyboardButton("📋 How It Works", callback_data="faq_how"))
    k.add(InlineKeyboardButton("💳 How to Fund", callback_data="faq_fund"))
    k.add(InlineKeyboardButton("🛒 How to Buy", callback_data="faq_buy"))
    k.add(InlineKeyboardButton("🛒 Using Cart", callback_data="faq_cart"))
    k.add(InlineKeyboardButton("🔄 Replacements", callback_data="faq_replace"))
    bot.send_message(message.chat.id, "📋 **HELP & FAQ**", reply_markup=k, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith("faq_"))
def faq_callback(call):
    q = call
    faq = q.data.replace("faq_", "")
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
        bot.edit_message_text(faqs[faq], q.message.chat.id, q.message.message_id, reply_markup=kb, parse_mode='Markdown')
    bot.answer_callback_query(q.id)

@bot.callback_query_handler(func=lambda call: call.data == "back_to_faq")
def back_to_faq(call):
    q = call
    k = InlineKeyboardMarkup()
    k.add(InlineKeyboardButton("📋 How It Works", callback_data="faq_how"))
    k.add(InlineKeyboardButton("💳 How to Fund", callback_data="faq_fund"))
    k.add(InlineKeyboardButton("🛒 How to Buy", callback_data="faq_buy"))
    k.add(InlineKeyboardButton("🛒 Using Cart", callback_data="faq_cart"))
    k.add(InlineKeyboardButton("🔄 Replacements", callback_data="faq_replace"))
    bot.edit_message_text("📋 **HELP & FAQ**", q.message.chat.id, q.message.message_id, reply_markup=k, parse_mode='Markdown')
    bot.answer_callback_query(q.id)

# ================= ADMIN COMMANDS =================
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
    for uid,data in pending_approvals.items():
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("✅ Approve", callback_data=f"approve:{uid}"))
        kb.add(InlineKeyboardButton("❌ Reject", callback_data=f"reject:{uid}"))
        try:
            bot.send_photo(
                ADMIN_ID,
                data["photo_id"],
                caption=f"💳 {uid}\n👤 {data.get('full_name','?')}\n🏦 {data['sender_name']}\n🔢 {data['ref']}",
                reply_markup=kb,
                parse_mode='Markdown'
            )
        except:
            pass

@bot.message_handler(func=lambda m: m.text == "📝 Reports")
def view_reports(message):
    if message.from_user.id != ADMIN_ID: return
    cursor.execute("SELECT id, user_id, issue_type, description FROM reports WHERE status='open' ORDER BY id DESC LIMIT 10")
    rows = cursor.fetchall()
    if not rows:
        bot.send_message(message.chat.id, "✅ No reports")
        return
    for rid,uid,it,desc in rows:
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("✅ Resolve", callback_data=f"resolve_{rid}"))
        kb.add(InlineKeyboardButton("💬 Reply", callback_data=f"reply_{rid}"))
        kb.add(InlineKeyboardButton("💰 Add", callback_data=f"addfund_{uid}"))
        bot.send_message(
            message.chat.id,
            f"📝 #{rid} | 👤 {uid} | 🏷 {it}\n📄 {desc[:200]}",
            reply_markup=kb,
            parse_mode='Markdown'
        )

@bot.message_handler(func=lambda m: m.text == "💰 Add Funds")
def admin_addfund_start(message):
    if message.from_user.id != ADMIN_ID: return
    bot.send_message(message.chat.id, "💰 **ADD FUNDS**\n\nEnter the USER ID:\n/cancel to abort")
    bot.register_next_step_handler(message, process_admin_addfund_user)

def process_admin_addfund_user(message):
    if message.text == "/cancel":
        bot.send_message(message.chat.id, "❌ Cancelled")
        return
    try:
        uid = int(message.text.strip())
        bot.send_message(message.chat.id, f"👤 User: {uid}\n💳 Balance: ₦{get_balance(uid)}\n\nEnter AMOUNT to add:")
        bot.register_next_step_handler(message, process_admin_addfund_amount, uid)
    except:
        bot.send_message(message.chat.id, "❌ Invalid ID")

def process_admin_addfund_amount(message, uid):
    try:
        amt = int(message.text.strip())
        if amt <= 0:
            bot.send_message(message.chat.id, "❌ Positive amount")
            return
        add_user(uid)
        old_bal = get_balance(uid)
        cursor.execute("UPDATE users SET balance=balance+? WHERE user_id=?",(amt,uid))
        conn.commit()
        log(uid,"credit",amt,"admin_addfund")
        new_bal = get_balance(uid)
        bot.send_message(message.chat.id, f"✅ Added ₦{amt} to {uid}\n💳 Previous: ₦{old_bal}\n💳 New: ₦{new_bal}")
        try:
            bot.send_message(uid, f"💰 Admin added ₦{amt}!\n💳 Balance: ₦{old_bal} → ₦{new_bal}")
        except:
            pass
    except:
        bot.send_message(message.chat.id, "❌ Send valid number")

@bot.message_handler(func=lambda m: m.text == "💸 Deduct Funds")
def admin_deductfund_start(message):
    if message.from_user.id != ADMIN_ID: return
    bot.send_message(message.chat.id, "💸 **DEDUCT FUNDS**\n\nEnter the USER ID:\n/cancel to abort")
    bot.register_next_step_handler(message, process_admin_deductfund_user)

def process_admin_deductfund_user(message):
    if message.text == "/cancel":
        bot.send_message(message.chat.id, "❌ Cancelled")
        return
    try:
        uid = int(message.text.strip())
        bal = get_balance(uid)
        bot.send_message(message.chat.id, f"👤 User: {uid}\n💳 Balance: ₦{bal}\n\nEnter AMOUNT to deduct:")
        bot.register_next_step_handler(message, process_admin_deductfund_amount, uid)
    except:
        bot.send_message(message.chat.id, "❌ Invalid ID")

def process_admin_deductfund_amount(message, uid):
    try:
        amt = int(message.text.strip())
        if amt <= 0:
            bot.send_message(message.chat.id, "❌ Positive amount")
            return
        old_bal = get_balance(uid)
        if old_bal < amt:
            bot.send_message(message.chat.id, f"⚠️ User only has ₦{old_bal}")
            return
        cursor.execute("UPDATE users SET balance=balance-? WHERE user_id=?",(amt,uid))
        conn.commit()
        log(uid,"debit",amt,"admin_deduct")
        new_bal = get_balance(uid)
        bot.send_message(message.chat.id, f"✅ Deducted ₦{amt} from {uid}\n💳 Previous: ₦{old_bal}\n💳 New: ₦{new_bal}")
        try:
            bot.send_message(uid, f"⚠️ ₦{amt} deducted\n💳 Balance: ₦{old_bal} → ₦{new_bal}")
        except:
            pass
    except:
        bot.send_message(message.chat.id, "❌ Send valid number")

@bot.message_handler(func=lambda m: m.text == "📈 Sales")
def sales_menu(message):
    if message.from_user.id != ADMIN_ID: return
    cursor.execute("SELECT COUNT(*), COALESCE(SUM(amount),0) FROM sales_log WHERE sale_date=date('now')")
    td = cursor.fetchone()
    cursor.execute("SELECT COUNT(*), COALESCE(SUM(amount),0) FROM sales_log WHERE sale_date>=date('now','-7 days')")
    wk = cursor.fetchone()
    bot.send_message(
        message.chat.id,
        f"📈 **SALES**\n\n📆 Today: {td[0]} orders, ₦{td[1]}\n📅 Week: {wk[0]} orders, ₦{wk[1]}\n💰 All: ₦{get_stat('revenue')}",
        parse_mode='Markdown'
    )

@bot.message_handler(func=lambda m: m.text == "📦 Restock")
def restock_menu(message):
    if message.from_user.id != ADMIN_ID: return
    stock = get_all_stock()
    kb = InlineKeyboardMarkup()
    for n in PRODUCTS:
        kb.add(InlineKeyboardButton(f"{n} - {stock[n]}", callback_data=f"restock_{n}"))
    kb.add(InlineKeyboardButton("🔙 Back", callback_data="back_to_admin"))
    bot.send_message(message.chat.id, "📦 **RESTOCK**", reply_markup=kb, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith("restock_"))
def restock_callback(call):
    q = call
    if q.from_user.id != ADMIN_ID: return
    pn = q.data.replace("restock_","")
    if pn in PRODUCTS:
        bot.send_message(q.message.chat.id, f"📦 RESTOCK: {pn}\n\nSend .txt file.\n/cancel")
        bot.register_next_step_handler(q.message, handle_restock_file, pn)
    bot.answer_callback_query(q.id)

def handle_restock_file(message, pn):
    if message.from_user.id != ADMIN_ID: return
    if message.text and message.text == "/cancel":
        bot.send_message(message.chat.id, "❌ Cancelled")
        return
    try:
        if not message.document:
            bot.send_message(message.chat.id, "❌ Send .txt file")
            return
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        content = downloaded_file.decode('utf-8', errors='ignore')
        new = [l.strip() for l in content.split('\n') if l.strip() and '@' in l]
        if not new:
            bot.send_message(message.chat.id, "❌ No emails")
            return
        old = get_stock_count(pn)
        added = add_bulk_to_stock(pn, new)
        bot.send_message(message.chat.id, f"✅ Restocked!\n📦 {pn}\n📊 {old}→{get_stock_count(pn)} (+{added})")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ {e}")

@bot.message_handler(func=lambda m: m.text == "📢 Broadcast")
def broadcast_menu(message):
    if message.from_user.id != ADMIN_ID: return
    bot.send_message(message.chat.id, "📢 **BROADCAST**\n\nSend your message now. It will be sent to ALL users automatically.\n/cancel to abort")
    bot.register_next_step_handler(message, process_broadcast)

def process_broadcast(message):
    if message.from_user.id != ADMIN_ID: return
    if message.text == "/cancel":
        bot.send_message(message.chat.id, "❌ Cancelled")
        return
    msg = message.text
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    sent = 0
    failed = 0
    status_msg = bot.send_message(message.chat.id, f"📢 Broadcasting to {len(users)} users...")
    for (uid,) in users:
        try:
            bot.send_message(uid, f"📢 {msg}")
            sent += 1
        except:
            failed += 1
        time.sleep(0.05)
    cursor.execute("INSERT INTO broadcast_logs (admin_id, message, total_sent, total_failed) VALUES (?,?,?,?)", (message.from_user.id, msg[:500], sent, failed))
    conn.commit()
    bot.edit_message_text(f"✅ Done!\n✅ Sent: {sent}\n❌ Failed: {failed}", message.chat.id, status_msg.message_id)

@bot.message_handler(func=lambda m: m.text == "💬 Message User")
def message_user_start(message):
    if message.from_user.id != ADMIN_ID: return
    bot.send_message(message.chat.id, "💬 **MESSAGE USER**\n\nEnter the USER ID:\n/cancel to abort")
    bot.register_next_step_handler(message, process_msg_user)

def process_msg_user(message):
    if message.from_user.id != ADMIN_ID: return
    if message.text == "/cancel":
        bot.send_message(message.chat.id, "❌ Cancelled")
        return
    try:
        uid = int(message.text.strip())
        bot.send_message(message.chat.id, f"👤 User: {uid}\n\nSend your message:\n/cancel to abort")
        bot.register_next_step_handler(message, process_send_msg, uid)
    except:
        bot.send_message(message.chat.id, "❌ Invalid ID")

def process_send_msg(message, uid):
    if message.from_user.id != ADMIN_ID: return
    if message.text == "/cancel":
        bot.send_message(message.chat.id, "❌ Cancelled")
        return
    try:
        bot.send_message(uid, f"📬 **Message from Admin:**\n\n{message.text}")
        bot.send_message(message.chat.id, f"✅ Sent to {uid}!")
    except:
        bot.send_message(message.chat.id, f"❌ Failed to send to {uid}")

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

@bot.callback_query_handler(func=lambda call: call.data.startswith("clearstock_"))
def clear_stock_callback(call):
    q = call
    if q.from_user.id != ADMIN_ID: return
    d = q.data
    if d == "clearstock_all":
        clear_all_stock()
        bot.answer_callback_query(q.id, "✅ All stock deleted!", show_alert=True)
        bot.edit_message_text("✅ All stock deleted!", q.message.chat.id, q.message.message_id)
    elif d == "clearstock_cancel":
        bot.edit_message_text("❌ Cancelled.", q.message.chat.id, q.message.message_id)
    else:
        pn = d.replace("clearstock_", "")
        if pn in PRODUCTS:
            count = get_stock_count(pn)
            clear_product_stock(pn)
            bot.answer_callback_query(q.id, f"✅ {pn} cleared! ({count} items)", show_alert=True)
            bot.edit_message_text(f"✅ {pn} cleared! ({count} items)", q.message.chat.id, q.message.message_id)

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

@bot.callback_query_handler(func=lambda call: call.data.startswith("extract_"))
def extract_stock_callback(call):
    q = call
    if q.from_user.id != ADMIN_ID: return
    d = q.data
    if d == "extract_all":
        all_emails = []
        for name in PRODUCTS:
            all_emails.extend(extract_stock(name))
        if not all_emails:
            bot.answer_callback_query(q.id, "❌ No stock!", show_alert=True)
            return
        content = "\n".join(all_emails)
        with open("all_stock.txt", "w") as f:
            f.write(content)
        with open("all_stock.txt", "rb") as f:
            bot.send_document(ADMIN_ID, f, caption=f"📤 All Stock\n📦 {len(all_emails)} items")
        os.remove("all_stock.txt")
        bot.answer_callback_query(q.id, f"✅ Exported {len(all_emails)} items!", show_alert=True)
        bot.edit_message_text(f"✅ Exported {len(all_emails)} items!", q.message.chat.id, q.message.message_id)
    elif d.startswith("extract_"):
        pn = d.replace("extract_", "")
        if pn in PRODUCTS:
            emails = extract_stock(pn)
            if not emails:
                bot.answer_callback_query(q.id, "❌ No stock!", show_alert=True)
                return
            content = "\n".join(emails)
            filename = f"{pn.replace(' ','_').replace('(','').replace(')','')}.txt"
            with open(filename, "w") as f:
                f.write(content)
            with open(filename, "rb") as f:
                bot.send_document(ADMIN_ID, f, caption=f"📤 {pn}\n📦 {len(emails)} items")
            os.remove(filename)
            bot.answer_callback_query(q.id, f"✅ Exported {pn}: {len(emails)} items!", show_alert=True)
            bot.edit_message_text(f"✅ Exported {pn}: {len(emails)} items!", q.message.chat.id, q.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data == "back_to_admin")
def back_to_admin(call):
    q = call
    if q.from_user.id != ADMIN_ID: return
    bot.edit_message_text("👑 **ADMIN PANEL**", q.message.chat.id, q.message.message_id, reply_markup=get_admin_keyboard(), parse_mode='Markdown')
    bot.answer_callback_query(q.id)

# ================= REPORT CALLBACKS =================
@bot.callback_query_handler(func=lambda call: call.data.startswith("report_"))
def report_callback(call):
    q = call
    it = q.data.replace("report_", "")
    prompts = {"taken": "📧 Gmail Already Taken", "notlinked": "📷 Instagram Not Linked", "payment": "💳 Payment Issue", "other": "❓ Other Issue"}
    if it in ["taken", "notlinked", "payment", "other"]:
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("📝 SUBMIT REPORT", callback_data=f"report_submit_{it}"))
        kb.add(InlineKeyboardButton("❌ Cancel", callback_data="report_cancel"))
        bot.edit_message_text(
            f"📝 **{prompts.get(it)}**\n\nSend description then click Submit.",
            q.message.chat.id,
            q.message.message_id,
            reply_markup=kb,
            parse_mode='Markdown'
        )
        bot.register_next_step_handler(q.message, process_report_desc, it)
    bot.answer_callback_query(q.id)

def process_report_desc(message, it):
    user_id = message.from_user.id
    desc = message.text
    user_data[user_id]["report_desc"] = desc
    user_data[user_id]["report_type"] = it
    bot.send_message(user_id, "✅ Text saved! Click SUBMIT REPORT button to submit.")

@bot.callback_query_handler(func=lambda call: call.data.startswith("report_submit_"))
def report_submit_callback(call):
    q = call
    u = q.from_user
    it = q.data.replace("report_submit_", "")
    desc = user_data.get(u.id, {}).get("report_desc", "")
    if not desc:
        bot.answer_callback_query(q.id, "Send description first!", show_alert=True)
        return
    issue_names = {"taken": "📧 Gmail Already Taken", "notlinked": "📷 Instagram Not Linked", "payment": "💳 Payment Issue", "other": "❓ Other Issue"}
    cursor.execute("INSERT INTO reports (user_id, issue_type, description) VALUES (?,?,?)", (u.id, it, desc[:500]))
    conn.commit()
    rid = cursor.lastrowid
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✅ Resolve", callback_data=f"resolve_{rid}"))
    kb.add(InlineKeyboardButton("💬 Reply", callback_data=f"reply_{rid}"))
    kb.add(InlineKeyboardButton("💰 Add Funds", callback_data=f"addfund_{u.id}"))
    try:
        bot.send_message(
            ADMIN_ID,
            f"📝 **NEW REPORT #{rid}**\n\n👤 {u.full_name}\n🆔 {u.id}\n🏷 {issue_names.get(it, it)}\n📄 {desc[:800]}",
            reply_markup=kb,
            parse_mode='Markdown'
        )
    except:
        pass
    bot.edit_message_text(f"✅ **Report #{rid} Submitted!**", q.message.chat.id, q.message.message_id)
    bot.answer_callback_query(q.id)

@bot.callback_query_handler(func=lambda call: call.data == "report_cancel")
def report_cancel(call):
    q = call
    bot.edit_message_text("❌ Report cancelled.", q.message.chat.id, q.message.message_id)
    bot.answer_callback_query(q.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("resolve_"))
def resolve_report_callback(call):
    q = call
    if q.from_user.id != ADMIN_ID: return
    rid = int(q.data.replace("resolve_", ""))
    cursor.execute("UPDATE reports SET status='resolved' WHERE id=?", (rid,))
    conn.commit()
    cursor.execute("SELECT user_id FROM reports WHERE id=?", (rid,))
    row = cursor.fetchone()
    if row:
        try:
            bot.send_message(row[0], f"✅ Your report #{rid} has been resolved!")
        except:
            pass
    bot.answer_callback_query(q.id, f"✅ Report #{rid} resolved!", show_alert=True)
    bot.edit_message_text(f"✅ Report #{rid} resolved.", q.message.chat.id, q.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("reply_"))
def reply_report_callback(call):
    q = call
    if q.from_user.id != ADMIN_ID: return
    rid = int(q.data.replace("reply_", ""))
    bot.send_message(q.message.chat.id, f"💬 Reply to report #{rid}:\n\nSend your message:")
    bot.register_next_step_handler(q.message, process_reply_msg, rid)
    bot.answer_callback_query(q.id)

def process_reply_msg(message, rid):
    if message.from_user.id != ADMIN_ID: return
    cursor.execute("SELECT user_id FROM reports WHERE id=?", (rid,))
    row = cursor.fetchone()
    if row:
        try:
            bot.send_message(row[0], f"📬 **Admin Response (#{rid})**\n\n{message.text}")
            cursor.execute("UPDATE reports SET admin_response=? WHERE id=?", (message.text[:500], rid))
            conn.commit()
            bot.send_message(message.chat.id, "✅ Reply sent!")
        except:
            bot.send_message(message.chat.id, "❌ Error sending reply")

@bot.callback_query_handler(func=lambda call: call.data.startswith("addfund_"))
def addfund_from_report(call):
    q = call
    if q.from_user.id != ADMIN_ID: return
    uid = int(q.data.replace("addfund_", ""))
    bot.send_message(q.message.chat.id, f"💰 Enter amount for user {uid}:")
    bot.register_next_step_handler(q.message, process_addfund_amount, uid)
    bot.answer_callback_query(q.id)

def process_addfund_amount(message, uid):
    if message.from_user.id != ADMIN_ID: return
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
            bot.send_message(uid, f"💰 Admin added ₦{amt}!\n💳 Balance: ₦{new_bal}")
        except:
            pass
    except:
        bot.send_message(message.chat.id, "❌ Invalid amount")

# ================= APPROVE/REJECT PAYMENT =================
@bot.callback_query_handler(func=lambda call: call.data.startswith("approve:") or call.data.startswith("reject:"))
def approve_reject_callback(call):
    q = call
    user_id = int(q.data.split(":")[1])
    
    if q.data.startswith("approve:"):
        if user_id not in pending_approvals:
            bot.answer_callback_query(q.id, "⚠️ Already processed!", show_alert=True)
            return
        bot.send_message(q.message.chat.id, f"💰 Enter amount for user {user_id}:")
        bot.register_next_step_handler(q.message, process_approve_amount, user_id)
        bot.answer_callback_query(q.id)
        return
    
    if q.data.startswith("reject:"):
        if user_id not in pending_approvals:
            bot.answer_callback_query(q.id, "❌ Not found!", show_alert=True)
            return
        info = pending_approvals[user_id]
        cursor.execute("UPDATE deposits SET status='rejected' WHERE ref=?", (info.get('ref'),))
        conn.commit()
        try:
            bot.send_message(user_id, "❌ **PAYMENT DECLINED**\n\nContact admin.", parse_mode='Markdown')
        except:
            pass
        pending_approvals.pop(user_id, None)
        bot.answer_callback_query(q.id, "✅ Rejected!", show_alert=True)
        bot.edit_message_text("✅ Rejected!", q.message.chat.id, q.message.message_id)

def process_approve_amount(message, uid):
    if message.from_user.id != ADMIN_ID: return
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
            bot.send_message(uid, f"✅ **PAYMENT APPROVED!**\n\n💰 Amount: ₦{amt}\n💳 Previous: ₦{old_bal}\n💳 New: ₦{new_bal}\n\nThank you!", parse_mode='Markdown')
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
    
    # Check button texts
    buttons = ["💰 Wallet", "➕ Fund Wallet", "📦 Check Stock", "🧾 My History", 
               "💳 My Deposits", "🛒 Buy Products", "🛒 My Cart", "🤖 Expert Support", 
               "📝 Report Issue", "🤝 Refer & Earn", "📋 Help & FAQ", "👑 Admin Panel", 
               "📊 Stats", "📥 Pending", "📝 Reports", "💰 Add Funds", "💸 Deduct Funds", 
               "👤 View Balance", "📈 Sales", "📦 Restock", "📢 Broadcast", "💬 Message User", 
               "🚫 Block/Unblock", "🗑 Clear Stock", "📤 Extract Stock", "🔄 User Menu", 
               "❌ Exit Support"]
    if text in buttons:
        return
    
    # Check if it's an admin command
    if user_id == ADMIN_ID:
        if text == "/cancel":
            bot.send_message(user_id, "❌ Cancelled")
            return
    
    # Auto response for common questions
    auto_responses = {
        "price": "💰 Prices: ₦1000 – ₦8500. Check 📦 Check Stock.",
        "how": "📋 Buy uncreated Gmail → Create it → Instagram 'Forgot Password' → Reset → Own both!",
        "gmail": "📧 We sell UNCREATED Gmail addresses. You create them yourself.",
        "buy": "🛒 Fund wallet → Buy Products → Click BUY to purchase instantly → Confirm → Get email!"
    }
    for key, response in auto_responses.items():
        if key in text.lower():
            bot.send_message(user_id, response)
            return
    
    bot.send_message(user_id, "❌ Please use the buttons below.", reply_markup=get_main_keyboard(user_id))

# ================= MAIN =================
print("="*50)
print("✅ BOT RUNNING!")
print("🛒 BUY = Instant purchase | ➕ Cart = Add to cart")
print("💰 Approval shows Previous & New balance")
print("👤 /balance [id] - View user balance")
print("="*50)

while True:
    try:
        bot.infinity_polling(timeout=10, long_polling_timeout=10)
    except Exception as e:
        print(f"Error: {e}")
        time.sleep(5)
