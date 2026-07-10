import sqlite3
import time

DB_NAME = "vip_kullanicilar.sqlite"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            mexc_api_key TEXT NOT NULL,
            mexc_api_secret TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            trade_mode TEXT DEFAULT 'PERCENT',
            trade_amount REAL DEFAULT 5,
            max_trades INTEGER DEFAULT 8,
            tp_ratios TEXT DEFAULT '25,25,25,25',
            stop_mode TEXT DEFAULT 'NONE'
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS active_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            coin TEXT,
            yon TEXT,
            giris REAL,
            tp1 REAL,
            tp2 REAL,
            tp3 REAL,
            tp4 REAL,
            sl REAL,
            durum TEXT DEFAULT 'BEKLIYOR',
            asama INTEGER DEFAULT 0,
            eklenme_zamani REAL
        )
    ''')
    try:
        cursor.execute("ALTER TABLE active_signals ADD COLUMN eklenme_zamani REAL")
    except:
        pass
    conn.commit()
    conn.close()

def add_user(telegram_id, api_key, api_secret):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO users (telegram_id, mexc_api_key, mexc_api_secret, is_active, trade_mode, trade_amount, max_trades, tp_ratios, stop_mode)
        VALUES (?, ?, ?, 1, 'PERCENT', 5, 8, '25,25,25,25', 'NONE')
        ON CONFLICT(telegram_id) DO UPDATE SET
            mexc_api_key=excluded.mexc_api_key,
            mexc_api_secret=excluded.mexc_api_secret,
            is_active=1
    ''', (telegram_id, api_key, api_secret))
    conn.commit()
    conn.close()

def update_user_settings(telegram_id, mode, amount, max_trades):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET trade_mode = ?, trade_amount = ?, max_trades = ? WHERE telegram_id = ?", 
                   (mode, amount, max_trades, telegram_id))
    conn.commit()
    conn.close()

def update_tp_ratios(telegram_id, ratios):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET tp_ratios = ? WHERE telegram_id = ?", (ratios, telegram_id))
    conn.commit()
    conn.close()

def update_stop_mode(telegram_id, mode):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET stop_mode = ? WHERE telegram_id = ?", (mode, telegram_id))
    conn.commit()
    conn.close()

def toggle_user_active(telegram_id, durum):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET is_active = ? WHERE telegram_id = ?', (durum, telegram_id))
    conn.commit()
    conn.close()

def get_all_active_users():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE is_active = 1")
    users = cursor.fetchall()
    conn.close()
    return users

def sinyal_kaydet(coin, yon, giris, tp1, tp2, tp3, tp4, sl):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    su_an = time.time()
    cursor.execute('''
        INSERT INTO active_signals (coin, yon, giris, tp1, tp2, tp3, tp4, sl, durum, eklenme_zamani) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'BEKLIYOR', ?)
    ''', (coin, yon, giris, tp1, tp2, tp3, tp4, sl, su_an))
    conn.commit()
    conn.close()
