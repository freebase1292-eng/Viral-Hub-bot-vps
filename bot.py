"""
NexusBot — Telegram Bot Logic (flattened single module)
Merges: helpers, keyboards, start, callbacks, content delivery, and the
Telegram admin control panel into one file for easy deployment.
"""
import logging
import os
import random
import string
import asyncio
from datetime import datetime, date

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from telegram.error import BadRequest

from db import (
    Session, User, Analytics, Content, Broadcast,
    BotConfig, get_config, set_config, fb_request
)

logger = logging.getLogger(__name__)

# Admin Telegram User ID — only this user can access admin functions
ADMIN_TELEGRAM_ID = int(os.environ.get("ADMIN_TELEGRAM_ID", "8756082851"))


# ══════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════

STREAK_EMOJIS = ["🔥", "🔥🔥", "🔥🔥🔥", "💎", "👑", "🏆", "⚡", "🌟"]


def get_streak_emoji(streak: int) -> str:
    """Get emoji based on streak count."""
    idx = min(streak - 1, len(STREAK_EMOJIS) - 1)
    return STREAK_EMOJIS[max(0, idx)]


def format_streak_message(streak: int) -> str:
    """Format a streak message for the user."""
    emoji = get_streak_emoji(streak)
    if streak == 1:
        return f"{emoji} Day 1 streak — you're just getting started!"
    elif streak < 7:
        return f"{emoji} {streak}-day streak — keep it going!"
    elif streak < 30:
        return f"{emoji} {streak}-day streak — you're on fire!"
    else:
        return f"{emoji} {streak}-day streak — LEGENDARY status! 👑"


def update_streak(user) -> bool:
    """Update user streak. Returns True if streak was incremented."""
    today = date.today()
    if user.streak_last_date is None:
        user.streak_count = 1
        user.streak_last_date = datetime.utcnow()
        return True
    last_date = user.streak_last_date.date() if isinstance(user.streak_last_date, datetime) else user.streak_last_date
    delta = (today - last_date).days
    if delta == 0:
        return False  # Already updated today
    elif delta == 1:
        user.streak_count += 1
        user.streak_last_date = datetime.utcnow()
        return True
    else:
        user.streak_count = 1  # Reset streak
        user.streak_last_date = datetime.utcnow()
        return True


def escape_md(text: str) -> str:
    """Escape Markdown V2 special characters."""
    special = r'_*[]()~`>#+-=|{}.!'
    return ''.join(f'\\{c}' if c in special else c for c in text)


def track_message(context, message_or_id):
    """Record a sent message ID in user_data for reference."""
    if not context or not hasattr(context, "user_data") or context.user_data is None:
        return
    if "bot_message_ids" not in context.user_data:
        context.user_data["bot_message_ids"] = []

    msg_id = message_or_id.message_id if hasattr(message_or_id, "message_id") else message_or_id
    if msg_id not in context.user_data["bot_message_ids"]:
        context.user_data["bot_message_ids"].append(msg_id)


# ══════════════════════════════════════════════════════════════════════
# KEYBOARDS
# ══════════════════════════════════════════════════════════════════════

def user_reply_keyboard() -> ReplyKeyboardMarkup:
    """Return the persistent bottom Reply Keyboard."""
    return ReplyKeyboardMarkup([
        [KeyboardButton("📱 Download APK")],
        [KeyboardButton("🌸 See Demo")]
    ], resize_keyboard=True, is_persistent=True)


def content_keyboard(apk_version: str = None, apk_button_text: str = "Download APK") -> InlineKeyboardMarkup:
    """Content screen buttons."""
    buttons = []
    # Button 1: Download APK
    btn_text = f"📱 {apk_button_text}"
    if apk_version:
        btn_text = f"📱 {apk_button_text} v{apk_version}"
    buttons.append([InlineKeyboardButton(btn_text, callback_data="download_apk")])

    # Button 2: See Demo
    buttons.append([InlineKeyboardButton("🌸 See Demo", callback_data="show_content")])
    return InlineKeyboardMarkup(buttons)


def apk_download_keyboard(apk_version: str, apk_button_text: str = "⬇️ Download App") -> InlineKeyboardMarkup:
    """Standalone APK download button (used in broadcasts)."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{apk_button_text} v{apk_version}", callback_data="download_apk")]
    ])


def back_to_content_keyboard() -> InlineKeyboardMarkup:
    """Button to go back to content after downloading APK."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Back to Content", callback_data="show_content")],
    ])


def stats_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎁 See Content Again", callback_data="show_content")],
    ])


def admin_panel_keyboard(demo_on: bool = True, bot_active: bool = True, role: str = "super_admin") -> InlineKeyboardMarkup:
    demo_status = "🟢 Demo: ON" if demo_on else "🔴 Demo: OFF"
    bot_status = "🟢 Bot: ACTIVE" if bot_active else "🟡 Bot: MAINTENANCE"

    buttons = [
        [InlineKeyboardButton("📢 Broadcast Media 📢", callback_data="admin_prompt_broadcast_media")],
        [InlineKeyboardButton("📝 Send Text Broadcast 📝", callback_data="admin_prompt_send_text")],
        [InlineKeyboardButton("📲 Send APK To All 📲", callback_data="admin_broadcast_apk")],
        [
            InlineKeyboardButton(demo_status, callback_data="admin_toggle_demo"),
            InlineKeyboardButton(bot_status, callback_data="admin_toggle_maintenance")
        ],
        [
            InlineKeyboardButton("📱 Set APK 📱", callback_data="admin_prompt_set_apk"),
            InlineKeyboardButton("🗑️ Remove APK 🗑️", callback_data="admin_remove_apk")
        ],
        [
            InlineKeyboardButton("📛 APK Name 📛", callback_data="admin_prompt_apk_name"),
            InlineKeyboardButton("💬 APK Caption 💬", callback_data="admin_prompt_apk_caption")
        ],
        [
            InlineKeyboardButton("📝 Welcome 📝", callback_data="admin_prompt_welcome"),
            InlineKeyboardButton("🌸 Set Demo 🌸", callback_data="admin_prompt_demo"),
        ],
        [
            InlineKeyboardButton("📋 Manage Demo 📋", callback_data="admin_manage_demo"),
            InlineKeyboardButton("🗑️ Reset Demo 🗑️", callback_data="admin_reset_demo"),
        ],
        [
            InlineKeyboardButton("💬 Demo Msg 💬", callback_data="admin_prompt_demo_msg"),
            InlineKeyboardButton("🔗 Demo Link 🔗", callback_data="admin_prompt_demo_link"),
        ],
        [
            InlineKeyboardButton("📱 Add APK to Demo 📱", callback_data="admin_add_apk_to_demo"),
            InlineKeyboardButton("🖼️ Set App Icon 🖼️", callback_data="admin_prompt_app_icon"),
        ],
    ]

    if role == "super_admin":
        buttons.append([InlineKeyboardButton("👥 Manage Admins 👥", callback_data="admin_manage_sub_admins")])

    buttons += [
        [
            InlineKeyboardButton("❓ How to use ❓", callback_data="admin_how_to_use"),
            InlineKeyboardButton("📊 Get Report 📊", callback_data="admin_get_report")
        ],
        [
            InlineKeyboardButton("📖 Admin Guide 📖", callback_data="admin_guide"),
            InlineKeyboardButton("❌ Close Panel", callback_data="admin_cancel")
        ]
    ]
    return InlineKeyboardMarkup(buttons)


# ══════════════════════════════════════════════════════════════════════
# CONTENT DELIVERY
# ══════════════════════════════════════════════════════════════════════

async def deliver_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Deliver all active content to the user in order.
    Order: text → image(s) → video(s) → voice → link(s) → APK (at the end).
    """
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    session = Session()
    try:
        user = session.get(User, user_id)
        if not user:
            return

        user.last_active = datetime.utcnow()

        # Log analytics
        session.add(Analytics(user_id=user_id, event="content_view"))
        session.commit()

        # Fetch all active content ordered by type priority and order_index
        contents = (
            session.query(Content)
            .filter_by(is_active=True)
            .order_by(Content.order_index.asc(), Content.id.asc())
            .all()
        )

        # Separate active APK for the button
        active_apk = next((c for c in contents if c.content_type == "apk"), None)

        # Check if demo content delivery is enabled
        demo_enabled = get_config("demo_enabled", "true").lower() == "true"

        # Smooth UX: typing indicator before content arrives
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")

        # Deliver each piece in order if demo is ON
        for item in contents:
            if not demo_enabled and item.content_type != "apk":
                continue  # Skip general content/demo items if demo toggle is OFF

            try:
                if item.content_type == "text":
                    msg = await context.bot.send_message(
                        chat_id=chat_id,
                        text=item.text_content or item.caption or "—",
                        parse_mode=ParseMode.MARKDOWN,
                    )
                    track_message(context, msg)

                elif item.content_type == "image":
                    msg = await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=item.file_id,
                        caption=item.caption or "",
                        parse_mode=ParseMode.MARKDOWN,
                    )
                    track_message(context, msg)

                elif item.content_type == "video":
                    msg = await context.bot.send_video(
                        chat_id=chat_id,
                        video=item.file_id,
                        caption=item.caption or "",
                        parse_mode=ParseMode.MARKDOWN,
                        supports_streaming=True,
                    )
                    track_message(context, msg)

                elif item.content_type == "voice":
                    msg = await context.bot.send_voice(
                        chat_id=chat_id,
                        voice=item.file_id,
                        caption=item.caption or "",
                    )
                    track_message(context, msg)

                elif item.content_type == "audio":
                    msg = await context.bot.send_audio(
                        chat_id=chat_id,
                        audio=item.file_id,
                        caption=item.caption or "",
                    )
                    track_message(context, msg)

                elif item.content_type == "apk":
                    continue

                elif item.content_type == "apk_demo":
                    await send_apk_to_user(update, context)

                elif item.content_type == "link":
                    link_kb = InlineKeyboardMarkup([
                        [InlineKeyboardButton(item.link_text or "🔗 Open Link", url=item.link_url or item.text_content)]
                    ])
                    msg = await context.bot.send_message(
                        chat_id=chat_id,
                        text=item.caption or "🔗 *Click the button below:*",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=link_kb,
                    )
                    track_message(context, msg)
                    continue

                if item.link_url:
                    link_kb = InlineKeyboardMarkup([
                        [InlineKeyboardButton(item.link_text or "🔗 Open Link", url=item.link_url)]
                    ])
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="🔗 *Related link:*",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=link_kb,
                    )

            except Exception as e:
                logger.error(f"Error sending content item {item.id}: {e}")
                continue

        if active_apk and not user.downloaded_apk:
            total_downloads = session.query(Analytics).filter_by(event="apk_download").count()
            simple_reminder = (
                f"📱 *{active_apk.file_name or 'App'}*\n"
                f"📌 Version: *{active_apk.version}*\n"
                f"👥 *{total_downloads} users* have downloaded this"
            )
            reminder_msg = await context.bot.send_message(
                chat_id=chat_id,
                text=simple_reminder,
                parse_mode=ParseMode.MARKDOWN,
            )
            track_message(context, reminder_msg)

    except Exception as e:
        logger.error(f"Error in deliver_content: {e}", exc_info=True)
    finally:
        session.close()


async def send_apk_to_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send the latest APK file to the user with social proof and install guide."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    session = Session()
    try:
        active_apk = (
            session.query(Content)
            .filter_by(is_active=True, content_type="apk")
            .order_by(Content.id.desc())
            .first()
        )

        if not active_apk:
            msg = await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ No APK available yet. Check back soon! 🔔",
            )
            track_message(context, msg)
            return
        user = session.get(User, user_id)

        total_downloads = session.query(Analytics).filter_by(event="apk_download").count()

        if user:
            if not user.downloaded_apk:
                user.downloaded_apk = True
            user.last_active = datetime.utcnow()
        session.add(Analytics(user_id=user_id, event="apk_download",
                              metadata_={"version": active_apk.version}))
        session.commit()

        social_proof = f"👥 *{total_downloads + 1} users* have downloaded this APK"
        caption_parts = [
            f"📱 *{active_apk.file_name or 'App'}*",
            f"📌 Version: *{active_apk.version}*" if active_apk.version else "",
            f"\n{social_proof}",
        ]
        caption = "\n".join(p for p in caption_parts if p)

        app_icon_id = get_config("apk_icon_file_id", "")
        if app_icon_id:
            try:
                icon_msg = await context.bot.send_photo(
                    chat_id=chat_id, photo=app_icon_id,
                    caption="📦 *Preparing your download...*",
                    parse_mode=ParseMode.MARKDOWN
                )
                track_message(context, icon_msg)
            except Exception:
                pass

        await context.bot.send_chat_action(chat_id=chat_id, action="upload_document")

        doc_msg = await context.bot.send_document(
            chat_id=chat_id,
            document=active_apk.file_id,
            caption=caption,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_to_content_keyboard(),
        )
        track_message(context, doc_msg)

    except Exception as e:
        logger.error(f"Error in send_apk_to_user: {e}", exc_info=True)
        err_msg = await context.bot.send_message(chat_id=chat_id, text="❌ Couldn't send the APK. Please try again.")
        track_message(context, err_msg)
    finally:
        session.close()


# ══════════════════════════════════════════════════════════════════════
# START HANDLER
# ══════════════════════════════════════════════════════════════════════

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command — register user and show welcome."""
    user_tg = update.effective_user
    chat_id = update.effective_chat.id

    # Check maintenance mode
    if get_config("bot_enabled", "true").lower() != "true":
        maint_msg = get_config(
            "maintenance_message",
            "🔧 We're upgrading the experience. Back soon! 💫"
        )
        await update.message.reply_text(maint_msg)
        return

    session = Session()
    try:
        # --- ADMIN FLOW: Show Admin Panel directly ---
        if is_admin(user_tg.id):
            text, keyboard = get_admin_panel_details(user_id=user_tg.id)
            await update.message.reply_text(
                text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )
            return

        # --- USER FLOW ---
        user = session.get(User, user_tg.id)
        is_new = user is None

        if is_new:
            user = User(
                id=user_tg.id,
                username=user_tg.username,
                first_name=user_tg.first_name,
                last_name=user_tg.last_name,
                language_code=user_tg.language_code or "en",
                streak_count=1,
                streak_last_date=datetime.utcnow(),
            )
            session.add(user)

            # Log analytics
            session.add(Analytics(user_id=user_tg.id, event="start", metadata_={"is_new": True}))
            track_daily_join()
            session.flush()

            # Safe non-blocking log notification to Admin (does not freeze user /start)
            enable_join_alerts = os.environ.get("ENABLE_JOIN_ALERTS", "false").lower() == "true"
            if ADMIN_TELEGRAM_ID and enable_join_alerts:
                async def _send_admin_alert():
                    try:
                        name_str = f"{user_tg.first_name or ''} {user_tg.last_name or ''}".strip()
                        username_str = f"@{user_tg.username}" if user_tg.username else "—"
                        await context.bot.send_message(
                            chat_id=ADMIN_TELEGRAM_ID,
                            text=(
                                f"🆕 *New user*\n\n"
                                f"👤 Name: *{name_str or 'Unknown'}*\n"
                                f"🆔 ID: `{user_tg.id}`\n"
                                f"📛 Username: {username_str}"
                            ),
                            parse_mode=ParseMode.MARKDOWN,
                        )
                    except Exception:
                        pass
                asyncio.create_task(_send_admin_alert())

        else:
            # Returning user — update info and streak
            user.username = user_tg.username
            user.first_name = user_tg.first_name
            user.last_name = user_tg.last_name
            user.last_active = datetime.utcnow()
            update_streak(user)

        session.commit()

        # Dock the persistent custom Reply Keyboard at the bottom of the Telegram chat immediately
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text="🤖 *Accessing premium portal...*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=user_reply_keyboard()
            )
        except Exception as kb_err:
            logger.error(f"Failed to dock custom reply keyboard: {kb_err}")

        await deliver_content(update, context)

    except Exception as e:
        logger.error(f"Error in start_handler: {e}", exc_info=True)
        await update.message.reply_text("Something went wrong. Please try again with /start")
    finally:
        session.close()


def track_daily_join():
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    key = f"daily_joins_{today_str}"
    current = get_config(key, "0")
    try:
        set_config(key, str(int(current) + 1))
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════
# CALLBACK ROUTER
# ══════════════════════════════════════════════════════════════════════

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route all inline button callbacks."""
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "download_apk":
        await send_apk_to_user(update, context)
    elif data == "my_stats":
        await _show_stats(update, context)
    elif data == "show_content":
        await deliver_content(update, context)
    else:
        logger.warning(f"Unknown callback data: {data}")


async def _show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user stats: streak and APK download status."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    session = Session()
    try:
        user = session.get(User, user_id)
        if not user:
            await context.bot.send_message(chat_id=chat_id, text="⚠️ Use /start first!")
            return

        downloaded_emoji = "✅" if user.downloaded_apk else "❌"
        stats_intro = f"📊 *Our Relationship Status, {user.get_display_name()}!*\n"
        stats_intro += f"{'─' * 25}\n"

        session2 = Session()
        try:
            total_downloads = session2.query(Analytics).filter_by(event="apk_download").count()
        finally:
            session2.close()

        if user.downloaded_apk:
            stats_intro += f"📱 APK Downloaded: *Yes* {downloaded_emoji}\n"
        else:
            stats_intro += f"📱 APK Downloaded: *Not yet* — tap 📱 Download APK below!\n"
        stats_intro += (
            f"👥 Total APK Downloads: *{total_downloads} users*\n"
            f"🔥 Visits Streak: *{user.streak_count} days*\n"
            f"\n💡 _Keep visiting to stay updated!_"
        )
        msg = stats_intro

        await context.bot.send_message(
            chat_id=chat_id,
            text=msg,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=stats_keyboard(),
        )

    except Exception as e:
        logger.error(f"Error in _show_stats: {e}", exc_info=True)
    finally:
        session.close()


async def user_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text message inputs matching the custom bottom Reply Keyboard buttons."""
    message = update.message
    if not message or not message.text:
        return

    text = message.text.strip()

    if "Download APK" in text or "download apk" in text:
        await send_apk_to_user(update, context)
    elif "Demo" in text or "demo" in text or "See Content" in text or "Content Again" in text:
        await deliver_content(update, context)
    elif "changed my mind" in text.lower():
        await _handle_yes(update, context)


# ══════════════════════════════════════════════════════════════════════
# ADMIN TELEGRAM HANDLERS
# ══════════════════════════════════════════════════════════════════════

def is_admin(user_id: int) -> bool:
    if ADMIN_TELEGRAM_ID != 0 and user_id == ADMIN_TELEGRAM_ID:
        return True
    data = fb_request("GET", f"sub_admins/{user_id}")
    return bool(data and data.get("is_active", False))


def get_admin_role(user_id: int) -> str:
    if ADMIN_TELEGRAM_ID != 0 and user_id == ADMIN_TELEGRAM_ID:
        return "super_admin"
    return "admin"


async def _make_sub_admin(message, target_id, target_name, target_username, adder_id):
    fb_request("PUT", f"sub_admins/{target_id}", {
        "telegram_id": target_id,
        "name": target_name or "Sub Admin",
        "username": target_username or "",
        "role": "admin",
        "added_by": adder_id,
        "added_at": datetime.utcnow().isoformat(),
        "is_active": True,
    })
    auth_username = target_username or f"user_{target_id}"
    fb_request("PUT", f"sub_admin_auth/{auth_username}", {
        "username": auth_username,
        "password": "subadmin123",
        "telegram_id": target_id,
        "role": "admin",
    })
    await message.reply_text(
        f"✅ *{target_name or 'User'} is now a Sub Admin!*\n\n"
        f"Default login: username `{auth_username}`, password `subadmin123`\n"
        f"Tell them to send /admin to access the panel.",
        parse_mode=ParseMode.MARKDOWN
    )


async def _safe_edit(query, text, **kwargs):
    try:
        await query.edit_message_text(text, **kwargs)
    except BadRequest as e:
        if "message is not modified" in str(e).lower():
            pass
        else:
            raise


async def _remove_sub_admin_render(query, user_id, chat_id):
    fb_request("PUT", f"sub_admins/{user_id}", {"is_active": False})
    await query.answer("Sub-admin removed.")
    sub_admin_data = fb_request("GET", "sub_admins") or {}
    msg_lines = ["👥 *Sub Admins:*\n"]
    keyboard_buttons = []
    if sub_admin_data and isinstance(sub_admin_data, dict):
        for tid, info in sub_admin_data.items():
            if info and info.get("is_active"):
                name = info.get("name", "Unknown")
                username = info.get("username", "")
                label = f"{name} (@{username})" if username else name
                msg_lines.append(f"• {label}")
                keyboard_buttons.append([
                    InlineKeyboardButton(f"❌ Remove {name}", callback_data=f"admin_remove_sub_admin_{tid}")
                ])
    else:
        msg_lines.append("_No sub-admins appointed._")
    keyboard_buttons.append([InlineKeyboardButton("➕ Add Sub Admin", callback_data="admin_prompt_add_sub_admin")])
    keyboard_buttons.append([InlineKeyboardButton("◀️ Back", callback_data="admin_back_to_panel")])
    await _safe_edit(query, "\n".join(msg_lines), parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard_buttons))


async def admin_file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles any file/media sent directly to the bot by the admin.
    """
    user = update.effective_user
    if not is_admin(user.id):
        return

    message = update.message
    chat_id = update.effective_chat.id

    # Check if super admin is adding a sub-admin (via forward or paste user ID)
    if context.user_data.get("awaiting_sub_admin_forward"):
        context.user_data.pop("awaiting_sub_admin_forward", None)
        fwd_from = message.forward_from if hasattr(message, 'forward_from') else None
        target_id = None
        target_name = None
        target_username = None

        if fwd_from:
            target_id = fwd_from.id
            target_name = fwd_from.first_name or "Sub Admin"
            target_username = fwd_from.username or ""
        elif message.text and message.text.strip().isdigit():
            target_id = int(message.text.strip())
            target_name = "Sub Admin (ID)"
            target_username = ""

        if not target_id:
            await message.reply_text(
                "❌ Forward a message from the user, or paste their Telegram User ID.\n\n"
                "📌 To get someone's ID: forward their message to @userinfobot"
            )
            return

        await _make_sub_admin(message, target_id, target_name, target_username, user.id)
        return

    file_id = None
    content_type = None
    file_name = None
    detected_label = ""

    if message.document:
        doc = message.document
        file_id = doc.file_id
        file_name = doc.file_name or "file"
        if doc.mime_type == "application/vnd.android.package-archive" or (file_name and file_name.lower().endswith(".apk")):
            content_type = "apk"
            detected_label = "📱 APK File"
        else:
            content_type = "document"
            detected_label = f"📁 Document ({file_name})"

    elif message.video:
        file_id = message.video.file_id
        content_type = "video"
        file_name = message.video.file_name or "video.mp4"
        detected_label = "🎬 Video"

    elif message.photo:
        file_id = message.photo[-1].file_id
        content_type = "image"
        file_name = "photo.jpg"
        detected_label = "🖼️ Image"

    elif message.voice:
        file_id = message.voice.file_id
        content_type = "voice"
        file_name = "voice.ogg"
        detected_label = "🎵 Voice Note"

    elif message.audio:
        file_id = message.audio.file_id
        content_type = "audio"
        file_name = message.audio.file_name or "audio.mp3"
        detected_label = "🎤 Audio"

    elif message.animation:
        file_id = message.animation.file_id
        content_type = "image"
        file_name = "animation.gif"
        detected_label = "🎞️ GIF / Animation"

    if not file_id:
        return

    # Check if we are waiting for an app icon image
    if context.user_data.get("awaiting_app_icon"):
        context.user_data.pop("awaiting_app_icon", None)
        set_config("apk_icon_file_id", file_id)
        await message.reply_text(
            f"✅ *App Icon Updated successfully!*\n\n"
            f"File ID: `{file_id}`\n"
            f"Users will now see this icon before downloading the APK.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # Check if we are compiling a multi-media demo sequence
    demo_list = context.user_data.get("awaiting_demo_media_list")
    if demo_list is not None:
        demo_list.append({
            "content_type": content_type,
            "file_id": file_id,
            "caption": message.caption or "",
            "text_content": ""
        })
        context.user_data["awaiting_demo_media_list"] = demo_list

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Save Demo", callback_data="admin_confirm_demo_media_done")],
            [InlineKeyboardButton("❌ Cancel", callback_data="admin_cancel")]
        ])

        await message.reply_text(
            f"🌸 *Added to Demo sequence!*\n\n"
            f"• Type: `{content_type}`\n"
            f"• Total Items: *{len(demo_list)}*\n\n"
            f"Send more text or media to add, or tap **Save Demo** to confirm.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )
        return

    # Check if we are compiling a multi-media broadcast list
    media_list = context.user_data.get("awaiting_broadcast_media_list")
    if media_list is not None:
        media_list.append({
            "type": content_type,
            "file_id": file_id,
            "caption": message.caption or ""
        })
        context.user_data["awaiting_broadcast_media_list"] = media_list

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Done (Confirm)", callback_data="admin_confirm_bc_media_done")],
            [InlineKeyboardButton("❌ Cancel", callback_data="admin_cancel")]
        ])

        await message.reply_text(
            f"📁 *Added to Broadcast list!*\n\n"
            f"• Type: `{content_type}`\n"
            f"• Total Items: *{len(media_list)}*\n\n"
            f"Send more text/files to add, or tap **Done** to proceed.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )
        return

    # Check if we are waiting for broadcast content
    if context.user_data.get("awaiting_broadcast_content"):
        context.user_data.pop("awaiting_broadcast_content", None)
        context.user_data["broadcast_file_id"] = file_id
        context.user_data["broadcast_type"] = content_type
        context.user_data["broadcast_caption"] = message.caption or ""

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Attach APK Button", callback_data="admin_confirm_bc_yes_apk"),
                InlineKeyboardButton("❌ No APK Button", callback_data="admin_confirm_bc_no_apk")
            ],
            [InlineKeyboardButton("❌ Cancel", callback_data="admin_cancel")]
        ])

        await message.reply_text(
            f"📢 *Broadcast {detected_label} Content Saved!*\n\n"
            f"Do you want to attach the APK download button below this broadcast?",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )
        return

    # Check if we were specifically waiting for a demo file
    if context.user_data.get("awaiting_demo_file"):
        context.user_data.pop("awaiting_demo_file", None)
        session = Session()
        try:
            new_demo = Content(
                content_type=content_type,
                file_id=file_id,
                file_name=file_name,
                caption=message.caption or "Check out the exclusive demo! 🌸",
                is_active=True,
                order_index=1,
            )
            session.add(new_demo)
            session.commit()

            if content_type == "image" and file_name.endswith(".gif"):
                set_config("welcome_gif_id", file_id)

            await message.reply_text(
                f"🌸 *Demo Content Added successfully!*\n\n"
                f"Saved a *{content_type}* file as additional demo content.",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            session.rollback()
            await message.reply_text(f"❌ Error setting demo: {e}")
        finally:
            session.close()
        return

    # Store file_id in context for callback
    context.user_data["pending_file_id"] = file_id
    context.user_data["pending_file_name"] = file_name
    context.user_data["pending_content_type"] = content_type
    context.user_data["pending_caption"] = message.caption or ""

    # If it is an APK, run the APK version prompt flow
    if content_type == "apk":
        await _save_apk_prompt(update, context, file_id, file_name, message.caption or "")
        return

    # For other items, show selection menu
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🌸 Set as Demo content", callback_data="admin_set_as_demo"),
            InlineKeyboardButton("📦 Add to General Content", callback_data="admin_save_content"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="admin_cancel")]
    ])

    await message.reply_text(
        f"✅ *{detected_label} received!*\n\n"
        f"Choose what to do with this file:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard,
    )


async def _save_apk_prompt(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    file_id: str,
    file_name: str,
    caption: str,
):
    """Instantly save and activate the new APK with auto-incremented versioning."""
    message = update.message
    session = Session()
    try:
        # Fetch the last active APK to auto-increment version
        last_apk = session.query(Content).filter_by(content_type="apk").order_by(Content.id.desc()).first()

        # Determine new version
        new_version = "1.0"
        if last_apk and last_apk.version:
            try:
                new_version = str(round(float(last_apk.version) + 0.1, 1))
            except ValueError:
                new_version = "1.0"

        # Archive old active APKs
        session.query(Content).filter_by(content_type="apk", is_active=True).update({"is_active": False})

        # Save and activate new APK
        new_apk = Content(
            content_type="apk",
            file_id=file_id,
            file_name=file_name,
            version=new_version,
            changelog=caption or "Performance improvements and bug fixes.",
            is_active=True,
        )
        session.add(new_apk)
        session.commit()

        # Keyboard options for quick edits or broadcast
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✏️ Edit Version/Changelog", callback_data=f"admin_edit_apk_meta_{new_apk.id}"),
                InlineKeyboardButton("📲 Send to All Users", callback_data="admin_broadcast_apk")
            ],
            [InlineKeyboardButton("✅ Done", callback_data="admin_apk_done")]
        ])

        await message.reply_text(
            f"🎉 *APK Uploaded & Activated Instantly!*\n\n"
            f"📱 File: `{file_name}`\n"
            f"📌 Version: *v{new_version}* (Auto-incremented)\n"
            f"📋 Changelog: _{caption or 'Performance improvements.'}_\n\n"
            f"🚀 *New users will now automatically download this version!*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )

    except Exception as e:
        session.rollback()
        logger.error(f"Error auto-saving APK: {e}", exc_info=True)
        await message.reply_text(f"❌ Error saving APK: {e}")
    finally:
        session.close()


async def admin_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles text inputs from the admin when configuring values.
    """
    user = update.effective_user
    if not is_admin(user.id):
        return

    message = update.message
    text = message.text.strip()
    chat_id = update.effective_chat.id

    # Passthrough for reply keyboard buttons — route to user handler
    known_buttons = [
        "📱 Download APK", "🌸 See Demo", "🎁 See Content Again",
        "🌟 Actually, I changed my mind!",
    ]
    if text in known_buttons:
        await user_text_handler(update, context)
        return

    session = Session()

    try:
        # Check if super admin is adding a sub-admin (via forward, paste ID, or @username)
        if context.user_data.get("awaiting_sub_admin_forward"):
            context.user_data.pop("awaiting_sub_admin_forward", None)
            fwd_from = message.forward_from if hasattr(message, 'forward_from') else None
            target_id = None
            target_name = None
            target_username = None

            if fwd_from:
                target_id = fwd_from.id
                target_name = fwd_from.first_name or "Sub Admin"
                target_username = fwd_from.username or ""
            elif text.isdigit():
                target_id = int(text)
                target_name = "Sub Admin (ID)"
                target_username = ""
            elif text.startswith("@"):
                username = text.lstrip("@")
                try:
                    chat = await context.bot.get_chat("@" + username)
                    target_id = chat.id
                    target_name = chat.first_name or username
                    target_username = username
                except Exception:
                    await message.reply_text(
                        "❌ Could not find a user with that username. "
                        "Make sure the username is correct and they have started this bot."
                    )
                    return
            else:
                await message.reply_text(
                    "❌ Please forward a message from the user, paste their numeric User ID, "
                    "or send their @username."
                )
                return

            await _make_sub_admin(message, target_id, target_name, target_username, user.id)
            return

        # Check if we are compiling a multi-media demo sequence
        demo_list = context.user_data.get("awaiting_demo_media_list")
        if demo_list is not None:
            demo_list.append({
                "content_type": "text",
                "file_id": None,
                "caption": "",
                "text_content": text
            })
            context.user_data["awaiting_demo_media_list"] = demo_list

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Save Demo", callback_data="admin_confirm_demo_media_done")],
                [InlineKeyboardButton("❌ Cancel", callback_data="admin_cancel")]
            ])

            await message.reply_text(
                f"✍️ *Text added to Demo sequence!*\n\n"
                f"• Preview: _{text[:60]}..._\n"
                f"• Total Items: *{len(demo_list)}*\n\n"
                f"Send more text or media to add, or tap **Save Demo** to confirm.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )
            return

        # Check if we are compiling a multi-media broadcast list
        media_list = context.user_data.get("awaiting_broadcast_media_list")
        if media_list is not None:
            media_list.append({
                "type": "text",
                "text": text
            })
            context.user_data["awaiting_broadcast_media_list"] = media_list

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Done (Confirm)", callback_data="admin_confirm_bc_media_done")],
                [InlineKeyboardButton("❌ Cancel", callback_data="admin_cancel")]
            ])

            await message.reply_text(
                f"✍️ *Text Item added to Broadcast list!*\n\n"
                f"• Preview: _{text[:60]}..._\n"
                f"• Total Items: *{len(media_list)}*\n\n"
                f"Send more text/files to add, or tap **Done** to proceed.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )
            return

        # Check if we are waiting for broadcast text content
        if context.user_data.get("awaiting_broadcast_content"):
            context.user_data.pop("awaiting_broadcast_content", None)
            context.user_data["broadcast_text"] = text
            context.user_data["broadcast_type"] = "text"

            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Attach APK Button", callback_data="admin_confirm_bc_yes_apk"),
                    InlineKeyboardButton("❌ No APK Button", callback_data="admin_confirm_bc_no_apk")
                ],
                [InlineKeyboardButton("❌ Cancel", callback_data="admin_cancel")]
            ])

            await message.reply_text(
                f"📢 *Broadcast Text Content Saved!*\n\n"
                f"Do you want to attach the APK download button below this message?",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )
            return

        # 1. Handling APK version/changelog input (custom metadata update)
        if context.user_data.get("awaiting_apk_version"):
            context.user_data.pop("awaiting_apk_version")
            lines = text.split("\n", 1)
            version = lines[0].strip()
            changelog = lines[1].strip() if len(lines) > 1 else ""

            apk_edit_id = context.user_data.pop("awaiting_apk_edit_id", None)

            if apk_edit_id:
                # Upgraded path: edit metadata on the auto-saved APK
                apk_item = session.query(Content).filter_by(id=apk_edit_id).first()
                if apk_item:
                    apk_item.version = version
                    apk_item.changelog = changelog
                    session.commit()
                    await message.reply_text(
                        f"✅ *APK Metadata Updated!*\n\n"
                        f"📱 File: `{apk_item.file_name}`\n"
                        f"📌 Custom Version: *v{version}*\n"
                        f"📋 Changelog: _{changelog or 'None'}_",
                        parse_mode=ParseMode.MARKDOWN
                    )
                else:
                    await message.reply_text("❌ Error: Could not locate the uploaded APK record.")
            else:
                # Fallback path (old code)
                file_id = context.user_data.pop("pending_file_id", None)
                file_name = context.user_data.pop("pending_file_name", "App.apk")

                session.query(Content).filter_by(content_type="apk", is_active=True).update({"is_active": False})
                new_apk = Content(
                    content_type="apk",
                    file_id=file_id,
                    file_name=file_name,
                    version=version,
                    changelog=changelog,
                    is_active=True,
                )
                session.add(new_apk)
                session.commit()

                await message.reply_text(
                    f"🎉 *Active APK Configured successfully!*\n\n"
                    f"📛 Name: `{file_name}`\n"
                    f"📌 Version: *v{version}*\n"
                    f"📋 Changelog: _{changelog or 'None'}_",
                    parse_mode=ParseMode.MARKDOWN
                )
            return

        # 2. Handling APK name update
        if context.user_data.get("awaiting_apk_name"):
            context.user_data.pop("awaiting_apk_name")
            active_apk = session.query(Content).filter_by(content_type="apk", is_active=True).first()
            if active_apk:
                active_apk.file_name = text
                session.commit()
                await message.reply_text(f"✅ APK File Name set to: `{text}`")
            else:
                await message.reply_text("⚠️ No active APK found. Upload an APK file first!")
            return

        # 3. Handling APK caption update
        if context.user_data.get("awaiting_apk_caption"):
            context.user_data.pop("awaiting_apk_caption")
            active_apk = session.query(Content).filter_by(content_type="apk", is_active=True).first()
            if active_apk:
                active_apk.changelog = text
                session.commit()
                await message.reply_text(f"✅ APK Caption/Changelog set to:\n_{text}_", parse_mode=ParseMode.MARKDOWN)
            else:
                await message.reply_text("⚠️ No active APK found. Upload an APK file first!")
            return

        # 4. Handling welcome text update
        if context.user_data.get("awaiting_welcome_text"):
            context.user_data.pop("awaiting_welcome_text")
            set_config("welcome_text", text)
            await message.reply_text(f"✅ Welcome message updated successfully to:\n\n{text}", parse_mode=ParseMode.MARKDOWN)
            return

        # 5. Handling demo closing message update
        if context.user_data.get("awaiting_demo_msg"):
            context.user_data.pop("awaiting_demo_msg")
            set_config("demo_closing_text", text)
            await message.reply_text(f"✅ Demo closing message updated successfully to:\n\n{text}", parse_mode=ParseMode.MARKDOWN)
            return

        # 9. Handling demo link URL + label
        if context.user_data.get("awaiting_demo_link"):
            lines = text.split("\n", 1)
            url = lines[0].strip()
            label = lines[1].strip() if len(lines) > 1 else "🔗 Open Link"
            if not url.startswith("http"):
                await message.reply_text("❌ Invalid URL. Must start with http:// or https://")
                return
            context.user_data.pop("awaiting_demo_link")
            new_link = Content(
                content_type="link",
                link_url=url,
                link_text=label,
                text_content=url,
                caption="🔗 *Click below to open:*",
                is_active=True,
                order_index=999,
            )
            session.add(new_link)
            session.commit()
            await message.reply_text(
                f"✅ *Demo Link added!*\n\n"
                f"🔗 URL: `{url}`\n"
                f"📌 Label: `{label}`",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        # 10. Handling broadcast link URL + label
        if context.user_data.get("awaiting_broadcast_link"):
            if text.strip().lower() == "skip":
                context.user_data.pop("awaiting_broadcast_link")
                context.user_data["broadcast_link_url"] = None
                context.user_data["broadcast_link_text"] = None
            else:
                lines = text.split("\n", 1)
                url = lines[0].strip()
                label = lines[1].strip() if len(lines) > 1 else "🔗 Open Link"
                if not url.startswith("http"):
                    await message.reply_text("❌ Invalid URL. Must start with http:// or https://")
                    return
                context.user_data.pop("awaiting_broadcast_link")
                context.user_data["broadcast_link_url"] = url
                context.user_data["broadcast_link_text"] = label
            bc_id, bc_type = await _launch_broadcast(context, chat_id)
            await message.reply_text(f"📲 *Broadcast #{bc_id} ({bc_type}) started in background!* Sending to users...", parse_mode=ParseMode.MARKDOWN)
            return

    except Exception as e:
        session.rollback()
        logger.error(f"Admin text config error: {e}", exc_info=True)
        await message.reply_text(f"❌ Error: {e}")
    finally:
        session.close()


async def _launch_broadcast(context, chat_id):
    """Build and launch a broadcast from stored context data. Returns (bc_id, bc_type)"""
    session = Session()
    try:
        has_apk = context.user_data.pop("broadcast_has_apk", False)
        link_url = context.user_data.pop("broadcast_link_url", None)
        link_text = context.user_data.pop("broadcast_link_text", None)
        media_list = context.user_data.pop("awaiting_broadcast_media_list", None)

        import json
        if media_list:
            bc_type = "multimedia"
            bc_file_id = None
            bc_caption = None
            bc_text = json.dumps(media_list)
        else:
            bc_type = context.user_data.pop("broadcast_type", "text")
            bc_file_id = context.user_data.pop("broadcast_file_id", None)
            bc_caption = context.user_data.pop("broadcast_caption", None)
            bc_text = context.user_data.pop("broadcast_text", None)

        new_bc = Broadcast(
            message_type=bc_type,
            file_id=bc_file_id,
            caption=bc_caption,
            content_text=bc_text,
            has_apk_button=has_apk,
            apk_button_text="⬇️ Download App",
            link_url=link_url,
            link_text=link_text or "🔗 Open Link",
            status="pending"
        )
        session.add(new_bc)
        session.commit()
        bc_id = new_bc.id

        from broadcast import execute_broadcast
        import threading

        def run_custom_bg():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(execute_broadcast(bc_id, context.bot.token))
            except Exception as thread_err:
                logger.error(f"Telegram thread broadcast error: {thread_err}")
            finally:
                loop.close()

        threading.Thread(target=run_custom_bg, daemon=True).start()
        return bc_id, bc_type
    except Exception as e:
        logger.error(f"Error launching broadcast: {e}", exc_info=True)
        raise
    finally:
        session.close()


async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Admin Panel button callbacks."""
    user = update.effective_user
    if not is_admin(user.id):
        return

    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = update.effective_chat.id
    session = Session()

    try:
        if data.startswith("admin_edit_apk_meta_"):
            apk_id = int(data.split("_")[-1])
            context.user_data["awaiting_apk_version"] = True
            context.user_data["awaiting_apk_edit_id"] = apk_id
            await context.bot.send_message(
                chat_id=chat_id,
                text="✏️ *Please reply with the custom version and changelog.* \n\nFormat:\n`2.0\nYour changelog here...`",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        if data == "admin_save_content":
            file_id = context.user_data.pop("pending_file_id", None)
            file_name = context.user_data.pop("pending_file_name", "file")
            content_type = context.user_data.pop("pending_content_type", "document")
            caption = context.user_data.pop("pending_caption", "")

            max_order = 0
            for item in session.query(Content).all():
                if item.order_index and item.order_index > max_order:
                    max_order = item.order_index

            new_item = Content(
                content_type=content_type,
                file_id=file_id,
                file_name=file_name,
                caption=caption or None,
                is_active=True,
                order_index=max_order + 1,
            )
            session.add(new_item)
            session.commit()
            await _safe_edit(query, f"✅ General content added successfully at order position {max_order + 1}.")

        elif data == "admin_set_as_demo":
            file_id = context.user_data.pop("pending_file_id", None)
            file_name = context.user_data.pop("pending_file_name", "file")
            content_type = context.user_data.pop("pending_content_type", "document")
            caption = context.user_data.pop("pending_caption", "")

            new_demo = Content(
                content_type=content_type,
                file_id=file_id,
                file_name=file_name,
                caption=caption or "Here is your exclusive demo content! 🌸",
                is_active=True,
                order_index=1,
            )
            session.add(new_demo)
            session.commit()
            await _safe_edit(query, f"🌸 Demo content added successfully as new *{content_type}*.")

        elif data == "admin_prompt_set_apk":
            await context.bot.send_message(
                chat_id=chat_id,
                text="📤 *Please send the new .apk file directly to this chat.*",
                parse_mode=ParseMode.MARKDOWN
            )

        elif data == "admin_remove_apk":
            session.query(Content).filter_by(content_type="apk").update({"is_active": False})
            session.commit()
            await _safe_edit(query, "🗑️ Active APK has been removed. Users can no longer download it.")

        elif data == "admin_prompt_apk_name":
            context.user_data["awaiting_apk_name"] = True
            await context.bot.send_message(
                chat_id=chat_id,
                text="✏️ *Please reply with the name you want to display for the APK file:*",
                parse_mode=ParseMode.MARKDOWN
            )

        elif data == "admin_prompt_apk_caption":
            context.user_data["awaiting_apk_caption"] = True
            await context.bot.send_message(
                chat_id=chat_id,
                text="✏️ *Please reply with the caption / changelog description for the APK:*",
                parse_mode=ParseMode.MARKDOWN
            )

        elif data == "admin_prompt_welcome":
            context.user_data["awaiting_welcome_text"] = True
            await context.bot.send_message(
                chat_id=chat_id,
                text="✏️ *Please reply with the new Welcome message text (Markdown supported):*",
                parse_mode=ParseMode.MARKDOWN
            )

        elif data == "admin_prompt_demo":
            context.user_data["awaiting_demo_media_list"] = []
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    "🌸 *Multi-Media Demo Builder active!* 🌸\n\n"
                    "Send me any files (videos, photos, voice notes, audio, text) one-by-one to build the demo sequence.\n\n"
                    "Tap **✅ Save Demo** when you've sent all files to complete setup."
                ),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Save Demo", callback_data="admin_confirm_demo_media_done")],
                    [InlineKeyboardButton("❌ Cancel", callback_data="admin_cancel")]
                ])
            )

        elif data == "admin_confirm_demo_media_done":
            demo_list = context.user_data.pop("awaiting_demo_media_list", None)
            if not demo_list:
                await context.bot.send_message(chat_id=chat_id, text="⚠️ No items added to demo sequence. Cancelled.")
                return

            for idx, item in enumerate(demo_list):
                new_demo = Content(
                    content_type=item["content_type"],
                    file_id=item["file_id"],
                    file_name="demo_file",
                    caption=item["caption"],
                    text_content=item["text_content"],
                    is_active=True,
                    order_index=idx + 1,
                )
                session.add(new_demo)
            session.commit()

            await _safe_edit(query, f"🌸 *Demo sequence updated with {len(demo_list)} new items!*")

        elif data == "admin_prompt_demo_msg":
            context.user_data["awaiting_demo_msg"] = True
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    "✏️ *Please reply with the text to be shown AFTER the demo content delivery:*\n\n"
                    "💡 Use `{name}` in your text to dynamically replace it with the user's name (e.g. `✨ Enjoy the game, {name}!`)."
                ),
                parse_mode=ParseMode.MARKDOWN
            )

        elif data == "admin_prompt_demo_link":
            context.user_data["awaiting_demo_link"] = True
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    "🔗 *Please send the link URL and button label.*\n\n"
                    "Format:\n"
                    "`https://example.com\nButton Label`\n\n"
                    "Or just the URL to use default label \"🔗 Open Link\"."
                ),
                parse_mode=ParseMode.MARKDOWN
            )

        elif data == "admin_prompt_app_icon":
            context.user_data["awaiting_app_icon"] = True
            await context.bot.send_message(
                chat_id=chat_id,
                text="🖼️ *Please send the Image or Sticker you want to use as the App Icon:*",
                parse_mode=ParseMode.MARKDOWN
            )

        elif data == "admin_manage_demo":
            all_items = session.query(Content).filter_by(is_active=True).all()
            demo_items = [c for c in all_items if c.content_type != "apk"]
            if not demo_items:
                await _safe_edit(query, "🌸 *Demo is empty.*\n\nUse the buttons below to add content.", reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🌸 Set Demo 🌸", callback_data="admin_prompt_demo")],
                    [InlineKeyboardButton("◀️ Back", callback_data="admin_back_to_panel")]
                ]))
            else:
                lines = ["📋 *Current Demo Items:*\n"]
                keyboard = []
                for i, item in enumerate(demo_items, 1):
                    lbl = f"{i}. {item.content_type}"
                    if item.content_type == "text" and item.text_content:
                        lbl += f": {item.text_content[:30]}"
                    elif item.file_name:
                        lbl += f" — {item.file_name}"
                    lines.append(f"  {i}. `{item.content_type}` — {item.text_content[:40] if item.text_content else item.file_id[:20]}")
                    keyboard.append([InlineKeyboardButton(f"❌ Remove #{i}", callback_data=f"admin_remove_demo_item_{item.id}")])
                keyboard.append([InlineKeyboardButton("🌸 Add More 🌸", callback_data="admin_prompt_demo"), InlineKeyboardButton("◀️ Back", callback_data="admin_back_to_panel")])
                await _safe_edit(query, "\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard))

        elif data == "admin_reset_demo":
            await _safe_edit(
                query,
                "🗑️ *Are you sure you want to reset ALL demo content?*\n\n"
                "This will remove every item from the demo sequence. This cannot be undone.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Yes, Reset Demo", callback_data="admin_confirm_reset_demo")],
                    [InlineKeyboardButton("❌ Cancel", callback_data="admin_manage_demo")]
                ])
            )

        elif data == "admin_confirm_reset_demo":
            all_items = session.query(Content).filter_by(is_active=True).all()
            count = 0
            for c in all_items:
                if c.content_type != "apk":
                    c.is_active = False
                    session.add(c)
                    count += 1
            session.commit()
            await _safe_edit(query, f"🗑️ *Demo reset complete!* Removed {count} item{'s' if count != 1 else ''}.")

        elif data.startswith("admin_remove_demo_item_"):
            remove_id = int(data.split("_")[-1])
            item = session.get(Content, remove_id)
            if item:
                item.is_active = False
                session.add(item)
                session.commit()
                await query.answer("✅ Item removed from demo.")
            else:
                await query.answer("⚠️ Item not found.")
            text, _ = get_admin_panel_details(user_id=user.id)
            keyboard = admin_panel_keyboard(get_config("demo_enabled", "true").lower() == "true", get_config("bot_enabled", "true").lower() == "true", get_admin_role(user.id))
            try:
                await _safe_edit(query, text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
            except Exception:
                pass

        elif data == "admin_add_apk_to_demo":
            active_apk = session.query(Content).filter_by(is_active=True, content_type="apk").order_by(Content.id.desc()).first()
            if not active_apk:
                await query.answer("⚠️ No active APK found.")
                await context.bot.send_message(chat_id=chat_id, text="⚠️ No active APK found. Upload an APK file first!")
            else:
                existing = session.query(Content).filter_by(is_active=True, content_type="apk_demo").all()
                if existing:
                    await query.answer("✅ APK already in demo.")
                    await context.bot.send_message(chat_id=chat_id, text="✅ *APK is already in the demo sequence!*")
                else:
                    new_item = Content(
                        content_type="apk_demo",
                        file_id=active_apk.file_id,
                        file_name=active_apk.file_name,
                        caption="📱 *Here is your exclusive download!*",
                        is_active=True,
                        order_index=999,
                    )
                    session.add(new_item)
                    session.commit()
                    await _safe_edit(query, f"✅ *APK added to demo sequence!*\n\nUsers will receive the APK during the demo flow.")

        elif data in ("admin_toggle_demo", "admin_toggle_maintenance"):
            if data == "admin_toggle_demo":
                current = get_config("demo_enabled", "true").lower() == "true"
                set_config("demo_enabled", "false" if current else "true")
            else:
                current = get_config("bot_enabled", "true").lower() == "true"
                set_config("bot_enabled", "false" if current else "true")

            text, keyboard = get_admin_panel_details(user_id=user.id)
            await _safe_edit(query, text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)

        elif data == "admin_how_to_use":
            guide_text = (
                "❓ *NexusBot Quick Help*\n\n"
                "• Send *any* file directly to this bot chat, and it will ask where to save it.\n"
                "• Send an `.apk` file directly to instantly set the new active download.\n"
                "• Tap *Get Report* to see detailed user sign-ups and download statistics."
            )
            await context.bot.send_message(chat_id=chat_id, text=guide_text, parse_mode=ParseMode.MARKDOWN)

        elif data == "admin_guide":
            guide_text = (
                "📖 *Admin Command & Operations Guide*\n\n"
                "1. **Welcome Message**: Set the onboarding greeting message.\n"
                "2. **Set Demo**: Set the video/media that YES answers will trigger.\n"
                "3. **Broadcast**: Push the active APK directly into user chats with the push button."
            )
            await context.bot.send_message(chat_id=chat_id, text=guide_text, parse_mode=ParseMode.MARKDOWN)

        elif data == "admin_get_report":
            total_users = session.query(User).count()
            downloads = session.query(Analytics).filter_by(event="apk_download").count()

            report = (
                "📊 *NexusBot Active Report*\n"
                "──────────────────────────\n"
                f"👤 Total Joined Users: *{total_users}*\n"
                f"📥 Total APK Downloads: *{downloads}*\n"
                "──────────────────────────\n"
                "All stats updated in real-time."
            )
            await context.bot.send_message(chat_id=chat_id, text=report, parse_mode=ParseMode.MARKDOWN)

        elif data == "admin_broadcast_apk":
            active_apk = session.query(Content).filter_by(content_type="apk", is_active=True).first()
            if not active_apk:
                await context.bot.send_message(chat_id=chat_id, text="⚠️ Cannot broadcast: No active APK file set!")
                return

            # Save broadcast job
            broadcast_job = Broadcast(
                message_type="apk",
                file_id=active_apk.file_id,
                caption=active_apk.changelog or "New APK Update is live! 🚀",
                has_apk_button=True,
                apk_button_text="⬇️ Download App",
                status="pending"
            )
            session.add(broadcast_job)
            session.commit()

            # Run asynchronously in background thread
            from broadcast import execute_broadcast
            import threading
            bc_id = broadcast_job.id
            token = context.bot.token
            def run_bg():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(execute_broadcast(bc_id, token))
                except Exception as thread_err:
                    logger.error(f"Telegram thread broadcast error: {thread_err}")
                finally:
                    loop.close()

            threading.Thread(target=run_bg, daemon=True).start()
            await _safe_edit(query, "📲 *APK Broadcast started in the background!* Users will receive it shortly.")

        elif data == "admin_prompt_broadcast_media":
            context.user_data["awaiting_broadcast_media_list"] = []
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    "📢 *Multi-Media Broadcast Builder active!* 📢\n\n"
                    "Send me any files or messages you want to include in this broadcast (Texts, Voice Notes, Photos, Videos, Audio, Documents/APKs) one-by-one.\n\n"
                    "Tap **✅ Done (Confirm)** when you've sent all files to launch the broadcast."
                ),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Done (Confirm)", callback_data="admin_confirm_bc_media_done")],
                    [InlineKeyboardButton("❌ Cancel", callback_data="admin_cancel")]
                ])
            )

        elif data == "admin_prompt_send_text":
            context.user_data["awaiting_broadcast_content"] = True
            await context.bot.send_message(
                chat_id=chat_id,
                text="✏️ *Please reply with the text message you want to broadcast to all users:*",
                parse_mode=ParseMode.MARKDOWN
            )

        elif data == "admin_prompt_broadcast_link":
            context.user_data["awaiting_broadcast_link"] = True
            await _safe_edit(
                query,
                "🔗 *Send the link URL and optional button label.*\n\n"
                "Format:\n"
                "`https://example.com\nButton Label`\n\n"
                "Or send just `skip` to continue without a link.",
                parse_mode=ParseMode.MARKDOWN
            )

        elif data == "admin_confirm_bc_media_done":
            media_list = context.user_data.get("awaiting_broadcast_media_list", [])
            if not media_list:
                await context.bot.send_message(chat_id=chat_id, text="⚠️ No items added yet. Please send some media or text first.")
                return

            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Attach APK Button", callback_data="admin_confirm_bc_yes_apk"),
                    InlineKeyboardButton("❌ No APK Button", callback_data="admin_confirm_bc_no_apk")
                ],
                [InlineKeyboardButton("Cancel", callback_data="admin_cancel")]
            ])
            await _safe_edit(
                query,
                f"📊 *Multi-Media sequence contains {len(media_list)} items.*\n\nDo you want to attach the APK download button below this broadcast?",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )

        elif data in ("admin_confirm_bc_yes_apk", "admin_confirm_bc_no_apk"):
            has_apk = (data == "admin_confirm_bc_yes_apk")
            context.user_data["broadcast_has_apk"] = has_apk

            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Attach Link Button", callback_data="admin_prompt_broadcast_link"),
                    InlineKeyboardButton("❌ No Link", callback_data="admin_confirm_bc_launch")
                ],
                [InlineKeyboardButton("Cancel", callback_data="admin_cancel")]
            ])
            await _safe_edit(
                query,
                "🔗 *Do you want to attach a clickable link button to this broadcast?*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )

        elif data == "admin_confirm_bc_launch":
            bc_id, bc_type = await _launch_broadcast(context, chat_id)
            await _safe_edit(query, f"📲 *Broadcast #{bc_id} ({bc_type}) started in background!* Sending to users...")

        elif data.startswith("admin_remove_sub_admin_"):
            remove_id = int(data.split("_")[-1])
            await _remove_sub_admin_render(query, remove_id, chat_id)

        elif data == "admin_manage_sub_admins":
            if get_admin_role(user.id) != "super_admin":
                await context.bot.send_message(chat_id=chat_id, text="⛔ Only super admin can manage admins.")
                return
            sub_admin_data = fb_request("GET", "sub_admins") or {}
            msg_lines = ["👥 *Sub Admins:*\n"]
            keyboard_buttons = []
            if sub_admin_data and isinstance(sub_admin_data, dict):
                for tid, info in sub_admin_data.items():
                    if info and info.get("is_active"):
                        name = info.get("name", "Unknown")
                        username = info.get("username", "")
                        label = f"{name} (@{username})" if username else name
                        msg_lines.append(f"• {label}")
                        keyboard_buttons.append([
                            InlineKeyboardButton(f"❌ Remove {name}", callback_data=f"admin_remove_sub_admin_{tid}")
                        ])
            else:
                msg_lines.append("_No sub-admins appointed._")
            keyboard_buttons.append([InlineKeyboardButton("➕ Add Sub Admin", callback_data="admin_prompt_add_sub_admin")])
            keyboard_buttons.append([InlineKeyboardButton("◀️ Back", callback_data="admin_back_to_panel")])
            await _safe_edit(query, "\n".join(msg_lines), parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard_buttons))

        elif data == "admin_prompt_add_sub_admin":
            if get_admin_role(user.id) != "super_admin":
                return
            context.user_data["awaiting_sub_admin_forward"] = True
            await _safe_edit(query,
                "📤 *Forward me a message from the user you want to appoint as Sub Admin.*\n\n"
                "Any message they sent to this bot will work.",
                parse_mode=ParseMode.MARKDOWN
            )

        elif data == "admin_back_to_panel":
            context.user_data.clear()
            text, keyboard = get_admin_panel_details(user_id=user.id)
            await _safe_edit(query, text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)

        elif data == "admin_apk_done":
            context.user_data.clear()
            await _safe_edit(query, "✅ APK configured and live!")
        elif data == "admin_cancel":
            context.user_data.clear()
            await _safe_edit(query, "❌ Operations cancelled.")

    except Exception as e:
        session.rollback()
        logger.error(f"Callback admin error: {e}", exc_info=True)
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Error: {e}")
    finally:
        session.close()


def get_admin_panel_details(user_id: int = 0):
    session = Session()
    try:
        total_users = session.query(User).count()

        active_apk = session.query(Content).filter_by(content_type="apk", is_active=True).first()
        app_status = "Set" if active_apk else "Not set"
        app_name = active_apk.file_name if active_apk else "None"

        active_demo = session.query(Content).filter(Content.content_type != "apk", Content.is_active == True).first()
        demo_status = "Set" if active_demo else "Not set"

        demo_on = get_config("demo_enabled", "true").lower() == "true"
        bot_active = get_config("bot_enabled", "true").lower() == "true"

        text = (
            "⚙️ *ADMIN CONTROL PANEL* ⚙️\n"
            "──────────────────────────\n"
            f"👥 Total Verified Users: *{total_users}*\n"
            f"📱 App Status: *{app_status}*\n"
            f"📛 App Name: *{app_name}*\n"
            f"🌸 Demo URL: *{demo_status}*\n"
            "──────────────────────────\n"
            "👇 _Niche diye buttons se manage karein:_"
        )

        role = get_admin_role(user_id) if user_id else "super_admin"
        keyboard = admin_panel_keyboard(demo_on, bot_active, role)
        return text, keyboard
    finally:
        session.close()