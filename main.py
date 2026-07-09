import asyncio
import sqlite3
import ccxt.async_support as ccxt
from telethon import TelegramClient, events

# Yazdığımız modülleri içeri alıyoruz
import config
import database as db
from parser import parse_signal
from trader import islem_ac

# Telethon İstemcisini Başlatıyoruz
client = TelegramClient('kralin_makinesi_session', config.API_ID, config.API_HASH)
VIP_KANAL_ID = int(config.VIP_CHANNEL)

# ---------------------------------------------------------
# 1. BÖLÜM: ÜYE YÖNETİMİ VE AYARLAR (ÖZEL MESAJ - DM)
# ---------------------------------------------------------
@client.on(events.NewMessage(func=lambda e: e.is_private))
async def dm_handler(event):
    mesaj = event.message.message
    gonderen_id = event.sender_id
    
    # KULLANICI KAYIT KOMUTU
    if mesaj.startswith('/kayit'):
        try:
            _, api_key, api_secret = mesaj.split()
            db.add_user(gonderen_id, api_key, api_secret)
            await event.reply("✅ Kralın Sinyalleri VIP sistemine hoş geldin!\nAPI anahtarların şifrelenerek kasaya kilitlendi.\n\nRisk ayarlarını yapmak için /ayar komutunu kullan.\nÖrnek:\nYüzde için: `/ayar PERCENT 5 8` (Kasanın %5'i, Max 8 İşlem)\nSabit için: `/ayar FIXED 50 5` (İşlem başı 50 USDT, Max 5 İşlem)")
        except ValueError:
            await event.reply("❌ Hatalı kullanım!\nDoğrusu: `/kayit API_KEY API_SECRET`")

    # KULLANICI AYAR KOMUTU
    elif mesaj.startswith('/ayar'):
        try:
            _, mod, miktar, max_islem = mesaj.split()
            if mod.upper() not in ['PERCENT', 'FIXED']:
                raise ValueError("Mod hatalı")
                
            db.update_user_settings(gonderen_id, mod.upper(), float(miktar), int(max_islem))
            await event.reply(f"⚙️ Ayarların güncellendi!\nMod: {mod.upper()}\nMiktar: {miktar}\nMaksimum Açık İşlem: {max_islem}")
        except Exception:
            await event.reply("❌ Hatalı kullanım!\nÖrnek 1: `/ayar PERCENT 5 8`\nÖrnek 2: `/ayar FIXED 50 5`")


# ---------------------------------------------------------
# 2. BÖLÜM: SİNYAL YAKALAMA VE ATEŞLEME (VIP KANAL)
# ---------------------------------------------------------
@client.on(events.NewMessage(chats=VIP_KANAL_ID))
async def sinyal_handler(event):
    mesaj_metni = event.message.message
    
    # 1. Adım: Sinyali Parçala
    sinyal_verisi = parse_signal(mesaj_metni)
    
    # Eğer gelen mesaj bir sinyal değilse (sohbet vb.) işlemi yoksay
    if not sinyal_verisi:
        return
        
    print(f"\n🚀 [YENİ SİNYAL] {sinyal_verisi['coin']} için operasyon başlatılıyor...")
    
    # 2. Adım: Fiyat takibi için veritabanına kaydet
    db.sinyal_kaydet(
        sinyal_verisi['coin'], 
        sinyal_verisi['yon'], 
        sinyal_verisi['giris'], 
        sinyal_verisi['tp_listesi'][0], 
        sinyal_verisi['sl']
    )
    
    # 3. Adım: Aktif VIP Üyeleri Çek
    aktif_uyeler = db.get_all_active_users()
    if not aktif_uyeler:
        print("Sistemde kayıtlı veya aktif VIP üye bulunamadı.")
        return
        
    # 4. Adım: Asenkron (Eşzamanlı) Ateşleme
    gorevler = []
    for uye in aktif_uyeler:
        # trader.py içindeki islem_ac fonksiyonunu görev olarak listeye ekliyoruz
        ayarlar = {
            'trade_mode': uye['trade_mode'],
            'trade_amount': uye['trade_amount'],
            'max_trades': uye['max_trades']
        }
        gorev = islem_ac(uye['api_key'], uye['api_secret'], ayarlar, sinyal_verisi)
        gorevler.append(gorev)
        
    # Tüm görevleri tek bir milisaniyede borsaya yolluyoruz
    sonuclar = await asyncio.gather(*gorevler, return_exceptions=True)
    
    basarili = sum(1 for r in sonuclar if isinstance(r, dict) and r.get('durum') == 'BASARILI')
    print(f"✅ Operasyon Tamamlandı: {len(aktif_uyeler)} üyeden {basarili} tanesine emir başarıyla iletildi.")


# ---------------------------------------------------------
# 3. BÖLÜM: PİYASA RADARI (SÜREKLİ TAKİP VE BİLDİRİM)
# ---------------------------------------------------------
async def fiyat_takip_radari():
    """Arka planda sürekli çalışarak açık sinyallerin fiyatlarını kontrol eder."""
    await client.wait_until_ready()
    # Fiyat okumak için genel (API Key gerektirmeyen) bir borsa nesnesi
    borsa = ccxt.mexc()
    
    while True:
        try:
            # Veritabanından bekleyen sinyalleri çekiyoruz
            conn = sqlite3.connect(db.DB_NAME)
            cursor = conn.cursor()
            cursor.execute("SELECT id, coin, yon, giris, tp1, sl FROM active_signals WHERE durum = 'BEKLIYOR'")
            bekleyenler = cursor.fetchall()
            
            if bekleyenler:
                # MEXC'den güncel tüm fiyatları tek seferde çekiyoruz (Rate Limit yememek için)
                tickerlar = await borsa.fetch_tickers()
                
                for sinyal in bekleyenler:
                    s_id, coin, yon, giris, tp1, sl = sinyal
                    sembol = coin.replace('USDT', '') + '/USDT:USDT'
                    
                    if sembol in tickerlar:
                        guncel_fiyat = tickerlar[sembol]['last']
                        
                        # HEDEF (TP) KONTROLÜ
                        tp_vurdu_mu = (yon == 'LONG' and guncel_fiyat >= tp1) or (yon == 'SHORT' and guncel_fiyat <= tp1)
                        # STOP LOSS (SL) KONTROLÜ
                        stop_oldu_mu = (yon == 'LONG' and guncel_fiyat <= sl) or (yon == 'SHORT' and guncel_fiyat >= sl)
                        
                        yeni_durum = None
                        bildirim = None
                        
                        if tp_vurdu_mu:
                            yeni_durum = 'TP_VURDU'
                            bildirim = f"🎯 **HEDEF VURULDU!** 🎯\n\n#{coin} {yon} işlemimiz başarıyla TP1 hedefine ulaştı!\nKralın Sinyalleri kazandırmaya devam ediyor. 👑💰"
                        elif stop_oldu_mu:
                            yeni_durum = 'STOP_OLDU'
                            bildirim = f"🛡 **Kalkan Devrede (STOP)** 🛡\n\n#{coin} {yon} işlemi stop seviyesine ulaştı. Kasa güvenliği sağlandı, bir sonraki fırsata odaklanıyoruz."
                            
                        # Durum değiştiyse veritabanını güncelle ve VIP kanala mesaj at
                        if yeni_durum:
                            cursor.execute("UPDATE active_signals SET durum = ? WHERE id = ?", (yeni_durum, s_id))
                            conn.commit()
                            await client.send_message(VIP_KANAL_ID, bildirim)
                            
            conn.close()
            
        except Exception as e:
            print(f"Radar Hatası: {e}")
            
        # Piyasayı 30 saniyede bir tarar (Sunucuyu ve borsa API'sini yormamak için ideal süre)
        await asyncio.sleep(30)


# ---------------------------------------------------------
# 4. BÖLÜM: MOTORU ÇALIŞTIRMA
# ---------------------------------------------------------
async def main():
    print("Sistem ayağa kaldırılıyor...")
    
    # 1. Telethon botunu başlat
    await client.start(bot_token=config.BOT_TOKEN)
    print("🤖 VIP Bot Telegram'a bağlandı.")
    
    # 2. Veritabanını kontrol et/oluştur
    db.init_db()
    
    # 3. Fiyat Takip Radarını arka planda asenkron olarak başlat
    client.loop.create_task(fiyat_takip_radari())
    print("🦅 Fiyat Radarı (Tracker) çalıştırıldı. Hedefler bekleniyor...")
    
    print("\n👑 KRALIN MAKİNESİ TAMAMEN AKTİF. EMİRLERİNİZİ BEKLİYOR. 👑\n")
    
    # Botun kapanmasını engeller, sonsuza kadar dinler
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
