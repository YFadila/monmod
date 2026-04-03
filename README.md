# 🤖 Discord Moderation Bot

Bot moderasi server Discord sederhana, dibangun dengan `discord.py`.

---

## 📁 Struktur Project

```
discord-bot/
├── main.py               # Entry point utama
├── requirements.txt      # Dependensi Python
├── .env                  # Konfigurasi rahasia (JANGAN di-commit!)
├── .env.example          # Template konfigurasi
├── .gitignore
│
├── cogs/                 # Modul perintah (dipisah per kategori)
│   ├── moderation.py     # Kick, ban, timeout, clear, dll.
│   ├── info.py           # Userinfo, serverinfo, ping
│   └── events.py         # on_ready, on_member_join, dll.
│
├── utils/                # Helper & utilitas bersama
│   ├── logger.py         # Konfigurasi logging
│   └── embeds.py         # Helper embed Discord
│
├── logs/                 # File log (di-generate otomatis)
└── data/                 # Penyimpanan data lokal (opsional)
```

---

## ⚙️ Setup

### 1. Clone & masuk ke folder
```bash
git clone https://github.com/username/discord-bot.git
cd discord-bot
```

### 2. Buat virtual environment
```bash
python -m venv venv

# Aktifkan:
# Windows
venv\Scripts\activate
# Mac/Linux
source venv/bin/activate
```

### 3. Install dependensi
```bash
pip install -r requirements.txt
```

### 4. Konfigurasi `.env`
```bash
cp .env.example .env
```
Buka `.env` lalu isi nilainya:
```env
DISCORD_TOKEN=token_bot_kamu
GUILD_ID=id_server_kamu
BOT_PREFIX=!
LOG_CHANNEL_ID=id_channel_log   # opsional
```

### 5. Setup bot di Discord Developer Portal
1. Buka https://discord.com/developers/applications
2. **New Application** → beri nama → buka tab **Bot**
3. Klik **Reset Token** → copy token ke `.env`
4. Aktifkan **Privileged Gateway Intents**:
   - ✅ Server Members Intent
   - ✅ Message Content Intent
5. Undang bot: **OAuth2 → URL Generator**
   - Scope: `bot`
   - Permissions: `Administrator` (atau pilih manual)

### 6. Jalankan bot
```bash
python main.py
```

---

## 📋 Daftar Perintah

### 🛡️ Moderasi
| Perintah | Keterangan | Permission |
|---|---|---|
| `!kick @user [alasan]` | Kick member | Kick Members |
| `!ban @user [alasan]` | Ban member | Ban Members |
| `!unban Nama#1234` | Unban member | Ban Members |
| `!timeout @user [menit] [alasan]` | Timeout member | Moderate Members |
| `!untimeout @user` | Hapus timeout | Moderate Members |
| `!warn @user [alasan]` | Peringatkan via DM | Manage Messages |
| `!clear [1-100]` | Hapus pesan | Manage Messages |
| `!slowmode [detik]` | Atur slowmode | Manage Channels |
| `!lock` | Kunci channel | Manage Channels |
| `!unlock` | Buka channel | Manage Channels |

### ℹ️ Info
| Perintah | Keterangan |
|---|---|
| `!userinfo [@user]` | Info lengkap member |
| `!serverinfo` | Info server |
| `!avatar [@user]` | Lihat avatar member |
| `!ping` | Cek latensi bot |

---

## 🔧 Menambah Cog Baru

1. Buat file baru di folder `cogs/`, misalnya `cogs/fun.py`
2. Gunakan template berikut:

```python
from discord.ext import commands

class Fun(commands.Cog, name="Fun"):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="hello")
    async def hello(self, ctx):
        await ctx.send(f"Halo, {ctx.author.mention}!")

async def setup(bot):
    await bot.add_cog(Fun(bot))
```

3. Daftarkan di `main.py`:
```python
COGS = [
    "cogs.moderation",
    "cogs.info",
    "cogs.events",
    "cogs.fun",   # ← tambahkan di sini
]
```

---

## 📜 Lisensi
MIT
