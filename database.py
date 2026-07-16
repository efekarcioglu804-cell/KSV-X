import sqlite3
import time
import datetime

DB_NAME = "vip_kullanicilar.sqlite"

def get_connection():
    return sqlite3.connect(DB_NAME, timeout=30)

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;") 
    
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
            kaldirac INTEGER DEFAULT 20,
            durum TEXT DEFAULT 'BEKLIYOR',
            asama INTEGER DEFAULT 0,
            eklenme_zamani REAL,
            katilanlar TEXT DEFAULT '',
            rsi_degeri REAL DEFAULT 0.0,
            macd_degeri REAL DEFAULT 0.0,
            hacim_degeri REAL DEFAULT 0.0,
            atr REAL DEFAULT 0.0,
            fear_greed INTEGER DEFAULT 50,
            en_iyi_fiyat REAL DEFAULT 0.0,
            mum_gecmisi TEXT DEFAULT '[]'
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_daily_stats (
            telegram_id INTEGER,
            tarih TEXT,
            acilan_islem INTEGER DEFAULT 0,
            tp_adet INTEGER DEFAULT 0,
            stop_adet INTEGER DEFAULT 0,
            be_adet INTEGER DEFAULT 0,
            kar_usdt REAL DEFAULT 0.0,
            PRIMARY KEY (telegram_id, tarih)
        )
    ''')
    
    # Yeni odaları eski tabloya enjekte et
    try: cursor.execute("ALTER TABLE active_signals ADD COLUMN eklenme_zamani REAL")
    except: pass
    try: cursor.execute("ALTER TABLE active_signals ADD COLUMN katilanlar TEXT DEFAULT ''")
    except: pass
    try: cursor.execute("ALTER TABLE active_signals ADD COLUMN kaldirac INTEGER DEFAULT 20")
    except: pass
    try: cursor.execute("ALTER TABLE user_daily_stats ADD COLUMN be_adet INTEGER DEFAULT 0")
    except: pass
    try: cursor.execute("ALTER TABLE active_signals ADD COLUMN rsi_degeri REAL DEFAULT 0.0")
    except: pass
    try: cursor.execute("ALTER TABLE active_signals ADD COLUMN macd_degeri REAL DEFAULT 0.0")
    except: pass
    try: cursor.execute("ALTER TABLE active_signals ADD COLUMN hacim_degeri REAL DEFAULT 0.0")
    except: pass
    try: cursor.execute("ALTER TABLE active_signals ADD COLUMN atr REAL DEFAULT 0.0")
    except: pass
    try: cursor.execute("ALTER TABLE active_signals ADD COLUMN fear_greed INTEGER DEFAULT 50")
    except: pass
    try: cursor.execute("ALTER TABLE active_signals ADD COLUMN en_iyi_fiyat REAL DEFAULT 0.0")
    except: pass
    try: cursor.execute("ALTER TABLE active_signals ADD COLUMN mum_gecmisi TEXT DEFAULT '[]'")
    except: pass
    
    conn.commit()
    conn.close()

def add_user(telegram_id, api_key, api_secret):
    conn = get_connection()
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
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET trade_mode = ?, trade_amount = ?, max_trades = ? WHERE telegram_id = ?", 
                   (mode, amount, max_trades, telegram_id))
    conn.commit()
    conn.close()

def update_tp_ratios(telegram_id, ratios):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET tp_ratios = ? WHERE telegram_id = ?", (ratios, telegram_id))
    conn.commit()
    conn.close()

def update_stop_mode(telegram_id, mode):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET stop_mode = ? WHERE telegram_id = ?", (mode, telegram_id))
    conn.commit()
    conn.close()

def toggle_user_active(telegram_id, durum):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET is_active = ? WHERE telegram_id = ?', (durum, telegram_id))
    conn.commit()
    conn.close()

def get_all_active_users():
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE is_active = 1")
    users = cursor.fetchall()
    conn.close()
    return users

def sinyal_kaydet(coin, yon, giris, tp1, tp2, tp3, tp4, sl, kaldirac=20, rsi=0.0, macd=0.0, hacim=0.0, atr=0.0, fng=50, mum_video='[]'):
    conn = get_connection()
    cursor = conn.cursor()
    su_an = time.time()
    # İlk kayıt anında en iyi fiyat, giriş fiyatıdır
    cursor.execute('''
        INSERT INTO active_signals 
        (coin, yon, giris, tp1, tp2, tp3, tp4, sl, kaldirac, durum, eklenme_zamani, rsi_degeri, macd_degeri, hacim_degeri, atr, fear_greed, en_iyi_fiyat, mum_gecmisi) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'BEKLIYOR', ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (coin, yon, giris, tp1, tp2, tp3, tp4, sl, kaldirac, su_an, rsi, macd, hacim, atr, fng, giris, mum_video))
    signal_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return signal_id

def sinyale_katilan_ekle(signal_id, telegram_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT katilanlar FROM active_signals WHERE id = ?", (signal_id,))
    row = cursor.fetchone()
    if row:
        mevcut = row[0] if row[0] else ""
        if str(telegram_id) not in mevcut.split(','):
            yeni = mevcut + f"{telegram_id},"
            cursor.execute("UPDATE active_signals SET katilanlar = ? WHERE id = ?", (yeni, signal_id))
            conn.commit()
    conn.close()

def update_daily_stat(telegram_id, stat_type, value=1, profit=0.0):
    tarih = datetime.date.today().strftime("%Y-%m-%d")
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO user_daily_stats (telegram_id, tarih, acilan_islem, tp_adet, stop_adet, be_adet, kar_usdt)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(telegram_id, tarih) DO UPDATE SET
            acilan_islem = acilan_islem + excluded.acilan_islem,
            tp_adet = tp_adet + excluded.tp_adet,
            stop_adet = stop_adet + excluded.stop_adet,
            be_adet = be_adet + excluded.be_adet,
            kar_usdt = kar_usdt + excluded.kar_usdt
    ''', (
        telegram_id, tarih, 
        value if stat_type == 'open' else 0,
        value if stat_type == 'tp' else 0,
        value if stat_type == 'stop' else 0,
        value if stat_type == 'be' else 0,
        profit
    ))
    conn.commit()
    conn.close()

def get_daily_stats(telegram_id):
    tarih = datetime.date.today().strftime("%Y-%m-%d")
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM user_daily_stats WHERE telegram_id = ? AND tarih = ?", (telegram_id, tarih))
    res = cursor.fetchone()
    conn.close()
    return res
