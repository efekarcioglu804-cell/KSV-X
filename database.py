import sqlite3

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
            max_trades INTEGER DEFAULT 8
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS active_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            coin TEXT,
            yon TEXT,
            giris REAL,
            tp1 REAL,
            sl REAL,
            durum TEXT DEFAULT 'BEKLIYOR' 
        )
    ''')
    conn.commit()
    conn.close()

def add_user(telegram_id, api_key, api_secret):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO users (telegram_id, mexc_api_key, mexc_api_secret, is_active, trade_mode, trade_amount, max_trades)
        VALUES (?, ?, ?, 1, 'PERCENT', 5, 8)
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
    cursor.execute('''
        UPDATE users 
        SET trade_mode = ?, trade_amount = ?, max_trades = ? 
        WHERE telegram_id = ?
    ''', (mode, amount, max_trades, telegram_id))
    conn.commit()
    conn.close()

def get_all_active_users():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT telegram_id, mexc_api_key, mexc_api_secret, trade_mode, trade_amount, max_trades 
        FROM users WHERE is_active = 1
    ''')
    users = cursor.fetchall()
    conn.close()
    return [{
        "telegram_id": row[0], "api_key": row[1], "api_secret": row[2], 
        "trade_mode": row[3], "trade_amount": row[4], "max_trades": row[5]
    } for row in users]

def sinyal_kaydet(coin, yon, giris, tp1, sl):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO active_signals (coin, yon, giris, tp1, sl, durum) 
        VALUES (?, ?, ?, ?, ?, 'BEKLIYOR')
    ''', (coin, yon, giris, tp1, sl))
    conn.commit()
    conn.close()
    
def toggle_user_active(telegram_id, durum):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET is_active = ? WHERE telegram_id = ?', (durum, telegram_id))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
