import asyncio
import logging
import json
from datetime import datetime
from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.error import TelegramError, BadRequest
from telegram.constants import ParseMode

from db import Session, Broadcast, Content

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
CHUNK_SIZE = 20
CHUNK_SLEEP = 1.0


async def execute_broadcast(broadcast_id: int, bot_token: str):
    bot = Bot(token=bot_token)
    session = Session()
    broadcast = None

    try:
        broadcast = session.get(Broadcast, broadcast_id)
        if not broadcast:
            logger.error(f"Broadcast {broadcast_id} not found")
            return

        broadcast.status = "sending"
        session.commit()

        user_ids = session.get_user_ids()
        total = len(user_ids)
        broadcast.total_users = total
        session.commit()

        sent = 0
        failed = 0

        reply_markup = None
        buttons = []
        if broadcast.link_url:
            buttons.append([InlineKeyboardButton(broadcast.link_text or "🔗 Open Link", url=broadcast.link_url)])
        if broadcast.has_apk_button:
            active_apk = (
                session.query(Content)
                .filter_by(is_active=True, content_type="apk")
                .order_by(Content.id.desc())
                .first()
            )
            if active_apk:
                btn_text = f"{broadcast.apk_button_text} v{active_apk.version}" if active_apk.version else broadcast.apk_button_text
                buttons.append([InlineKeyboardButton(btn_text, callback_data="download_apk")])
        if buttons:
            reply_markup = InlineKeyboardMarkup(buttons)

        progress_msg = None
        from bot import ADMIN_TELEGRAM_ID
        if ADMIN_TELEGRAM_ID:
            try:
                progress_msg = await bot.send_message(
                    chat_id=ADMIN_TELEGRAM_ID,
                    text=(
                        f"📢 *Broadcast #{broadcast_id} Initialized...* ⏳\n"
                        f"──────────────────────────\n"
                        f"👥 Target: *{total}* users\n"
                        f"🚀 Sending in chunks of {CHUNK_SIZE}..."
                    ),
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                pass

        for i in range(0, total, CHUNK_SIZE):
            chunk_ids = user_ids[i:i + CHUNK_SIZE]
            tasks = [_send_to_user(bot, uid, broadcast, reply_markup) for uid in chunk_ids]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for r in results:
                if r is True:
                    sent += 1
                else:
                    failed += 1

            done = min(i + CHUNK_SIZE, total)

            if done % 100 == 0 or done == total:
                broadcast.sent_count = sent
                broadcast.failed_count = failed
                session.commit()
                if progress_msg:
                    try:
                        remaining = total - done
                        pct = (done / total) * 100
                        await bot.edit_message_text(
                            chat_id=ADMIN_TELEGRAM_ID,
                            message_id=progress_msg.message_id,
                            text=(
                                f"📢 *Broadcast #{broadcast_id} in Progress...* ⏳\n"
                                f"──────────────────────────\n"
                                f"👥 Total: *{total}*\n"
                                f"✅ Sent: *{sent}*\n"
                                f"🚫 Blocked: *{failed}*\n"
                                f"⏳ Remaining: *{remaining}*\n"
                                f"📊 Progress: *{pct:.1f}%*"
                            ),
                            parse_mode=ParseMode.MARKDOWN
                        )
                    except Exception:
                        pass

            if i + CHUNK_SIZE < total:
                await asyncio.sleep(CHUNK_SLEEP)

        broadcast.sent_count = sent
        broadcast.failed_count = failed
        broadcast.status = "done"
        broadcast.completed_at = datetime.utcnow()
        session.commit()

        logger.info(f"Broadcast {broadcast_id} complete: {sent}/{total} sent, {failed} failed")

        if ADMIN_TELEGRAM_ID:
            try:
                title_lbl = "APK Blast" if broadcast.message_type == "apk" else "Broadcast"
                is_multi = False
                if broadcast.content_text:
                    try:
                        parsed = json.loads(broadcast.content_text)
                        if isinstance(parsed, list):
                            is_multi = True
                    except Exception:
                        pass

                apk_name_line = ""
                if broadcast.message_type == "apk":
                    active_apk = session.query(Content).filter_by(content_type="apk", is_active=True).first()
                    if active_apk:
                        apk_name_line = f"📲 APK Name: *{active_apk.file_name}*\n"

                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("◀️ Back to Admin", callback_data="admin_back_to_panel")]
                ])

                report_text = (
                    f"🎉 *{title_lbl} Complete!* 🎉\n"
                    f"──────────────────────────\n"
                    f"{apk_name_line}"
                    f"👥 Total Targeted: *{total}*\n"
                    f"✅ Successfully Broadcasted to: *{sent}*\n"
                    f"❌ Blocked / Could Not Receive: *{failed}*\n"
                    f"💯 Coverage: *{round(sent/total*100, 1) if total else 0}%*\n"
                    f"──────────────────────────\n"
                    f"All done! 💪🔥"
                )

                if progress_msg:
                    await bot.edit_message_text(
                        chat_id=ADMIN_TELEGRAM_ID,
                        message_id=progress_msg.message_id,
                        text=report_text,
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=keyboard
                    )
                else:
                    await bot.send_message(
                        chat_id=ADMIN_TELEGRAM_ID,
                        text=report_text,
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=keyboard
                    )
            except Exception as report_err:
                logger.error(f"Failed to send broadcast completion report: {report_err}")

    except Exception as e:
        logger.error(f"Broadcast {broadcast_id} failed: {e}", exc_info=True)
        if broadcast:
            broadcast.status = "failed"
            session.commit()
    finally:
        try:
            if hasattr(bot, '_http_client') and bot._http_client:
                await bot._http_client.aclose()
        except Exception:
            pass
        session.close()


async def _send_to_user(
    bot: Bot, user_id: int, broadcast: "Broadcast",
    reply_markup: InlineKeyboardMarkup | None, attempt: int = 1,
) -> bool:
    try:
        items = []
        if broadcast.content_text:
            try:
                parsed = json.loads(broadcast.content_text)
                if isinstance(parsed, list):
                    items = parsed
            except Exception:
                pass

        if not items:
            items = [{
                "type": broadcast.message_type, "file_id": broadcast.file_id,
                "caption": broadcast.caption, "text": broadcast.content_text
            }]

        for idx, item in enumerate(items):
            msg_type = item.get("type", "text")
            file_id = item.get("file_id")
            caption = item.get("caption") or ""
            text = item.get("text") or ""
            item_markup = reply_markup if idx == len(items) - 1 else None

            if msg_type == "text":
                try:
                    await bot.send_message(chat_id=user_id, text=text, parse_mode=ParseMode.MARKDOWN, reply_markup=item_markup)
                except BadRequest as parse_err:
                    if "parse" in str(parse_err).lower():
                        await bot.send_message(chat_id=user_id, text=text, reply_markup=item_markup)
                    else:
                        raise
            elif msg_type == "image":
                await bot.send_photo(chat_id=user_id, photo=file_id, caption=caption, parse_mode=ParseMode.MARKDOWN, reply_markup=item_markup)
            elif msg_type == "video":
                await bot.send_video(chat_id=user_id, video=file_id, caption=caption, parse_mode=ParseMode.MARKDOWN, supports_streaming=True, reply_markup=item_markup)
            elif msg_type == "voice":
                await bot.send_voice(chat_id=user_id, voice=file_id, caption=caption, reply_markup=item_markup)
            elif msg_type == "audio":
                await bot.send_audio(chat_id=user_id, audio=file_id, caption=caption, reply_markup=item_markup)
            elif msg_type in ("apk", "document"):
                await bot.send_document(chat_id=user_id, document=file_id, caption=caption, parse_mode=ParseMode.MARKDOWN, reply_markup=item_markup)

        return True
    except TelegramError as e:
        err_msg = str(e).lower()
        if any(x in err_msg for x in ["blocked", "deactivated", "not found", "chat not found"]):
            return False
        if "429" in err_msg or "too many requests" in err_msg:
            retry_after = 2
            try:
                retry_after = int(str(e).split("retry after ")[1].split()[0]) + 1
            except Exception:
                pass
            await asyncio.sleep(retry_after)
            if attempt < MAX_RETRIES:
                return await _send_to_user(bot, user_id, broadcast, reply_markup, attempt + 1)
        if attempt < MAX_RETRIES:
            await asyncio.sleep(1)
            return await _send_to_user(bot, user_id, broadcast, reply_markup, attempt + 1)
        logger.warning(f"Failed to send to {user_id} after {attempt} attempts: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending to {user_id}: {e}")
        return False