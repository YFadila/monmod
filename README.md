# 🤖 Discord Moderation Bot

Bot moderasi server Discord sederhana, dibangun dengan `discord.py`.

> **Changelog terbaru:**
> - ✅ Sistem **warn points** dengan tindakan otomatis (timeout / kick / ban)
> - ✅ **Riwayat warn** lengkap per member, termasuk siapa yang memberi warn
> - ✅ **Soft-delete warn** — warn yang di-clear tetap tercatat beserta siapa yang menghapusnya
> - ✅ Sistem **konfigurasi per-server** (`!config`) tanpa perlu deploy ulang
> - ✅ Sistem **warn decay** otomatis — poin warn hilang sendiri setelah N hari tanpa pelanggaran
> - ✅ **Custom prefix per-server** — setiap server bisa pakai prefix sendiri

---

## 📁 Struktur Project

```
discord-bot/
├── main.py               # Entry point utama (command_prefix = get_prefix)
├── requirements.txt      # Dependensi Python
├── .env                  # Konfigurasi rahasia (JANGAN di-commit!)
├── .env.example          # Template konfigurasi
├── .gitignore
│
├── cogs/                 # Modul perintah (dipisah per kategori)
│   ├── moderation.py     # Kick, ban, timeout, warn, config, dll.
│   ├── prefix.py         # Custom prefix per-server
│   ├── info.py           # Userinfo, serverinfo, ping
│   └── events.py         # on_ready, on_member_join, dll.
│
├── utils/                # Helper & utilitas bersama
│   ├── logger.py         # Konfigurasi logging
│   └── embeds.py         # Helper embed Discord
│
├── logs/                 # File log (di-generate otomatis)
└── data/                 # Penyimpanan data lokal (di-generate otomatis)
    ├── warns.json        # Riwayat warn semua member (soft-delete)
    ├── guild_config.json # Konfigurasi moderasi per-server
    └── prefixes.json     # Custom prefix per-server
```

---

## ⚙️ Setup

### 1. Clone & masuk ke folder
```bash
git clone https://github.com/YFadila/monmod.git
cd monmod
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
BOT_PREFIX=!                    # prefix default (fallback jika server belum set custom prefix)
LOG_CHANNEL_ID=id_channel_log   # opsional, bisa di-override per-server via !config setlog
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
| `!warn @user [alasan]` | Peringatkan member via DM + catat warn point | Manage Messages |
| `!clear [1-100]` | Hapus pesan | Manage Messages |
| `!slowmode [detik]` | Atur slowmode | Manage Channels |
| `!lock` | Kunci channel | Manage Channels |
| `!unlock` | Buka channel | Manage Channels |

### ⚠️ Sistem Warn
| Perintah | Keterangan | Permission |
|---|---|---|
| `!warn @user [alasan]` | Beri warn + trigger tindakan otomatis jika threshold tercapai | Manage Messages |
| `!warnlist @user` | Lihat riwayat warn lengkap (aktif & yang sudah di-clear) | Manage Messages |
| `!warns @user` | Alias dari `!warnlist` | Manage Messages |
| `!warnhistory @user` | Alias dari `!warnlist` | Manage Messages |
| `!mywarns` | Lihat riwayat warnmu sendiri (dikirim via DM) | Semua member |
| `!clearwarns @user [alasan]` | Clear semua warn aktif (riwayat tetap tersimpan) | Administrator |

**Threshold warn default** (dapat diubah per-server via `!config`):

| Jumlah Warn | Tindakan Otomatis |
|---|---|
| 3 warn | Timeout 5 menit |
| 5 warn | Kick |
| 7 warn | Ban permanen |

**Sistem Decay Warn:**
Setiap poin warn akan hilang otomatis jika member tidak melakukan pelanggaran selama N hari (default: 30 hari). Timer dihitung dari warn **terakhir** yang diterima — jika ada warn baru, semua timer reset. Warn yang expire tetap tersimpan di riwayat sebagai `expired` untuk audit trail.

Contoh dengan decay 30 hari:
- Member punya 2 warn aktif terakhir diterima 1 Jan
- Poin ke-1 expire 31 Jan (1 × 30 hari)
- Poin ke-2 expire 1 Mar (2 × 30 hari)
- Jika member dapat warn baru di 15 Jan → timer reset, poin ke-1 expire 14 Feb, poin ke-2 expire 16 Mar

> **Catatan:** Warn yang di-clear menggunakan *soft-delete* — data tidak dihapus, hanya ditandai sebagai `cleared`. Riwayat siapa yang men-clear, kapan, dan alasannya tetap bisa dilihat lewat `!warnlist`.

### ⚙️ Konfigurasi Server
Semua perintah `!config` hanya bisa digunakan oleh **Administrator** server. Setiap perubahan hanya berlaku untuk server tersebut dan tidak mempengaruhi server lain.

| Perintah | Contoh | Keterangan |
|---|---|---|
| `!config show` | — | Lihat semua konfigurasi aktif server ini |
| `!config setwarn <N> <aksi>` | `!config setwarn 4 kick` | Atur tindakan otomatis pada warn ke-N |
| `!config removewarn <N>` | `!config removewarn 5` | Hapus threshold warn ke-N |
| `!config setTimeout <menit>` | `!config setTimeout 10` | Ubah durasi auto-timeout |
| `!config setdecay <hari>` | `!config setdecay 14` | Ubah durasi decay warn (0 = nonaktif) |
| `!config setlog <#channel>` | `!config setlog #mod-log` | Atur channel log moderasi |
| `!config setlog clear` | — | Hapus channel log custom (kembali ke `.env`) |
| `!config reset` | — | Reset semua konfigurasi server ke default |

**Aksi yang tersedia untuk `setwarn`:** `timeout` · `kick` · `ban` · `none` (nonaktifkan threshold)

### 🔧 Custom Prefix
Setiap server bisa mengatur prefix sendiri. Bot juga **selalu** merespons mention (`@BotName`) sebagai prefix darurat jika prefix terlupa.

| Perintah | Contoh | Keterangan | Permission |
|---|---|---|---|
| `!prefix` | — | Lihat prefix aktif server ini | Semua member |
| `!setprefix <prefix>` | `!setprefix ??` | Ganti prefix bot untuk server ini | Administrator |
| `!resetprefix` | — | Kembalikan prefix ke default | Administrator |

> **Tips:** Jika lupa prefix server, selalu bisa pakai `@BotName setprefix !` untuk reset via mention.

### ℹ️ Info
| Perintah | Keterangan |
|---|---|
| `!userinfo [@user]` | Info lengkap member |
| `!serverinfo` | Info server |
| `!avatar [@user]` | Lihat avatar member |
| `!ping` | Cek latensi bot |

---

## 💾 Penyimpanan Data

Folder `data/` dibuat otomatis saat bot pertama kali dijalankan. Pastikan folder ini **tidak di-commit** ke Git karena berisi data server.

Tambahkan ke `.gitignore`:
```
data/
logs/
.env
```

Struktur data warn di `warns.json` menggunakan sistem **soft-delete**: warn yang di-clear tidak dihapus permanen, melainkan ditandai dengan status `cleared` beserta informasi siapa yang melakukan clear dan kapan. Warn yang expire otomatis ditandai `expired`. Ini memungkinkan audit trail yang lengkap.

Custom prefix tiap server disimpan di `prefixes.json` dengan key berupa guild ID. Server yang belum pernah set prefix tidak punya entri di file ini dan akan memakai nilai `BOT_PREFIX` dari `.env`.

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
    "cogs.prefix",        # selalu pertama
    "cogs.moderation",
    "cogs.info",
    "cogs.events",
    "cogs.fun",   # ← tambahkan di sini
]
```

---

## 📜 Lisensi
MIT