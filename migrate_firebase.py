"""
One-Time Firebase RTDB to SQLite Migration Script for NexusBot VPS.
Pulls existing users, contents, broadcasts, and configs from Firebase
and imports them directly into local SQLite (nexusbot.db).
"""
import os
import json
import urllib.request
import sqlite3
from datetime import datetime
from db import init_db, DB_PATH

FIREBASE_URL = os.environ.get("FIREBASE_URL", "https://th-june-76ac5-default-rtdb.firebaseio.com")
FIREBASE_SECRET = os.environ.get("FIREBASE_SECRET", "cjSEmrx1jKj8vbZdBd34gZ1Zb8aAFbR5UuF8lMtr")


def fb_fetch(path):
    url = f"{FIREBASE_URL}/{path.lstrip('/')}.json?auth={FIREBASE_SECRET}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=60) as response:
            body = response.read().decode("utf-8")
            if not body or body == "null":
                return None
            return json.loads(body)
    except Exception as e:
        print(f"❌ Error fetching {path}: {e}")
        return None


def run_migration():
    print("🚀 Initializing local SQLite database schema...")
    init_db()

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. Migrate Users
    print("\n📥 Fetching users from Firebase...")
    users_data = fb_fetch("users") or {}
    user_count = 0

    if isinstance(users_data, dict):
        user_items = users_data.items()
    elif isinstance(users_data, list):
        user_items = [(str(idx), val) for idx, val in enumerate(users_data) if val is not None]
    else:
        user_items = []

    for uid_str, u in user_items:
        if not u or not isinstance(u, dict):
            continue
        uid = int(uid_str) if str(uid_str).isdigit() else u.get("id")
        if not uid:
            continue

        cursor.execute("""
            INSERT OR REPLACE INTO users (
                id, username, first_name, last_name, language_code,
                joined_at, last_active, is_banned, streak_count, streak_last_date, downloaded_apk
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            uid,
            u.get("username"),
            u.get("first_name"),
            u.get("last_name"),
            u.get("language_code", "en"),
            u.get("joined_at", datetime.utcnow().isoformat()),
            u.get("last_active", datetime.utcnow().isoformat()),
            1 if u.get("is_banned") else 0,
            u.get("streak_count", 0),
            u.get("streak_last_date"),
            1 if u.get("downloaded_apk") else 0
        ))
        user_count += 1

    conn.commit()
    print(f"✅ Migrated {user_count} users into SQLite!")

    # 2. Migrate Contents
    print("\n📥 Fetching content items from Firebase...")
    contents_data = fb_fetch("contents") or {}
    content_count = 0

    if isinstance(contents_data, dict):
        content_items = contents_data.items()
    elif isinstance(contents_data, list):
        content_items = [(str(idx), val) for idx, val in enumerate(contents_data) if val is not None]
    else:
        content_items = []

    for cid_str, c in content_items:
        if not c or not isinstance(c, dict):
            continue
        cid = int(cid_str) if str(cid_str).isdigit() else c.get("id")

        cursor.execute("""
            INSERT OR REPLACE INTO contents (
                id, content_type, file_id, file_name, version,
                changelog, caption, text_content, is_active, order_index,
                created_at, link_url, link_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            cid,
            c.get("content_type"),
            c.get("file_id"),
            c.get("file_name"),
            c.get("version"),
            c.get("changelog"),
            c.get("caption"),
            c.get("text_content"),
            1 if c.get("is_active", True) else 0,
            c.get("order_index", 0),
            c.get("created_at", datetime.utcnow().isoformat()),
            c.get("link_url"),
            c.get("link_text", "🔗 Open Link")
        ))
        content_count += 1

    conn.commit()
    print(f"✅ Migrated {content_count} content items into SQLite!")

    # 3. Migrate Broadcasts
    print("\n📥 Fetching broadcasts from Firebase...")
    broadcasts_data = fb_fetch("broadcasts") or {}
    broadcast_count = 0

    if isinstance(broadcasts_data, dict):
        broadcast_items = broadcasts_data.items()
    elif isinstance(broadcasts_data, list):
        broadcast_items = [(str(idx), val) for idx, val in enumerate(broadcasts_data) if val is not None]
    else:
        broadcast_items = []

    for bid_str, b in broadcast_items:
        if not b or not isinstance(b, dict):
            continue
        bid = int(bid_str) if str(bid_str).isdigit() else b.get("id")

        cursor.execute("""
            INSERT OR REPLACE INTO broadcasts (
                id, message_type, file_id, caption, content_text,
                has_apk_button, apk_button_text, link_url, link_text,
                status, sent_count, failed_count, total_users, created_at, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            bid,
            b.get("message_type", "text"),
            b.get("file_id"),
            b.get("caption"),
            b.get("content_text"),
            1 if b.get("has_apk_button") else 0,
            b.get("apk_button_text", "⬇️ Download App"),
            b.get("link_url"),
            b.get("link_text"),
            b.get("status", "done"),
            b.get("sent_count", 0),
            b.get("failed_count", 0),
            b.get("total_users", 0),
            b.get("created_at", datetime.utcnow().isoformat()),
            b.get("completed_at")
        ))
        broadcast_count += 1

    conn.commit()
    print(f"✅ Migrated {broadcast_count} broadcast records into SQLite!")

    # 4. Migrate Bot Configs
    print("\n📥 Fetching bot configurations from Firebase...")
    config_data = fb_fetch("config") or {}
    config_count = 0
    if isinstance(config_data, dict):
        for k, v in config_data.items():
            if v is not None:
                cursor.execute("INSERT OR REPLACE INTO bot_config (key, value) VALUES (?, ?)", (k, str(v)))
                config_count += 1

    conn.commit()
    conn.close()
    print(f"✅ Migrated {config_count} configuration keys into SQLite!")
    print("\n🎉 MIGRATION COMPLETE! Your VPS bot is now fully populated and ready to run.")


if __name__ == "__main__":
    run_migration()
