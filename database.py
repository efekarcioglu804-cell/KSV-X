import sqlite3

# Veritabanı dosyamızın adı. Kod çalıştığında klasörde otomatik oluşacak.
DB_NAME = "vip_kullanicilar.sqlite"

def init_db():
    """Sistemin kalbini (Veritabanı ve Tabloları) oluşturur."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Kullanıcılar tablosunu yaratıyoruz. 
    # telegram_id benzersiz (PRIMARY KEY) olmak zorunda.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            mexc_api_key TEXT NOT NULL,
            mexc_api_secret TEXT NOT NULL,
            is_active INTEGER DEFAULT 1
        )
    ''')
    conn.commit()
    conn.close()
    print("Veritabanı modülü devrede. VIP kayıtları için hazır.")

def add_user(telegram_id, api_key, api_secret):
    """Yeni VIP üye ekler. Üye zaten varsa API bilgilerini günceller."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # ON CONFLICT ile aynı adam ikinci kez kayıt olursa hata vermek yerine güncelliyoruz.
    cursor.execute('''
        INSERT INTO users (telegram_id, mexc_api_key, mexc_api_secret, is_active)
        VALUES (?, ?, ?, 1)
        ON CONFLICT(telegram_id) DO UPDATE SET
            mexc_api_key=excluded.mexc_api_key,
            mexc_api_secret=excluded.mexc_api_secret,
            is_active=1
    ''', (telegram_id, api_key, api_secret))
    
    conn.commit()
    conn.close()

def remove_user(telegram_id):
    """Kullanıcının sistemden sinyal almasını (üyeliğini) durdurur."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET is_active = 0 WHERE telegram_id = ?', (telegram_id,))
    conn.commit()
    conn.close()

def get_all_active_users():
    """Sinyal geldiğinde emrin iletileceği tüm aktif VIP üyeleri mermiye dizer."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT telegram_id, mexc_api_key, mexc_api_secret FROM users WHERE is_active = 1')
    users = cursor.fetchall()
    conn.close()
    
    # Veriyi diğer dosyalarda kolay kullanmak için liste içinde sözlük (dict) olarak döndürüyoruz.
    return [{"telegram_id": row[0], "api_key": row[1], "api_secret": row[2]} for row in users]

# Dosya ilk kez çalıştırıldığında tabloları kursun diye init_db() çağrılır.
if __name__ == "__main__":
    init_db()
