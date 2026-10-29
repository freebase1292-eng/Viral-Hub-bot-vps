# ⚡ NexusBot VPS Edition (100k+ Scale)

High-performance Telegram bot engine optimized for VPS hosting.
**No domain, no SSL, and no DNS required!**
Completely stripped of slow external Firebase HTTP calls and referral delays. Capable of instant (< 30ms) responses and handling 100k+ active users.

## 🚀 Key Improvements in this VPS Edition
* **Zero Domain / Zero SSL Required**: Runs in high-speed Long-Polling mode. No need to buy domains, set up DNS, or configure SSL certificates.
* **Direct Web Admin Access**: Access your admin dashboard directly from any browser at `http://YOUR_VPS_IP:8000/admin`.
* **Zero Firebase**: Replaced with local **SQLite in WAL (Write-Ahead Logging) mode**, executing indexed queries in **0.1ms** directly on NVMe SSD.
* **No Referral Bottlenecks**: Completely removed referral code generation and multi-megabyte full-table user scans.
* **Smart Admin Alerts**: Real-time alerts with auto-surge batching, ensuring 0ms delay for users and no Telegram 429 flood blocks.
* **RAM Caching**: Active configurations (`bot_enabled`, welcome messages, etc.) are cached in memory for sub-millisecond responses.
* **Direct APK Broadcasting**: Choose between sending the actual `.apk` file directly or attaching a download button.

---

## 🛠️ 3-Minute Quickstart on Ubuntu VPS

### 1. Install System Packages
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git
```

### 2. Clone Your Repo and Set Up Virtual Environment
```bash
cd /opt
git clone https://github.com/freebase1292-eng/Viral-Hub-bot-vps.git nexusbot-vps
cd nexusbot-vps

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure Your Bot Credentials
Paste this entire block into your terminal (replace with your Bot Token and Admin ID):
```bash
cat << 'EOF' > /opt/nexusbot-vps/.env
BOT_TOKEN=8785727322:AAFwMrQBFR2siX7eudS_n4kQSkMPny0zIiU
ADMIN_TELEGRAM_ID=8756082851
ADMIN_USERNAME=admin
ADMIN_SECRET=ChangeThisToAStrongPassword123!
SECRET_KEY=nexusbot_secure_random_key_change_me
PORT=8000
ENABLE_JOIN_ALERTS=true
EOF
```

### 4. (Optional) Migrate Existing 10,000 Users from Firebase
```bash
python3 migrate_firebase.py
```

### 5. Start the 24/7 Service
```bash
sudo cp nexusbot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable nexusbot
sudo systemctl start nexusbot
```

**That's it! Your bot is now LIVE!**
* Open Telegram and send `/start` to your bot.
* Access your Web Admin Panel directly from your browser at:
  `http://YOUR_VPS_IP:8000/admin`
