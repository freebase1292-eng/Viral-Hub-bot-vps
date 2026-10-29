"""
NexusBot — Main Entry Point (flattened single module)
Combines the Telegram bot (webhook/polling) with the Flask admin panel.
Runs on a single Render web service process.
"""
import os
import ssl
import json
import time
import asyncio
import logging
import threading
import urllib.request
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify
)
from jinja2 import DictLoader

from telegram import Update, BotCommandScopeDefault, BotCommandScopeChat
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters
)

from db import (
    Session as DBSession, User, Content, Broadcast,
    Analytics, get_config, set_config, init_db,
    list_sub_admins, add_sub_admin, remove_sub_admin, verify_sub_admin
)
from bot import (
    start_handler, callback_router, user_text_handler,
    admin_file_handler, admin_text_handler, admin_callback_handler,
    ADMIN_TELEGRAM_ID
)
from templates import TEMPLATES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8785727322:AAFwMrQBFR2siX7eudS_n4kQSkMPny0zIiU")
# Auto-derive the public URL: RENDER_EXTERNAL_URL is provided automatically by Render.
# Only set WEBHOOK_URL manually if you use a custom domain instead of *.onrender.com.
WEBHOOK_URL = (os.environ.get("WEBHOOK_URL") or os.environ.get("RENDER_EXTERNAL_URL") or "").strip()
PORT = int(os.environ.get("PORT", 8000))

_required_vars = ["BOT_TOKEN"]
for _var in _required_vars:
    if not os.environ.get(_var):
        logging.warning(f"⚠️ Environment variable {_var} is not set! Bot may not work correctly.")

# Initialize database on startup
try:
    init_db()
except Exception as e:
    logging.warning(f"DB init warning: {e}")


# ══════════════════════════════════════════════════════════════════════
# TELEGRAM BOT APPLICATION
# ══════════════════════════════════════════════════════════════════════

_ptb_app: Application = None
_ptb_app_lock = threading.Lock()


def register_handlers(app: Application) -> None:
    """Register all bot handlers on the given application instance."""
    # ── Admin-only handlers (run BEFORE user handlers) ──────────────
    app.add_handler(CallbackQueryHandler(
        admin_callback_handler,
        pattern="^admin_",
    ), group=0)

    if ADMIN_TELEGRAM_ID:
        admin_filter = filters.User(user_id=ADMIN_TELEGRAM_ID)

        app.add_handler(MessageHandler(
            admin_filter & (
                filters.Document.ALL | filters.VIDEO |
                filters.PHOTO | filters.VOICE |
                filters.AUDIO | filters.ANIMATION
            ),
            admin_file_handler,
        ), group=0)

        app.add_handler(MessageHandler(
            admin_filter & filters.TEXT & ~filters.COMMAND,
            admin_text_handler,
        ), group=0)

        app.add_handler(CommandHandler("admin", start_handler), group=0)

    # ── Regular user handlers ────────────────────────────────────────
    app.add_handler(CommandHandler("start", start_handler), group=1)
    app.add_handler(CallbackQueryHandler(callback_router, pattern="^(?!admin_)"), group=1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, user_text_handler), group=1)


def get_ptb_app() -> Application:
    global _ptb_app
    if _ptb_app is None:
        with _ptb_app_lock:
            if _ptb_app is None:
                _ptb_app = (
                    Application.builder()
                    .token(BOT_TOKEN)
                    .build()
                )
                register_handlers(_ptb_app)
    return _ptb_app


async def init_application():
    """Initialize the shared Application once at startup."""
    ptb_app = get_ptb_app()
    await ptb_app.initialize()

    try:
        await ptb_app.bot.set_my_commands(
            [("start", "🚀 Start Bot")],
            scope=BotCommandScopeDefault()
        )
        if ADMIN_TELEGRAM_ID:
            await ptb_app.bot.set_my_commands(
                [
                    ("start", "🚀 Start Bot"),
                    ("admin", "⚡ Admin Control Panel")
                ],
                scope=BotCommandScopeChat(chat_id=ADMIN_TELEGRAM_ID)
            )
    except Exception as cmd_err:
        logger.warning(f"Failed to set scoped commands: {cmd_err}")

    try:
        from bot import start_alert_worker_if_needed
        start_alert_worker_if_needed(ptb_app.bot)
    except Exception as worker_err:
        logger.warning(f"Failed to start alert worker: {worker_err}")

    logger.info("✅ Shared Application initialized successfully.")


# ══════════════════════════════════════════════════════════════════════
# FLASK ADMIN PANEL
# ══════════════════════════════════════════════════════════════════════

_bot_loop: asyncio.AbstractEventLoop = None
_bot_thread: threading.Thread = None
_event_loop_lock = threading.Lock()

ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "admin123")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")


def _ensure_event_loop():
    global _bot_loop, _bot_thread
    with _event_loop_lock:
        if _bot_loop is not None and _bot_thread is not None and _bot_thread.is_alive():
            return _bot_loop
        if _bot_loop is not None:
            try:
                _bot_loop.call_soon_threadsafe(_bot_loop.stop)
            except Exception:
                pass
        _bot_loop = asyncio.new_event_loop()
        _bot_thread = threading.Thread(
            target=_bot_loop.run_forever, daemon=True, name="bot-event-loop"
        )
        _bot_thread.start()
        logger.info("Background bot event loop started (or restarted).")
        return _bot_loop


def _start_bot_event_loop():
    _ensure_event_loop()


def _run_async(coro):
    loop = _ensure_event_loop()
    fut = asyncio.run_coroutine_threadsafe(coro, loop)
    return fut.result()


def _run_async_background(coro):
    loop = _ensure_event_loop()
    fut = asyncio.run_coroutine_threadsafe(coro, loop)
    def _log_error(f):
        try:
            if not f.cancelled():
                exc = f.exception()
                if exc:
                    logger.error(f"Background async error: {exc}", exc_info=exc)
        except Exception:
            pass
    fut.add_done_callback(_log_error)


app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "nexusbot-dev-secret")
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024  # 2GB max upload

# Serve admin templates from the embedded TEMPLATES dict (zero-folder deploy)
app.jinja_env.loader = DictLoader(TEMPLATES)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def super_admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("login"))
        if session.get("admin_role") != "super_admin":
            flash("Access denied. Super admin only.", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated


@app.route("/admin/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if username == ADMIN_USERNAME and password == ADMIN_SECRET:
            session["admin_logged_in"] = True
            session["admin_role"] = "super_admin"
            flash("Welcome back, Super Admin!", "success")
            return redirect(url_for("dashboard"))
        auth_data = verify_sub_admin(username, password)
        if auth_data:
            session["admin_logged_in"] = True
            session["admin_role"] = "admin"
            session["admin_telegram_id"] = auth_data.get("telegram_id")
            flash(f"Welcome, {username}!", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid credentials", "danger")
    return render_template("admin/login.html")


@app.route("/admin/logout")
@login_required
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/admin")
@app.route("/admin/dashboard")
@login_required
def dashboard():
    db = DBSession()
    try:
        total_users = db.query(User).count()
        banned_users = db.query(User).filter_by(is_banned=True).count()

        apk_downloads = db.query(Analytics).filter_by(event="apk_download").count()
        users_downloaded = db.query(User).filter_by(downloaded_apk=True).count()
        download_rate = round((users_downloaded / total_users * 100), 1) if total_users else 0
        active_content = db.query(Content).filter_by(is_active=True).count()

        recent_broadcasts = (
            db.query(Broadcast)
            .order_by(Broadcast.created_at.desc())
            .limit(5)
            .all()
        )

        daily_stats = []
        for i in range(6, -1, -1):
            day = (datetime.utcnow() - timedelta(days=i)).strftime("%Y-%m-%d")
            count_str = get_config(f"daily_joins_{day}", "0")
            try:
                count = int(count_str)
            except (ValueError, TypeError):
                count = 0
            daily_stats.append((day, count))

        bot_enabled = get_config("bot_enabled", "true") == "true"
        active_apk = db.query(Content).filter_by(is_active=True, content_type="apk").order_by(Content.id.desc()).first()

        return render_template("admin/dashboard.html",
            total_users=total_users,
            banned_users=banned_users,
            apk_downloads=apk_downloads,
            users_downloaded=users_downloaded,
            download_rate=download_rate,
            active_content=active_content,
            recent_broadcasts=recent_broadcasts,
            daily_stats=list(reversed(daily_stats)),
            bot_enabled=bot_enabled,
            active_apk=active_apk,
        )
    finally:
        db.close()


@app.route("/admin/bot/toggle", methods=["POST"])
@login_required
def toggle_bot():
    current = get_config("bot_enabled", "true")
    new_val = "false" if current == "true" else "true"
    set_config("bot_enabled", new_val)
    status = "enabled ✅" if new_val == "true" else "disabled 🔴"
    flash(f"Bot is now {status}", "success")
    return redirect(url_for("dashboard"))


@app.route("/admin/webhook/register", methods=["POST"])
@login_required
@super_admin_required
def register_webhook():
    """Re-register the bot webhook."""
    try:
        webhook_path = f"{WEBHOOK_URL}/webhook/{BOT_TOKEN}"
        data_json = json.dumps({"url": webhook_path, "drop_pending_updates": True}).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
            data=data_json,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("ok"):
                flash(f"✅ Webhook registered: {webhook_path}", "success")
            else:
                flash(f"❌ Webhook error: {data.get('description')}", "danger")
    except Exception as e:
        flash(f"❌ Failed: {e}", "danger")
    return redirect(url_for("dashboard"))


@app.route("/admin/content")
@login_required
def content_list():
    db = DBSession()
    try:
        contents = db.query(Content).order_by(Content.order_index.asc(), Content.id.asc()).all()
        return render_template("admin/content.html", contents=contents)
    finally:
        db.close()


@app.route("/admin/content/add", methods=["GET", "POST"])
@login_required
def content_add():
    if request.method == "POST":
        db = DBSession()
        try:
            content_type = request.form.get("content_type")
            file_id = request.form.get("file_id", "").strip()
            file_name = request.form.get("file_name", "").strip()
            caption = request.form.get("caption", "").strip()
            text_content = request.form.get("text_content", "").strip()
            version = request.form.get("version", "").strip()
            changelog = request.form.get("changelog", "").strip()
            order_index = int(request.form.get("order_index", 0))

            # If adding APK, archive old ones
            if content_type == "apk":
                db.query(Content).filter_by(content_type="apk", is_active=True).update({"is_active": False})

            item = Content(
                content_type=content_type,
                file_id=file_id or None,
                file_name=file_name or None,
                caption=caption or None,
                text_content=text_content or None,
                version=version or None,
                changelog=changelog or None,
                order_index=order_index,
                is_active=True,
            )
            db.add(item)
            db.commit()
            flash(f"✅ Content added successfully!", "success")
            return redirect(url_for("content_list"))
        except Exception as e:
            db.rollback()
            flash(f"❌ Error: {e}", "danger")
        finally:
            db.close()
    return render_template("admin/content_form.html", content=None, action="Add")


@app.route("/admin/content/edit/<int:cid>", methods=["GET", "POST"])
@login_required
def content_edit(cid):
    db = DBSession()
    try:
        item = db.get(Content, cid)
        if not item:
            flash("Content not found", "danger")
            return redirect(url_for("content_list"))

        if request.method == "POST":
            old_type = item.content_type
            new_type = request.form.get("content_type")
            item.content_type = new_type
            item.file_id = request.form.get("file_id", "").strip() or None
            item.file_name = request.form.get("file_name", "").strip() or None
            item.caption = request.form.get("caption", "").strip() or None
            item.text_content = request.form.get("text_content", "").strip() or None
            item.version = request.form.get("version", "").strip() or None
            item.changelog = request.form.get("changelog", "").strip() or None
            item.order_index = int(request.form.get("order_index", 0))

            # Archive other APKs if replacing with new APK
            if new_type == "apk" and old_type != "apk":
                db.query(Content).filter(
                    Content.content_type == "apk",
                    Content.is_active == True,
                    Content.id != cid
                ).update({"is_active": False})

            db.commit()
            flash("✅ Content updated!", "success")
            return redirect(url_for("content_list"))

        return render_template("admin/content_form.html", content=item, action="Edit")
    finally:
        db.close()


@app.route("/admin/content/toggle/<int:cid>", methods=["POST"])
@login_required
def content_toggle(cid):
    db = DBSession()
    try:
        item = db.get(Content, cid)
        if item:
            item.is_active = not item.is_active
            db.commit()
            status = "enabled" if item.is_active else "disabled"
            flash(f"Content {status}.", "success")
    finally:
        db.close()
    return redirect(url_for("content_list"))


@app.route("/admin/content/delete/<int:cid>", methods=["POST"])
@login_required
def content_delete(cid):
    db = DBSession()
    try:
        item = db.get(Content, cid)
        if item:
            db.delete(item)
            db.commit()
            flash("🗑️ Content deleted.", "success")
    finally:
        db.close()
    return redirect(url_for("content_list"))


@app.route("/admin/apk")
@login_required
def apk_manager():
    db = DBSession()
    try:
        all_apks = (
            db.query(Content)
            .filter_by(content_type="apk")
            .order_by(Content.id.desc())
            .all()
        )
        active_apk = next((a for a in all_apks if a.is_active), None)
        archived_apks = [a for a in all_apks if not a.is_active]
        return render_template("admin/apk.html",
            active_apk=active_apk,
            archived_apks=archived_apks
        )
    finally:
        db.close()


@app.route("/admin/apk/replace", methods=["POST"])
@login_required
def apk_replace():
    """Replace active APK — archive old, activate new."""
    db = DBSession()
    try:
        file_id = request.form.get("file_id", "").strip()
        file_name = request.form.get("file_name", "App.apk").strip()
        version = request.form.get("version", "1.0").strip()
        changelog = request.form.get("changelog", "").strip()

        if not file_id:
            flash("❌ File ID is required (forward the APK to @userinfobot or check below)", "danger")
            return redirect(url_for("apk_manager"))

        db.query(Content).filter_by(content_type="apk", is_active=True).update({"is_active": False})

        new_apk = Content(
            content_type="apk",
            file_id=file_id,
            file_name=file_name,
            version=version,
            changelog=changelog,
            is_active=True,
        )
        db.add(new_apk)
        db.commit()
        flash(f"✅ APK v{version} is now active! Old APKs archived.", "success")
    except Exception as e:
        db.rollback()
        flash(f"❌ Error: {e}", "danger")
    finally:
        db.close()
    return redirect(url_for("apk_manager"))


@app.route("/admin/broadcast")
@login_required
def broadcast_list():
    db = DBSession()
    try:
        broadcasts = db.query(Broadcast).order_by(Broadcast.created_at.desc()).limit(50).all()
        user_count = db.query(User).filter_by(is_banned=False).count()
        active_apk = db.query(Content).filter_by(is_active=True, content_type="apk").order_by(Content.id.desc()).first()
        return render_template("admin/broadcast.html",
            broadcasts=broadcasts,
            user_count=user_count,
            active_apk=active_apk,
        )
    finally:
        db.close()


@app.route("/admin/broadcast/send", methods=["POST"])
@login_required
def broadcast_send():
    db = DBSession()
    try:
        msg_type = request.form.get("message_type", "text")
        content_text = request.form.get("content_text", "").strip() or None
        file_id = request.form.get("file_id", "").strip() or None
        caption = request.form.get("caption", "").strip() or None
        has_apk_button = request.form.get("has_apk_button") == "on"
        apk_button_text = request.form.get("apk_button_text", "⬇️ Download App").strip()

        if msg_type == "text" and not content_text:
            flash("❌ Text content is required for text broadcasts.", "danger")
            return redirect(url_for("broadcast_list"))
        if msg_type != "text" and not file_id:
            flash("❌ File ID is required for media broadcasts.", "danger")
            return redirect(url_for("broadcast_list"))

        user_count = db.query(User).filter_by(is_banned=False).count()

        broadcast = Broadcast(
            message_type=msg_type,
            content_text=content_text,
            file_id=file_id,
            caption=caption,
            has_apk_button=has_apk_button,
            apk_button_text=apk_button_text,
            total_users=user_count,
            status="pending",
        )
        db.add(broadcast)
        db.commit()
        broadcast_id = broadcast.id

        def run_broadcast_thread(bid, token):
            from broadcast import execute_broadcast
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(execute_broadcast(bid, token))
            except Exception as thread_err:
                logger.error(f"Thread broadcast error: {thread_err}")
            finally:
                loop.close()

        thread = threading.Thread(
            target=run_broadcast_thread,
            args=(broadcast_id, BOT_TOKEN),
            daemon=True
        )
        thread.start()

        flash(f"🚀 Broadcast #{broadcast_id} triggered in background! Sending to {user_count} users...", "success")

    except Exception as e:
        db.rollback()
        flash(f"❌ Error: {e}", "danger")
    finally:
        db.close()
    return redirect(url_for("broadcast_list"))


@app.route("/admin/broadcast/status/<int:bid>")
@login_required
def broadcast_status(bid):
    """API endpoint for live broadcast progress."""
    db = DBSession()
    try:
        b = db.get(Broadcast, bid)
        if not b:
            return jsonify({"error": "Not found"}), 404
        progress = round((b.sent_count / b.total_users * 100) if b.total_users else 0, 1)
        return jsonify({
            "id": b.id,
            "status": b.status,
            "total": b.total_users,
            "sent": b.sent_count,
            "failed": b.failed_count,
            "progress": progress,
        })
    finally:
        db.close()


@app.route("/admin/users")
@login_required
def users_list():
    db = DBSession()
    try:
        page = int(request.args.get("page", 1))
        per_page = 50
        search = request.args.get("search", "").strip()

        query = db.query(User)
        if search:
            query = query.filter(
                (User.username.ilike(f"%{search}%")) |
                (User.first_name.ilike(f"%{search}%"))
            )

        total = query.count()
        users = (
            query.order_by(User.joined_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
        pages = (total + per_page - 1) // per_page

        return render_template("admin/users.html",
            users=users, page=page, pages=pages, total=total, search=search
        )
    finally:
        db.close()


@app.route("/admin/users/ban/<int:uid>", methods=["POST"])
@login_required
def user_ban(uid):
    db = DBSession()
    try:
        user = db.get(User, uid)
        if user:
            user.is_banned = not user.is_banned
            db.commit()
            action = "banned" if user.is_banned else "unbanned"
            flash(f"User {uid} {action}.", "success")
    finally:
        db.close()
    return redirect(url_for("users_list"))


@app.route("/admin/admins")
@login_required
@super_admin_required
def admin_list():
    sub_admins = list_sub_admins()
    return render_template("admin/admins.html", sub_admins=sub_admins)


@app.route("/admin/admins/add", methods=["POST"])
@login_required
@super_admin_required
def admin_add():
    telegram_id = request.form.get("telegram_id", "").strip()
    name = request.form.get("name", "").strip()
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()

    if not telegram_id or not telegram_id.isdigit():
        flash("Valid Telegram ID is required.", "danger")
        return redirect(url_for("admin_list"))

    add_sub_admin(int(telegram_id), name or "Sub Admin", username or "", password, added_by=ADMIN_TELEGRAM_ID)
    flash(f"Sub-admin '{name or telegram_id}' added.", "success")
    return redirect(url_for("admin_list"))


@app.route("/admin/admins/remove/<int:tid>", methods=["POST"])
@login_required
@super_admin_required
def admin_remove(tid):
    remove_sub_admin(tid)
    flash(f"Sub-admin {tid} removed.", "success")
    return redirect(url_for("admin_list"))


@app.route("/admin/settings", methods=["GET", "POST"])
@login_required
def settings():
    config_keys = [
        "welcome_text", "welcome_gif_id",
        "maintenance_message", "apk_button_text",
        "demo_closing_text", "install_guide_text",
    ]
    if request.method == "POST":
        try:
            for key in config_keys:
                value = request.form.get(key, "").strip()
                set_config(key, value)
            flash("✅ Settings saved!", "success")
        except Exception as e:
            flash(f"❌ Error: {e}", "danger")
        return redirect(url_for("settings"))

    configs = {key: get_config(key, "") for key in config_keys}
    return render_template("admin/settings.html", configs=configs)


@app.route(f"/webhook/<token>", methods=["POST"])
def telegram_webhook(token):
    """Receive updates from Telegram via webhook."""
    if token != BOT_TOKEN:
        return "Forbidden", 403

    from telegram import Update

    data = request.get_json(force=True)
    ptb_app = get_ptb_app()

    async def process():
        try:
            update = Update.de_json(data, ptb_app.bot)
            await ptb_app.process_update(update)
        except Exception as e:
            logger.error(f"Error processing update: {e}", exc_info=True)

    _run_async_background(process())

    return "ok", 200


@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "NexusBot"}), 200


@app.route("/")
def index():
    return redirect(url_for("login"))


# ══════════════════════════════════════════════════════════════════════
# DUAL EXECUTION MODE (Polling for Local, Webhook for Render)
# ══════════════════════════════════════════════════════════════════════

def start_bot_engine():
    # Check if WEBHOOK_URL is local or empty
    is_local = (
        not WEBHOOK_URL or
        "localhost" in WEBHOOK_URL or
        "127.0.0.1" in WEBHOOK_URL or
        "your-bot-name" in WEBHOOK_URL
    )

    if is_local:
        logging.info("💻 Local environment detected. Starting bot in POLLING MODE...")

        def run_polling_thread():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            ptb_app = get_ptb_app()

            # Delete any existing webhook on Telegram before starting polling
            try:
                loop.run_until_complete(ptb_app.bot.delete_webhook(drop_pending_updates=True))
                logging.info("🧹 Cleared old webhook from Telegram.")
            except Exception as e:
                logging.warning(f"Failed to clear webhook: {e}")

            loop.run_until_complete(init_application())
            loop.run_until_complete(ptb_app.start())
            loop.run_until_complete(ptb_app.updater.start_polling())
            logging.info("🤖 Bot is polling for updates successfully!")
            loop.run_forever()

        t = threading.Thread(target=run_polling_thread, daemon=True)
        t.start()

    else:
        # Production mode (Render) -> register webhook
        webhook_path = f"{WEBHOOK_URL.rstrip('/')}/webhook/{BOT_TOKEN}"
        api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
        logging.info(f"🚀 Production environment detected. Registering Webhook: {webhook_path}")

        try:
            data = json.dumps({
                "url": webhook_path,
                "drop_pending_updates": True,
                "allowed_updates": ["message", "callback_query"]
            }).encode("utf-8")

            req = urllib.request.Request(
                api_url,
                data=data,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                if res_data.get("ok"):
                    logging.info(f"✅ Webhook registered successfully: {webhook_path}")
                else:
                    logging.warning(f"❌ Telegram setWebhook failed: {res_data.get('description')}")
        except Exception as err:
            logging.warning(f"❌ Failed to connect to Telegram setWebhook API: {err}")


start_bot_engine()

# ── Initialize shared bot Application on background event loop ─────
_start_bot_event_loop()
try:
    _run_async(init_application())
except Exception as e:
    logging.warning(f"Application init warning: {e}")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False)