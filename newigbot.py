import sqlite3
import time
import random
import os
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

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

# ================= MEMORY =================
pending_approvals = {}
fraud_tracker = {}
blocked_users = set()
user_support_mode = {}

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

# ================= HANDLERS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    add_user(user_id)
    user_support_mode.pop(user_id, None)

    if context.args and context.args[0].startswith("ref_"):
        try:
            referrer_id = int(context.args[0].replace("ref_", ""))
            if referrer_id != user_id:
                cursor.execute("SELECT id FROM referrals WHERE referred_id=?", (user_id,))
                if not cursor.fetchone() and referrer_id != user_id:
                    cursor.execute("INSERT INTO referrals (referrer_id, referred_id) VALUES (?,?)", (referrer_id, user_id))
                    cursor.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (REFERRAL_BONUS, referrer_id))
                    cursor.execute("INSERT INTO referral_earnings (user_id, amount, from_user_id) VALUES (?,?,?)", (referrer_id, REFERRAL_BONUS, user_id))
                    log(referrer_id, "credit", REFERRAL_BONUS, f"referral_from_{user_id}")
                    conn.commit()
                    try:
                        await context.bot.send_message(referrer_id, f"🎉 New referral! +₦{REFERRAL_BONUS}")
                    except:
                        pass
        except:
            pass

    cart_count = len(get_cart(user_id))
    cart_text = f" | 🛒 {cart_count} items" if cart_count > 0 else ""

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

    await update.message.reply_text(
        f"🛒 **Store Bot**{cart_text}\n\n"
        f"📧 Buy uncreated Gmail → Create → Recover IG\n"
        f"🤝 Earn ₦{REFERRAL_BONUS}/referral!\n"
        f"📞 Contact: WhatsApp {WHATSAPP_NUMBER}",
        reply_markup=ReplyKeyboardMarkup(menu, resize_keyboard=True)
    )

async def contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📞 **CONTACT US**\n\n"
        f"📱 WhatsApp: `{WHATSAPP_NUMBER}`\n"
        f"👤 Bot Owner: @{BOT_USERNAME}\n\n"
        f"Feel free to reach out for support or inquiries.",
        parse_mode='Markdown'
    )

async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"💰 Balance: ₦{get_balance(update.message.from_user.id)}")

async def fund(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ref = generate_ref()
    context.user_data["fund_ref"] = ref
    context.user_data["awaiting_name"] = True
    await update.message.reply_text(
        f"💳 **FUND YOUR WALLET**\n\n🏦 {BANK_NAME}\n🔢 {ACCOUNT_NUMBER}\n👤 {ACCOUNT_NAME}\n\n🆔 {ref}\n\n📝 Send SENDER NAME first.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ I've Made Payment", callback_data=f"pay:{ref}")]])
    )

async def user_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "📦 **STOCK**\n\n"
    stock = get_all_stock()
    for name in PRODUCTS:
        msg += f"{'✅' if stock[name] > 0 else '❌'} {name}: {stock[name]} available\n"
    await update.message.reply_text(msg)

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    cursor.execute("SELECT type,amount,details FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 10", (uid,))
    rows = cursor.fetchall()
    if not rows:
        await update.message.reply_text("📭 No transactions yet")
        return
    msg = "🧾 **YOUR HISTORY**\n\n"
    for t, a, d in rows:
        msg += f"{'➕' if t=='credit' else '➖'} ₦{a} - {d}\n"
    await update.message.reply_text(msg)

async def my_deposits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    cursor.execute("SELECT ref, amount, status, decline_reason FROM deposits WHERE user_id=? ORDER BY id DESC LIMIT 5", (uid,))
    rows = cursor.fetchall()
    if not rows:
        await update.message.reply_text("📭 No deposits yet")
        return
    msg = "💳 **YOUR DEPOSITS**\n\n"
    for r, a, s, dr in rows:
        emoji = "✅" if s == "approved" else "⏳" if s == "pending" else "❌"
        msg += f"{emoji} {r}: {'₦'+str(a) if a else '...'} ({s})\n"
        if dr:
            msg += f"   📋 {dr}\n"
    await update.message.reply_text(msg)

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return
    kb = [
        ["📊 Stats", "📥 Pending"],
        ["📝 Reports", "💰 Add Funds"],
        ["💸 Deduct Funds", "📈 Sales"],
        ["📦 Restock", "📢 Broadcast"],
        ["💬 Message User", "👤 View Balance"],
        ["🚫 Block/Unblock", "🗑 Clear Stock"],
        ["📤 Extract Stock", "🔄 User Menu"]
    ]
    await update.message.reply_text("👑 **ADMIN PANEL**", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))

async def switch_to_user_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    menu = [
        ["💰 Wallet", "➕ Fund Wallet"],
        ["📦 Check Stock", "🧾 My History"],
        ["💳 My Deposits", "🛒 Buy Products"],
        ["🤖 Expert Support", "📝 Report Issue"],
        ["🤝 Refer & Earn", "🛒 My Cart"],
        ["📋 Help & FAQ", "📞 Contact"],
        ["👑 Admin Panel"]
    ]
    await update.message.reply_text("🔄 Switched to User Menu", reply_markup=ReplyKeyboardMarkup(menu, resize_keyboard=True))

async def view_balance_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return
    context.user_data["awaiting_view_balance"] = True
    await update.message.reply_text("👤 **VIEW USER BALANCE**\n\nEnter the USER ID:\n/cancel to abort")

async def view_balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return
    try:
        if len(context.args) < 1:
            await update.message.reply_text("Usage: /balance [user_id]")
            return
        uid = int(context.args[0])
        bal = get_balance(uid)
        try:
            target = await context.bot.get_chat(uid)
            name = f"{target.full_name} (@{target.username})" if target.username else target.full_name
        except:
            name = f"User {uid}"
        await update.message.reply_text(f"👤 **{name}**\n🆔 ID: {uid}\n💰 Balance: ₦{bal}")
    except:
        await update.message.reply_text("❌ Invalid ID. Use: /balance [user_id]")

async def block_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return
    try:
        if len(context.args) < 1:
            await update.message.reply_text("/block [user_id]")
            return
        uid = int(context.args[0])
        if uid in blocked_users:
            await update.message.reply_text(f"ℹ️ Already blocked.")
            return
        blocked_users.add(uid)
        await update.message.reply_text(f"🚫 User {uid} BLOCKED!")
        try:
            await context.bot.send_message(uid, "🚫 You have been blocked from submitting payment proofs.")
        except:
            pass
    except:
        await update.message.reply_text("❌ Invalid ID")

async def unblock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return
    try:
        if len(context.args) < 1:
            await update.message.reply_text("/unblock [user_id]")
            return
        uid = int(context.args[0])
        if uid not in blocked_users:
            await update.message.reply_text(f"ℹ️ Not blocked.")
            return
        blocked_users.discard(uid)
        if uid in fraud_tracker:
            fraud_tracker[uid] = {"last": 0, "count": 0}
        await update.message.reply_text(f"✅ User {uid} UNBLOCKED!")
        try:
            await context.bot.send_message(uid, "✅ You have been unblocked!")
        except:
            pass
    except:
        await update.message.reply_text("❌ Invalid ID")

async def blocked_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return
    if not blocked_users:
        await update.message.reply_text("✅ No blocked users!")
        return
    msg = "🚫 **BLOCKED USERS**\n\n"
    for uid in blocked_users:
        msg += f"🆔 {uid}\n"
    await update.message.reply_text(msg)

async def block_unblock_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return
    kb = [
        [InlineKeyboardButton("🚫 Block User", callback_data="block_menu")],
        [InlineKeyboardButton("✅ Unblock User", callback_data="unblock_menu")],
        [InlineKeyboardButton("📋 View Blocked", callback_data="blocked_list")]
    ]
    await update.message.reply_text("🚫 **BLOCK/UNBLOCK**", reply_markup=InlineKeyboardMarkup(kb))

async def block_unblock_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.from_user.id != ADMIN_ID:
        return
    d = q.data
    if d == "block_menu":
        context.user_data["awaiting_block_user"] = True
        await q.edit_message_text("🚫 Enter User ID to block:\n/cancel")
    elif d == "unblock_menu":
        context.user_data["awaiting_unblock_user"] = True
        await q.edit_message_text("✅ Enter User ID to unblock:\n/cancel")
    elif d == "blocked_list":
        if not blocked_users:
            await q.edit_message_text("✅ No blocked users!")
        else:
            msg = "🚫 **BLOCKED**\n\n"
            for uid in blocked_users:
                msg += f"🆔 {uid}\n"
            await q.edit_message_text(msg)

async def buy_products_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    k = [
        [InlineKeyboardButton("📧 Small (0-100)", callback_data="cat_small")],
        [InlineKeyboardButton("📧 Medium (200-500)", callback_data="cat_medium")],
        [InlineKeyboardButton("📧 Large (600-1000)", callback_data="cat_large")],
        [InlineKeyboardButton("📦 All", callback_data="cat_all")]
    ]
    await update.message.reply_text("🛒 **BUY PRODUCTS**\n\nSelect category to buy instantly or use Cart for bulk.", reply_markup=InlineKeyboardMarkup(k))

async def category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    cat = q.data.replace("cat_", "")
    if cat == "small":
        p = {k: v for k, v in PRODUCTS.items() if v <= 3000}
        t = "SMALL"
    elif cat == "medium":
        p = {k: v for k, v in PRODUCTS.items() if 4000 <= v <= 6000}
        t = "MEDIUM"
    elif cat == "large":
        p = {k: v for k, v in PRODUCTS.items() if v >= 6500}
        t = "LARGE"
    else:
        p = PRODUCTS
        t = "ALL"
    msg = f"**{t}**\n\n🛒 Click to BUY NOW | 🛒➕ Click to ADD TO CART\n\n"
    kb = []
    for n, pr in p.items():
        s = get_stock_count(n)
        msg += f"{'✅' if s > 0 else '❌'} {n}: {s} available - ₦{pr}\n"
        if s > 0:
            kb.append([InlineKeyboardButton(f"🛒 BUY {n}", callback_data=f"buy_{n}"), InlineKeyboardButton(f"➕ Cart", callback_data=f"addcart_{n}")])
    kb.append([InlineKeyboardButton("🔙 Back to Categories", callback_data="back_to_categories")])
    await q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb))

async def buy_product_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    u = q.from_user
    pn = q.data.replace("buy_", "")
    if pn not in PRODUCTS:
        return
    pr = PRODUCTS[pn]
    if get_stock_count(pn) == 0:
        await q.answer("❌ Out of stock!", show_alert=True)
        return
    bal = get_balance(u.id)
    if bal < pr:
        await q.answer(f"❌ Insufficient funds! Need ₦{pr}, you have ₦{bal}", show_alert=True)
        return
    kb = [
        [InlineKeyboardButton("✅ Confirm Purchase", callback_data=f"confirm_{pn}")],
        [InlineKeyboardButton("❌ Cancel", callback_data="back_to_categories")]
    ]
    await q.edit_message_text(
        f"🛒 **CONFIRM**\n\n📦 {pn}\n💰 Price: ₦{pr}\n💳 Balance: ₦{bal}\n💳 After: ₦{bal-pr}",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def confirm_purchase_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    u = q.from_user
    pn = q.data.replace("confirm_", "")
    if pn not in PRODUCTS:
        return
    pr = PRODUCTS[pn]
    if get_balance(u.id) < pr:
        await q.answer("❌ Insufficient!", show_alert=True)
        return
    item = get_item_from_stock(pn)
    if not item:
        await q.answer("❌ Out of stock!", show_alert=True)
        return
    item_id, email = item

    progress_msg = await q.edit_message_text("⏳ Processing your order... 0%")
    for i in range(1, 11):
        percent = i * 10
        bar = "█" * i + "░" * (10 - i)
        await progress_msg.edit_text(f"⏳ Processing your order... `[{bar}] {percent}%`", parse_mode='Markdown')
        time.sleep(0.3)

    mark_item_sold(item_id)
    cursor.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (pr, u.id))
    conn.commit()
    update_stat("revenue", pr)
    update_stat("orders", 1)
    log(u.id, "purchase", pr, pn)
    new_bal = get_balance(u.id)

    receipt = f"""
╔══════════════════════════════════════╗
║         📄 PURCHASE RECEIPT          ║
╠══════════════════════════════════════╣
║  🆔 Order ID: #{random.randint(10000,99999)}
║  📅 Date: {time.strftime('%Y-%m-%d %H:%M')}
║  📦 Product: {pn}
║  📧 Email: `{email}`
║  💰 Amount: ₦{pr}
║  💳 Balance After: ₦{new_bal}
║  ✅ Status: COMPLETED
╚══════════════════════════════════════╝
    """
    await q.edit_message_text(
        f"✅ **PURCHASED!**\n\n{receipt}\n\n📦 {pn}\n📧 `{email}`",
        parse_mode='Markdown'
    )

async def add_to_cart_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    u = q.from_user
    pn = q.data.replace("addcart_", "")
    if pn not in PRODUCTS:
        return
    pr = PRODUCTS[pn]
    if get_stock_count(pn) == 0:
        await q.answer("❌ Out of stock!", show_alert=True)
        return
    add_to_cart(u.id, pn, pr)
    cart_count = len(get_cart(u.id))
    cart_total = get_cart_total(u.id)
    await q.answer(f"✅ Added! 🛒 {cart_count} items | ₦{cart_total}", show_alert=True)

async def back_to_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    k = [
        [InlineKeyboardButton("📧 Small", callback_data="cat_small")],
        [InlineKeyboardButton("📧 Medium", callback_data="cat_medium")],
        [InlineKeyboardButton("📧 Large", callback_data="cat_large")],
        [InlineKeyboardButton("📦 All", callback_data="cat_all")]
    ]
    await q.edit_message_text("🛒 **BUY PRODUCTS**", reply_markup=InlineKeyboardMarkup(k))

async def view_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.message.from_user
    items = get_cart(u.id)
    if not items:
        kb = [[InlineKeyboardButton("🛒 Browse Products", callback_data="cat_all")]]
        await update.message.reply_text("🛒 Cart empty!", reply_markup=InlineKeyboardMarkup(kb))
        return
    total = get_cart_total(u.id)
    bal = get_balance(u.id)
    msg = f"🛒 **YOUR CART**\n\n"
    kb = []
    for item in items:
        cart_id, pn, pr, qty = item
        msg += f"📦 {pn}\n   Qty: {qty} × ₦{pr} = ₦{pr*qty}\n\n"
        kb.append([
            InlineKeyboardButton(f"➕ Add more", callback_data=f"qtyadd_{cart_id}"),
            InlineKeyboardButton(f"➖ Remove one", callback_data=f"qtysub_{cart_id}"),
            InlineKeyboardButton(f"❌ Remove all", callback_data=f"rmcart_{cart_id}")
        ])
    msg += f"━━━━━━━━━━━━━━━\n💰 **Total: ₦{total}**\n💳 Balance: ₦{bal}\n"
    if total > 0:
        if bal >= total:
            msg += f"\n✅ You have enough funds!"
            kb.append([InlineKeyboardButton("✅ CHECKOUT NOW", callback_data="checkout")])
        else:
            msg += f"\n⚠️ Insufficient! Need ₦{total - bal} more."
    kb.append([InlineKeyboardButton("🗑 Clear Cart", callback_data="clearcart")])
    kb.append([InlineKeyboardButton("🛒 Continue Shopping", callback_data="cat_all")])
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb))

async def cart_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    u = q.from_user
    d = q.data

    if d.startswith("addcart_"):
        await add_to_cart_callback(update, context)
        return
    if d.startswith("rmcart_"):
        remove_from_cart(u.id, int(d.replace("rmcart_", "")))
        await view_cart(update, context)
        return
    if d.startswith("qtyadd_"):
        cursor.execute("UPDATE cart SET quantity=quantity+1 WHERE id=? AND user_id=?", (int(d.replace("qtyadd_", "")), u.id))
        conn.commit()
        await view_cart(update, context)
        return
    if d.startswith("qtysub_"):
        cid = int(d.replace("qtysub_", ""))
        cursor.execute("SELECT quantity FROM cart WHERE id=? AND user_id=?", (cid, u.id))
        row = cursor.fetchone()
        if row and row[0] > 1:
            cursor.execute("UPDATE cart SET quantity=quantity-1 WHERE id=?", (cid,))
            conn.commit()
        else:
            remove_from_cart(u.id, cid)
        await view_cart(update, context)
        return
    if d == "clearcart":
        clear_cart(u.id)
        await q.edit_message_text("🛒 Cart cleared!")
        return
    if d == "checkout":
        await checkout_cart(update, context)
        return

async def checkout_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    u = q.from_user
    items = get_cart(u.id)
    if not items:
        await q.answer("Cart empty!", show_alert=True)
        return
    total = get_cart_total(u.id)
    if get_balance(u.id) < total:
        await q.answer(f"❌ Need ₦{total}!", show_alert=True)
        return
    for item in items:
        if get_stock_count(item[1]) < item[3]:
            await q.edit_message_text(f"❌ Not enough stock for {item[1]}!")
            return

    progress_msg = await q.edit_message_text("⏳ Processing your order... 0%")
    for i in range(1, 11):
        percent = i * 10
        bar = "█" * i + "░" * (10 - i)
        await progress_msg.edit_text(f"⏳ Processing your order... `[{bar}] {percent}%`", parse_mode='Markdown')
        time.sleep(0.3)

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
    await q.edit_message_text(f"✅ **ORDER COMPLETE!**\n\n{receipt}")

async def expert_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_support_mode[update.message.from_user.id] = True
    await update.message.reply_text(
        "🤖 **SUPPORT**\n\nAsk me anything!\nType 'exit' to leave.",
        reply_markup=ReplyKeyboardMarkup([["❌ Exit Support"]], resize_keyboard=True)
    )

async def handle_support_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.message.from_user
    t = update.message.text
    if t == "❌ Exit Support":
        user_support_mode.pop(u.id, None)
        await start(update, context)
        return
    msg = t.lower()
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
    await update.message.reply_text(r)

async def report_issue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    k = [
        [InlineKeyboardButton("📧 Gmail Taken", callback_data="report_taken")],
        [InlineKeyboardButton("📷 IG Not Linked", callback_data="report_notlinked")],
        [InlineKeyboardButton("💳 Payment", callback_data="report_payment")],
        [InlineKeyboardButton("❓ Other", callback_data="report_other")]
    ]
    await update.message.reply_text("📝 **FILE A REPORT**\n\nSelect type:", reply_markup=InlineKeyboardMarkup(k))

async def report_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    it = q.data.replace("report_", "")
    context.user_data["report_type"] = it
    context.user_data["awaiting_report"] = True
    prompts = {
        "taken": "📧 Gmail Already Taken",
        "notlinked": "📷 Instagram Not Linked",
        "payment": "💳 Payment Issue",
        "other": "❓ Other Issue"
    }
    await q.edit_message_text(
        f"📝 **{prompts.get(it)}**\n\nSend description then click Submit.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 SUBMIT REPORT", callback_data="report_submit")],
            [InlineKeyboardButton("❌ Cancel", callback_data="report_cancel")]
        ])
    )

async def report_submit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "report_submit":
        u = q.from_user
        desc = context.user_data.get("report_desc", "").strip()
        it = context.user_data.get("report_type", "other")
        if not desc:
            await q.answer("Send description first!", show_alert=True)
            return
        issue_names = {
            "taken": "📧 Gmail Already Taken",
            "notlinked": "📷 Instagram Not Linked",
            "payment": "💳 Payment Issue",
            "other": "❓ Other Issue"
        }
        cursor.execute("INSERT INTO reports (user_id, issue_type, description) VALUES (?,?,?)", (u.id, it, desc[:500]))
        conn.commit()
        rid = cursor.lastrowid
        try:
            kb = [
                [InlineKeyboardButton("✅ Resolve", callback_data=f"resolve_{rid}")],
                [InlineKeyboardButton("💬 Reply", callback_data=f"reply_{rid}")],
                [InlineKeyboardButton("💰 Add Funds", callback_data=f"addfund_{u.id}")]
            ]
            await context.bot.send_message(
                ADMIN_ID,
                f"📝 **NEW REPORT #{rid}**\n\n👤 {u.full_name}\n📛 @{u.username or 'N/A'}\n🆔 {u.id}\n🏷 {issue_names.get(it, it)}\n📄 {desc[:800]}",
                reply_markup=InlineKeyboardMarkup(kb)
            )
        except:
            pass
        context.user_data.pop("report_type", None)
        context.user_data.pop("report_desc", None)
        context.user_data.pop("awaiting_report", None)
        await q.edit_message_text(f"✅ **Report #{rid} Submitted!**")
    else:
        context.user_data.pop("report_type", None)
        context.user_data.pop("report_desc", None)
        context.user_data.pop("awaiting_report", None)
        await q.edit_message_text("❌ Report cancelled.")

async def resolve_report_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.from_user.id != ADMIN_ID:
        return
    rid = int(q.data.replace("resolve_", ""))
    cursor.execute("UPDATE reports SET status='resolved' WHERE id=?", (rid,))
    conn.commit()
    cursor.execute("SELECT user_id FROM reports WHERE id=?", (rid,))
    row = cursor.fetchone()
    if row:
        try:
            await context.bot.send_message(row[0], f"✅ Your report #{rid} has been resolved!")
        except:
            pass
    await q.edit_message_text(f"✅ Report #{rid} resolved.")

async def reply_report_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.from_user.id != ADMIN_ID:
        return
    context.user_data["replying_to"] = int(q.data.replace("reply_", ""))
    await context.bot.send_message(ADMIN_ID, "💬 Send your reply:\n/cancel to abort.")

async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.message.from_user
    if u.id != ADMIN_ID or "replying_to" not in context.user_data:
        return
    t = update.message.text
    if t == "/cancel":
        del context.user_data["replying_to"]
        await update.message.reply_text("❌ Cancelled")
        return
    rid = context.user_data.pop("replying_to")
    cursor.execute("SELECT user_id FROM reports WHERE id=?", (rid,))
    row = cursor.fetchone()
    if row:
        try:
            await context.bot.send_message(row[0], f"📬 **Admin Response (#{rid})**\n\n{t}")
        except:
            pass
        cursor.execute("UPDATE reports SET admin_response=? WHERE id=?", (t, rid))
        conn.commit()
        await update.message.reply_text("✅ Reply sent!")

async def help_faq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    k = [
        [InlineKeyboardButton("📋 How It Works", callback_data="faq_how")],
        [InlineKeyboardButton("💳 How to Fund", callback_data="faq_fund")],
        [InlineKeyboardButton("🛒 How to Buy", callback_data="faq_buy")],
        [InlineKeyboardButton("🛒 Using Cart", callback_data="faq_cart")],
        [InlineKeyboardButton("🔄 Replacements", callback_data="faq_replace")]
    ]
    await update.message.reply_text("📋 **HELP & FAQ**", reply_markup=InlineKeyboardMarkup(k))

async def faq_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    faq = q.data.replace("faq_", "")
    faqs = {
        "how": "📋 Buy uncreated Gmail → Create it → Instagram 'Forgot Password' → Enter Gmail → Reset password → Own both!",
        "fund": f"💳 Transfer to {BANK_NAME} ({ACCOUNT_NUMBER}) - {ACCOUNT_NAME} → Send name → Upload screenshot → Wait approval",
        "buy": "🛒 Fund wallet → Buy Products → Click BUY to purchase instantly → Confirm → Get email!",
        "cart": "🛒 Click ➕ Cart to add items → View Cart to manage → Adjust quantities → Checkout all at once!",
        "replace": "🔄 Replacement if Gmail taken or IG not linked. Report within 1 hour."
    }
    if faq in faqs:
        await q.edit_message_text(
            faqs[faq],
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_to_faq")]])
        )

async def back_to_faq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    k = [
        [InlineKeyboardButton("📋 How", callback_data="faq_how")],
        [InlineKeyboardButton("💳 Fund", callback_data="faq_fund")],
        [InlineKeyboardButton("🛒 Buy", callback_data="faq_buy")],
        [InlineKeyboardButton("🛒 Cart", callback_data="faq_cart")],
        [InlineKeyboardButton("🔄 Replace", callback_data="faq_replace")]
    ]
    await q.edit_message_text("📋 **HELP & FAQ**", reply_markup=InlineKeyboardMarkup(k))

async def refer_earn_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🤝 **REFER & EARN ₦{REFERRAL_BONUS}**\n\n"
        f"🔗 `{generate_referral_link(update.message.from_user.id)}`",
        parse_mode='Markdown'
    )

# ================= ADMIN STOCK FUNCTIONS =================

async def clear_stock_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return
    stock = get_all_stock()
    kb = [[InlineKeyboardButton("🗑 CLEAR ALL", callback_data="clearstock_all")]]
    for name, count in stock.items():
        if count > 0:
            kb.append([InlineKeyboardButton(f"🗑 {name} ({count})", callback_data=f"clearstock_{name}")])
    kb.append([InlineKeyboardButton("❌ Cancel", callback_data="clearstock_cancel")])
    await update.message.reply_text("🗑 **CLEAR STOCK**", reply_markup=InlineKeyboardMarkup(kb))

async def clear_stock_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.from_user.id != ADMIN_ID:
        return
    d = q.data
    if d == "clearstock_all":
        clear_all_stock()
        await q.edit_message_text("✅ All stock deleted!")
    elif d == "clearstock_cancel":
        await q.edit_message_text("❌ Cancelled.")
    elif d.startswith("clearstock_"):
        pn = d.replace("clearstock_", "")
        if pn in PRODUCTS:
            count = get_stock_count(pn)
            clear_product_stock(pn)
            await q.edit_message_text(f"✅ {pn} cleared! ({count} items)")

async def extract_stock_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return
    stock = get_all_stock()
    kb = []
    for name, count in stock.items():
        if count > 0:
            kb.append([InlineKeyboardButton(f"📤 {name} ({count})", callback_data=f"extract_{name}")])
    kb.append([InlineKeyboardButton("📤 ALL", callback_data="extract_all")])
    await update.message.reply_text("📤 **EXTRACT STOCK**", reply_markup=InlineKeyboardMarkup(kb))

async def extract_stock_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.from_user.id != ADMIN_ID:
        return
    d = q.data
    if d == "extract_all":
        all_emails = []
        for name in PRODUCTS:
            all_emails.extend(extract_stock(name))
        if not all_emails:
            await q.edit_message_text("❌ No stock!")
            return
        content = "\n".join(all_emails)
        with open("all_stock.txt", "w") as f:
            f.write(content)
        with open("all_stock.txt", "rb") as f:
            await context.bot.send_document(ADMIN_ID, f, caption=f"📤 All Stock\n📦 {len(all_emails)} items")
        os.remove("all_stock.txt")
        await q.edit_message_text(f"✅ Exported {len(all_emails)} items!")
    elif d.startswith("extract_"):
        pn = d.replace("extract_", "")
        if pn in PRODUCTS:
            emails = extract_stock(pn)
            if not emails:
                await q.edit_message_text("❌ No stock!")
                return
            content = "\n".join(emails)
            filename = f"{pn.replace(' ','_').replace('(','').replace(')','')}.txt"
            with open(filename, "w") as f:
                f.write(content)
            with open(filename, "rb") as f:
                await context.bot.send_document(ADMIN_ID, f, caption=f"📤 {pn}\n📦 {len(emails)} items")
            os.remove(filename)
            await q.edit_message_text(f"✅ Exported {pn}: {len(emails)} items!")

async def restock_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return
    kb = []
    stock = get_all_stock()
    for n in PRODUCTS:
        kb.append([InlineKeyboardButton(f"{n} - {stock[n]}", callback_data=f"restock_{n}")])
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="back_to_admin")])
    await update.message.reply_text("📦 **RESTOCK**", reply_markup=InlineKeyboardMarkup(kb))

async def restock_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.from_user.id != ADMIN_ID:
        return
    if q.data == "back_to_admin":
        await admin_panel(update, context)
        return
    pn = q.data.replace("restock_", "")
    if pn in PRODUCTS:
        context.user_data["awaiting_restock_file"] = True
        context.user_data["restock_product"] = pn
        await q.edit_message_text(f"📦 RESTOCK: {pn}\n\nSend .txt file.\n/cancel")

async def handle_restock_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.message.from_user
    if u.id != ADMIN_ID or not context.user_data.get("awaiting_restock_file"):
        return
    pn = context.user_data.get("restock_product")
    try:
        f = await update.message.document.get_file()
        c = await f.download_as_bytearray()
        c = c.decode('utf-8', errors='ignore')
        new = [l.strip() for l in c.split('\n') if l.strip() and '@' in l]
        if not new:
            await update.message.reply_text("❌ No emails")
            return
        old = get_stock_count(pn)
        added = add_bulk_to_stock(pn, new)
        await update.message.reply_text(f"✅ Restocked!\n📦 {pn}\n📊 {old}→{get_stock_count(pn)} (+{added})")
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")
    context.user_data["awaiting_restock_file"] = False

async def broadcast_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return
    context.user_data["awaiting_broadcast"] = True
    await update.message.reply_text("📢 **BROADCAST**\n\nSend your message now. It will be sent to ALL users automatically.\n/cancel to abort")

async def message_user_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return
    context.user_data["awaiting_msg_user"] = True
    await update.message.reply_text("💬 **MESSAGE USER**\n\nEnter the USER ID:\n/cancel to abort")

async def admin_addfund_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return
    context.user_data.pop("addfund_target", None)
    context.user_data["awaiting_addfund_user"] = True
    await update.message.reply_text("💰 **ADD FUNDS**\n\nEnter the USER ID:\n/cancel to abort")

async def admin_deductfund_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return
    context.user_data.pop("deduct_target", None)
    context.user_data["awaiting_deduct_user"] = True
    await update.message.reply_text("💸 **DEDUCT FUNDS**\n\nEnter the USER ID:\n/cancel to abort")

async def addfund_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return
    try:
        if len(context.args) < 2:
            await update.message.reply_text("/addfund [id] [amount]")
            return
        tid, amt = int(context.args[0]), int(context.args[1])
        add_user(tid)
        cursor.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amt, tid))
        conn.commit()
        log(tid, "credit", amt, "admin_addfund")
        await update.message.reply_text(f"✅ Added ₦{amt} to {tid}")
    except:
        await update.message.reply_text("Error!")

async def deductfund_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return
    try:
        if len(context.args) < 2:
            await update.message.reply_text("/deduct [id] [amount]")
            return
        tid, amt = int(context.args[0]), int(context.args[1])
        if get_balance(tid) < amt:
            await update.message.reply_text(f"⚠️ Only ₦{get_balance(tid)}")
            return
        cursor.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (amt, tid))
        conn.commit()
        log(tid, "debit", amt, "admin_deduct")
        await update.message.reply_text(f"✅ Deducted ₦{amt}")
    except:
        await update.message.reply_text("Error!")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return
    cursor.execute("SELECT COUNT(*) FROM users")
    u = cursor.fetchone()[0]
    await update.message.reply_text(f"📊 Users: {u}\n📦 Orders: {get_stat('orders')}\n💰 Revenue: ₦{get_stat('revenue')}")

async def pending_deposits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return
    if not pending_approvals:
        await update.message.reply_text("✅ No pending")
        return
    for uid, data in pending_approvals.items():
        kb = [
            [InlineKeyboardButton("✅ Approve", callback_data=f"approve:{uid}")],
            [InlineKeyboardButton("❌ Reject", callback_data=f"reject:{uid}")]
        ]
        try:
            await context.bot.send_photo(
                ADMIN_ID,
                data["photo_id"],
                caption=f"💳 {uid}\n👤 {data.get('full_name','?')}\n🏦 {data['sender_name']}\n🔢 {data['ref']}",
                reply_markup=InlineKeyboardMarkup(kb)
            )
        except:
            pass

async def view_reports(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return
    cursor.execute("SELECT id, user_id, issue_type, description FROM reports WHERE status='open' ORDER BY id DESC LIMIT 10")
    rows = cursor.fetchall()
    if not rows:
        await update.message.reply_text("✅ No reports")
        return
    for rid, uid, it, desc in rows:
        kb = [
            [InlineKeyboardButton("✅ Resolve", callback_data=f"resolve_{rid}")],
            [InlineKeyboardButton("💬 Reply", callback_data=f"reply_{rid}")],
            [InlineKeyboardButton("💰 Add", callback_data=f"addfund_{uid}")]
        ]
        await update.message.reply_text(
            f"📝 #{rid} | 👤 {uid} | 🏷 {it}\n📄 {desc[:200]}",
            reply_markup=InlineKeyboardMarkup(kb)
        )

async def sales_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return
    cursor.execute("SELECT COUNT(*), COALESCE(SUM(amount),0) FROM sales_log WHERE sale_date=date('now')")
    td = cursor.fetchone()
    cursor.execute("SELECT COUNT(*), COALESCE(SUM(amount),0) FROM sales_log WHERE sale_date>=date('now','-7 days')")
    wk = cursor.fetchone()
    await update.message.reply_text(
        f"📈 **SALES**\n\n📆 Today: {td[0]} orders, ₦{td[1]}\n📅 Week: {wk[0]} orders, ₦{wk[1]}\n💰 All: ₦{get_stat('revenue')}"
    )

async def handle_decline_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.message.from_user
    if u.id != ADMIN_ID or "declining_user" not in context.user_data:
        return
    t = update.message.text
    uid = context.user_data.pop("declining_user")
    if t == "/cancel":
        await update.message.reply_text("❌ Cancelled")
        return
    if uid in pending_approvals:
        info = pending_approvals[uid]
        cursor.execute("UPDATE deposits SET status='rejected', decline_reason=? WHERE ref=?", (t, info.get('ref')))
        conn.commit()
        try:
            await context.bot.send_message(uid, f"❌ **PAYMENT DECLINED**\n\n📋 Reason: {t}\n\nFix and try again.")
        except:
            pass
        await update.message.reply_text(f"✅ Declined user {uid}\n📋 {t}")
        pending_approvals.pop(uid, None)

# ================= MAIN BUTTON HANDLER =================

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data

    if d.startswith("pay:"):
        ref = d.split(":")[1]
        context.user_data["payment_ref"] = ref
        context.user_data["awaiting_name"] = True
        await q.edit_message_text(f"💳 REF: {ref}\n\n📝 Send SENDER NAME.")
        return

    if d.startswith("buy_"):
        await buy_product_callback(update, context)
        return
    if d.startswith("confirm_"):
        await confirm_purchase_callback(update, context)
        return

    # Cart buttons
    if d.startswith("addcart_") or d.startswith("rmcart_") or d.startswith("qtyadd_") or d.startswith("qtysub_") or d in ["clearcart", "checkout"]:
        await cart_callback(update, context)
        return

    if d in ["block_menu", "unblock_menu", "blocked_list"]:
        await block_unblock_callback(update, context)
        return
    if d.startswith("clearstock_"):
        await clear_stock_callback(update, context)
        return
    if d.startswith("extract_"):
        await extract_stock_callback(update, context)
        return
    if d.startswith("faq_"):
        await faq_callback(update, context)
        return
    if d == "back_to_faq":
        await back_to_faq(update, context)
        return

    if d.startswith("cat_") or d == "back_to_categories":
        if d == "back_to_categories":
            await back_to_categories(update, context)
        else:
            await category_callback(update, context)
        return

    if d.startswith("report_"):
        if d in ["report_submit", "report_cancel"]:
            await report_submit_callback(update, context)
        else:
            await report_callback(update, context)
        return
    if d.startswith("resolve_"):
        await resolve_report_callback(update, context)
        return
    if d.startswith("reply_"):
        await reply_report_callback(update, context)
        return

    if d.startswith("addfund_"):
        uid = int(d.replace("addfund_", ""))
        context.user_data["approving_user"] = uid
        await context.bot.send_message(ADMIN_ID, f"💰 Amount for user {uid}:")
        return

    if d.startswith("restock_"):
        await restock_callback(update, context)
        return
    if d == "back_to_admin":
        await admin_panel(update, context)
        return

    if "decline" in d:
        parts = d.split(":")
        uid = int(parts[1])
        rt = parts[2] if len(parts) > 2 else "custom"
        reasons = {
            "fake": "Payment proof appears fake.",
            "wrong": "Amount doesn't match.",
            "duplicate": "Proof used before.",
            "unclear": "Screenshot unclear."
        }
        reason = reasons.get(rt)
        if reason:
            if uid in pending_approvals:
                info = pending_approvals[uid]
                cursor.execute("UPDATE deposits SET status='rejected', decline_reason=? WHERE ref=?", (reason, info.get('ref')))
                conn.commit()
                try:
                    await context.bot.send_message(uid, f"❌ **PAYMENT DECLINED**\n\n📋 {reason}\n\nFix and try again.")
                except:
                    pass
                await context.bot.send_message(ADMIN_ID, f"✅ Declined {uid}: {reason}")
                pending_approvals.pop(uid, None)
                try:
                    await q.edit_message_text("❌ Declined")
                except:
                    pass
        else:
            context.user_data["declining_user"] = uid
            await context.bot.send_message(ADMIN_ID, f"✏️ Custom reason for {uid}:")
        return

    p = d.split(":")
    if p[0] == "approve":
        uid = int(p[1])
        if uid not in pending_approvals:
            await q.edit_message_text("⚠️ Already processed!")
            return
        context.user_data["approving_user"] = uid
        await context.bot.send_message(ADMIN_ID, f"💰 **APPROVE**\n\n🆔 {uid}\n\nReply with amount (e.g., 5000):")
        return
    if p[0] == "reject":
        uid = int(p[1])
        if uid not in pending_approvals:
            await q.edit_message_text("❌ No longer pending")
            return
        await context.bot.send_message(
            ADMIN_ID,
            f"❌ **DECLINE**\n\n🆔 {uid}\n\nSelect:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Fake", callback_data=f"decline:{uid}:fake")],
                [InlineKeyboardButton("❌ Wrong Amount", callback_data=f"decline:{uid}:wrong")],
                [InlineKeyboardButton("❌ Duplicate", callback_data=f"decline:{uid}:duplicate")],
                [InlineKeyboardButton("❌ Unclear", callback_data=f"decline:{uid}:unclear")],
                [InlineKeyboardButton("✏️ Custom", callback_data=f"decline:{uid}:custom")]
            ])
        )
        await q.edit_message_text("⏳ Select reason...")
        return

# ================= TEXT HANDLER =================

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.message.from_user
    t = update.message.text

    # Auto-responder
    if not user_support_mode.get(u.id):
        auto_reply = get_auto_reply(t)
        if auto_reply:
            await update.message.reply_text(auto_reply)
            return

    if user_support_mode.get(u.id):
        await handle_support_message(update, context)
        return

    # Report description
    if context.user_data.get("awaiting_report"):
        current = context.user_data.get("report_desc", "")
        context.user_data["report_desc"] = (current + " " + t).strip()
        await update.message.reply_text(
            "✅ Text added! Send more or click Submit.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📝 SUBMIT REPORT", callback_data="report_submit")]])
        )
        return

    # Funding flow
    if context.user_data.get("awaiting_name"):
        context.user_data["sender_name"] = t
        context.user_data["awaiting_name"] = False
        context.user_data["awaiting_proof"] = True
        await update.message.reply_text("📸 Now send SCREENSHOT of your payment.")
        return

    # Admin modes
    if u.id == ADMIN_ID:
        # View balance
        if context.user_data.get("awaiting_view_balance"):
            if t == "/cancel":
                context.user_data.pop("awaiting_view_balance", None)
                await update.message.reply_text("❌ Cancelled")
                return
            try:
                uid = int(t)
                bal = get_balance(uid)
                try:
                    target = await context.bot.get_chat(uid)
                    name = f"{target.full_name} (@{target.username})" if target.username else target.full_name
                except:
                    name = f"User {uid}"
                await update.message.reply_text(f"👤 **{name}**\n🆔 ID: {uid}\n💰 Balance: ₦{bal}")
                context.user_data.pop("awaiting_view_balance", None)
                return
            except:
                await update.message.reply_text("❌ Invalid ID")
                return

        # Block/Unblock
        if context.user_data.get("awaiting_block_user"):
            if t == "/cancel":
                context.user_data.pop("awaiting_block_user", None)
                await update.message.reply_text("❌ Cancelled")
                return
            try:
                uid = int(t)
                if uid in blocked_users:
                    await update.message.reply_text(f"ℹ️ Already blocked.")
                    context.user_data.pop("awaiting_block_user", None)
                    return
                blocked_users.add(uid)
                await update.message.reply_text(f"🚫 User {uid} BLOCKED!")
                try:
                    await context.bot.send_message(uid, "🚫 You have been blocked from submitting payment proofs.")
                except:
                    pass
                context.user_data.pop("awaiting_block_user", None)
                return
            except:
                await update.message.reply_text("❌ Invalid ID")
                return

        if context.user_data.get("awaiting_unblock_user"):
            if t == "/cancel":
                context.user_data.pop("awaiting_unblock_user", None)
                await update.message.reply_text("❌ Cancelled")
                return
            try:
                uid = int(t)
                if uid not in blocked_users:
                    await update.message.reply_text(f"ℹ️ Not blocked.")
                    context.user_data.pop("awaiting_unblock_user", None)
                    return
                blocked_users.discard(uid)
                if uid in fraud_tracker:
                    fraud_tracker[uid] = {"last": 0, "count": 0}
                await update.message.reply_text(f"✅ User {uid} UNBLOCKED!")
                try:
                    await context.bot.send_message(uid, "✅ You have been unblocked!")
                except:
                    pass
                context.user_data.pop("awaiting_unblock_user", None)
                return
            except:
                await update.message.reply_text("❌ Invalid ID")
                return

        if context.user_data.get("awaiting_broadcast"):
            if t == "/cancel":
                context.user_data.pop("awaiting_broadcast", None)
                await update.message.reply_text("❌ Cancelled")
                return
            cursor.execute("SELECT user_id FROM users")
            users = cursor.fetchall()
            if not users:
                await update.message.reply_text("❌ No users!")
                context.user_data.pop("awaiting_broadcast", None)
                return
            sent = 0
            failed = 0
            status_msg = await update.message.reply_text(f"📢 Broadcasting to {len(users)} users...")
            for (uid,) in users:
                try:
                    await context.bot.send_message(uid, f"📢 {t}")
                    sent += 1
                except:
                    failed += 1
                time.sleep(0.05)
            cursor.execute("INSERT INTO broadcast_logs (admin_id, message, total_sent, total_failed) VALUES (?,?,?,?)", (u.id, t[:500], sent, failed))
            conn.commit()
            await status_msg.edit_text(f"✅ Done!\n✅ Sent: {sent}\n❌ Failed: {failed}")
            context.user_data.pop("awaiting_broadcast", None)
            return

        if context.user_data.get("awaiting_msg_user"):
            if t == "/cancel":
                context.user_data.pop("awaiting_msg_user", None)
                await update.message.reply_text("❌ Cancelled")
                return
            try:
                tid = int(t)
                context.user_data["msg_target"] = tid
                context.user_data.pop("awaiting_msg_user", None)
                context.user_data["awaiting_msg_text"] = True
                await update.message.reply_text(f"👤 User: {tid}\n\nSend your message:\n/cancel to abort")
                return
            except:
                await update.message.reply_text("❌ Invalid ID")
                return

        if context.user_data.get("awaiting_msg_text"):
            if t == "/cancel":
                context.user_data.pop("awaiting_msg_text", None)
                context.user_data.pop("msg_target", None)
                await update.message.reply_text("❌ Cancelled")
                return
            tid = context.user_data.pop("msg_target")
            context.user_data.pop("awaiting_msg_text", None)
            try:
                await context.bot.send_message(tid, f"📬 **Message from Admin:**\n\n{t}")
                await update.message.reply_text(f"✅ Sent to {tid}!")
            except:
                await update.message.reply_text(f"❌ Failed to send to {tid}")
            return

        if context.user_data.get("awaiting_addfund_user"):
            if t == "/cancel":
                context.user_data.pop("awaiting_addfund_user", None)
                await update.message.reply_text("❌ Cancelled")
                return
            try:
                tid = int(t)
                context.user_data["addfund_target"] = tid
                context.user_data.pop("awaiting_addfund_user", None)
                context.user_data["awaiting_addfund_amount"] = True
                await update.message.reply_text(f"👤 User: {tid}\n💳 Balance: ₦{get_balance(tid)}\n\nEnter AMOUNT to add:\n/cancel to abort")
                return
            except:
                await update.message.reply_text("❌ Invalid ID")
                return

        if context.user_data.get("awaiting_addfund_amount"):
            if t == "/cancel":
                context.user_data.pop("awaiting_addfund_amount", None)
                context.user_data.pop("addfund_target", None)
                await update.message.reply_text("❌ Cancelled")
                return
            try:
                amt = int(t)
            except:
                await update.message.reply_text("❌ Send valid number")
                return
            if amt <= 0:
                await update.message.reply_text("❌ Positive amount")
                return
            tid = context.user_data.pop("addfund_target")
            context.user_data.pop("awaiting_addfund_amount", None)
            old_bal = get_balance(tid)
            add_user(tid)
            cursor.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amt, tid))
            conn.commit()
            log(tid, "credit", amt, "admin_addfund")
            try:
                await context.bot.send_message(tid, f"💰 Admin added ₦{amt}!\n💳 Balance: ₦{old_bal} → ₦{get_balance(tid)}")
            except:
                pass
            await update.message.reply_text(f"✅ Added ₦{amt} to user {tid}")
            return

        if context.user_data.get("awaiting_deduct_user"):
            if t == "/cancel":
                context.user_data.pop("awaiting_deduct_user", None)
                await update.message.reply_text("❌ Cancelled")
                return
            try:
                tid = int(t)
                bal = get_balance(tid)
                context.user_data["deduct_target"] = tid
                context.user_data.pop("awaiting_deduct_user", None)
                context.user_data["awaiting_deduct_amount"] = True
                await update.message.reply_text(f"👤 User: {tid}\n💳 Balance: ₦{bal}\n\nEnter AMOUNT to deduct (max ₦{bal}):\n/cancel to abort")
                return
            except:
                await update.message.reply_text("❌ Invalid ID")
                return

        if context.user_data.get("awaiting_deduct_amount"):
            if t == "/cancel":
                context.user_data.pop("awaiting_deduct_amount", None)
                context.user_data.pop("deduct_target", None)
                await update.message.reply_text("❌ Cancelled")
                return
            try:
                amt = int(t)
            except:
                await update.message.reply_text("❌ Send valid number")
                return
            if amt <= 0:
                await update.message.reply_text("❌ Positive amount")
                return
            tid = context.user_data.pop("deduct_target")
            context.user_data.pop("awaiting_deduct_amount", None)
            old_bal = get_balance(tid)
            if old_bal < amt:
                await update.message.reply_text(f"⚠️ User only has ₦{old_bal}")
                return
            cursor.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (amt, tid))
            conn.commit()
            log(tid, "debit", amt, "admin_deduct")
            try:
                await context.bot.send_message(tid, f"⚠️ ₦{amt} deducted\n💳 Balance: ₦{old_bal} → ₦{get_balance(tid)}")
            except:
                pass
            await update.message.reply_text(f"✅ Deducted ₦{amt} from user {tid}")
            return

        if "declining_user" in context.user_data:
            await handle_decline_reason(update, context)
            return
        if "replying_to" in context.user_data:
            await handle_admin_reply(update, context)
            return

    # Approve payment
    if u.id == ADMIN_ID and "approving_user" in context.user_data:
        try:
            amt = int(t)
        except:
            await update.message.reply_text("❌ Send valid number")
            return
        if amt <= 0:
            await update.message.reply_text("❌ Positive amount")
            return
        tid = context.user_data.pop("approving_user")
        if tid not in pending_approvals:
            await update.message.reply_text("⚠️ Already processed!")
            return
        info = pending_approvals[tid]
        old_bal = get_balance(tid)
        cursor.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amt, tid))
        conn.commit()
        cursor.execute("UPDATE deposits SET amount=?, status='approved' WHERE ref=?", (amt, info.get('ref')))
        conn.commit()
        new_bal = get_balance(tid)
        log(tid, "credit", amt, "deposit")
        try:
            await context.bot.send_message(tid, f"✅ **PAYMENT APPROVED!**\n\n💰 Amount: ₦{amt}\n💳 Previous Balance: ₦{old_bal}\n💳 New Balance: ₦{new_bal}\n\nThank you! You can now purchase products.")
        except:
            pass
        await update.message.reply_text(f"✅ Approved ₦{amt} for user {tid}\n👤 {info.get('full_name','?')}\n💳 Previous: ₦{old_bal}\n💳 New: ₦{new_bal}")
        pending_approvals.pop(tid, None)
        return

    await update.message.reply_text("❌ Please use the buttons below.")

# ================= PHOTO HANDLER =================

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.message.from_user
    if not context.user_data.get("awaiting_proof"):
        return
    if u.id in blocked_users:
        await update.message.reply_text("❌ Blocked")
        return
    now = time.time()
    if u.id not in fraud_tracker:
        fraud_tracker[u.id] = {"last": 0, "count": 0}
    d = fraud_tracker[u.id]
    if now - d["last"] < 60:
        await update.message.reply_text("⏳ Wait 60s")
        return
    d["last"] = now
    d["count"] += 1
    if d["count"] >= 5:
        blocked_users.add(u.id)
        await update.message.reply_text("❌ Blocked")
        return
    sn = context.user_data.get("sender_name", "Unknown")
    ref = context.user_data.get("payment_ref", generate_ref())
    try:
        cursor.execute("INSERT INTO deposits (user_id, sender_name, ref, status) VALUES (?,?,?,?)", (u.id, sn, ref, "pending"))
        conn.commit()
        pending_approvals[u.id] = {
            "sender_name": sn,
            "photo_id": update.message.photo[-1].file_id,
            "ref": ref,
            "username": u.username,
            "full_name": u.full_name
        }
        kb = [
            [InlineKeyboardButton("✅ Approve", callback_data=f"approve:{u.id}")],
            [InlineKeyboardButton("❌ Reject", callback_data=f"reject:{u.id}")]
        ]
        await context.bot.send_photo(
            ADMIN_ID,
            update.message.photo[-1].file_id,
            caption=f"💳 **NEW DEPOSIT**\n\n👤 {u.full_name}\n📛 @{u.username or 'N/A'}\n🆔 {u.id}\n🏦 {sn}\n🔢 {ref}",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        await update.message.reply_text("✅ Submitted!")
        context.user_data["awaiting_proof"] = False
    except:
        context.user_data["awaiting_proof"] = False

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id == ADMIN_ID and context.user_data.get("awaiting_restock_file"):
        await handle_restock_file(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for k in list(context.user_data.keys()):
        del context.user_data[k]
    await update.message.reply_text("❌ All operations cancelled")

# ================= RUN =================

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("addfund", addfund_command))
    app.add_handler(CommandHandler("deduct", deductfund_command))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("report", report_issue))
    app.add_handler(CommandHandler("msg", message_user_start))
    app.add_handler(CommandHandler("block", block_user_command))
    app.add_handler(CommandHandler("unblock", unblock_command))
    app.add_handler(CommandHandler("blockedlist", blocked_list_command))
    app.add_handler(CommandHandler("balance", view_balance_command))

    # Message handlers
    app.add_handler(MessageHandler(filters.Regex("^💰 Wallet$"), wallet))
    app.add_handler(MessageHandler(filters.Regex("^➕ Fund Wallet$"), fund))
    app.add_handler(MessageHandler(filters.Regex("^📦 Check Stock$"), user_stock))
    app.add_handler(MessageHandler(filters.Regex("^🧾 My History$"), history))
    app.add_handler(MessageHandler(filters.Regex("^💳 My Deposits$"), my_deposits))
    app.add_handler(MessageHandler(filters.Regex("^🛒 Buy Products$"), buy_products_menu))
    app.add_handler(MessageHandler(filters.Regex("^🛒 My Cart$"), view_cart))
    app.add_handler(MessageHandler(filters.Regex("^🤖 Expert Support$"), expert_support))
    app.add_handler(MessageHandler(filters.Regex("^📝 Report Issue$"), report_issue))
    app.add_handler(MessageHandler(filters.Regex("^🤝 Refer & Earn$"), refer_earn_menu))
    app.add_handler(MessageHandler(filters.Regex("^📋 Help & FAQ$"), help_faq))
    app.add_handler(MessageHandler(filters.Regex("^📞 Contact$"), contact_handler))
    app.add_handler(MessageHandler(filters.Regex("^👑 Admin Panel$"), admin_panel))
    app.add_handler(MessageHandler(filters.Regex("^📊 Stats$"), stats))
    app.add_handler(MessageHandler(filters.Regex("^📥 Pending$"), pending_deposits))
    app.add_handler(MessageHandler(filters.Regex("^📝 Reports$"), view_reports))
    app.add_handler(MessageHandler(filters.Regex("^💰 Add Funds$"), admin_addfund_start))
    app.add_handler(MessageHandler(filters.Regex("^💸 Deduct Funds$"), admin_deductfund_start))
    app.add_handler(MessageHandler(filters.Regex("^👤 View Balance$"), view_balance_start))
    app.add_handler(MessageHandler(filters.Regex("^📈 Sales$"), sales_menu))
    app.add_handler(MessageHandler(filters.Regex("^📦 Restock$"), restock_menu))
    app.add_handler(MessageHandler(filters.Regex("^📢 Broadcast$"), broadcast_menu))
    app.add_handler(MessageHandler(filters.Regex("^💬 Message User$"), message_user_start))
    app.add_handler(MessageHandler(filters.Regex("^🚫 Block/Unblock$"), block_unblock_menu))
    app.add_handler(MessageHandler(filters.Regex("^🗑 Clear Stock$"), clear_stock_menu))
    app.add_handler(MessageHandler(filters.Regex("^📤 Extract Stock$"), extract_stock_menu))
    app.add_handler(MessageHandler(filters.Regex("^🔄 User Menu$"), switch_to_user_menu))
    app.add_handler(MessageHandler(filters.Regex("^❌ Exit Support$"), lambda u, c: start(u, c)))

    # Callback handlers
    app.add_handler(CallbackQueryHandler(category_callback, pattern="^cat_"))
    app.add_handler(CallbackQueryHandler(buy_product_callback, pattern="^buy_"))
    app.add_handler(CallbackQueryHandler(confirm_purchase_callback, pattern="^confirm_"))
    app.add_handler(CallbackQueryHandler(add_to_cart_callback, pattern="^addcart_"))
    app.add_handler(CallbackQueryHandler(cart_callback, pattern="^(addcart_|rmcart_|qtyadd_|qtysub_|clearcart|checkout)"))
    app.add_handler(CallbackQueryHandler(back_to_categories, pattern="^back_to_categories$"))
    app.add_handler(CallbackQueryHandler(button, pattern="^(pay:|approve:|reject:|decline:|block_|unblock_|clearstock_|extract_|restock_|report_|resolve_|reply_|addfund_|faq_)"))

    # Text and photo handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    print("=" * 50)
    print("✅ BOT RUNNING!")
    print("🛒 BUY = Instant purchase | ➕ Cart = Add to cart")
    print("💰 Approval shows Previous & New balance")
    print("👤 /balance [id] - View user balance")
    print("📞 Contact: WhatsApp", WHATSAPP_NUMBER)
    print("=" * 50)

    app.run_polling()

if __name__ == "__main__":
    main()
