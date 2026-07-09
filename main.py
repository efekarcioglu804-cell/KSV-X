import asyncio
import sqlite3
import ccxt.async_support as ccxt
from telethon import TelegramClient, events

import config
import database as db
from parser import parse_signal
from trader import islem_ac

# ----- KRİTİK DÜZELTME: PYTHON 3.14 EVENT LOOP UYUMU -----
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
# ----------------------------------------------------------

client = TelegramClient('kralin_makinesi_session', config.API_ID, config.API_HASH)
VIP_KANAL_ID = int(config.VIP_CHANNEL)

# Kralın ID'si
KRALIN_ID = 39983605 

@client.on(events.NewMessage(func=lambda e: e.is_private))
async def dm_handler(event):
    mesaj = event.message.message
    gonderen_id = event.sender_id
    
    if mesaj.startswith('/kayit'):
        try:
            _, api_key, api_secret = mesaj.split()
            db.add_user(gonderen_id, api_key, api_secret)
            await event.reply("✅ Kralın Sinyalleri VIP sistemine hoş geldin!\nAPI anahtarların şifrelenerek kasaya kilitlendi.\n\nRisk ayarlarını yapmak için /ayar komutunu kullan.\nÖrnek:\nYüzde için: `/ayar PERCENT 5 8` (Kasanın %5'i, Max 8 İşlem)\nSabit için: `/ayar FIXED 50 5` (İşlem başı 50 USDT, Max 5 İşlem)")
        except ValueError:
            await event.reply("❌ Hatalı kullanım!\nDoğrusu: `/kayit API_KEY API_SECRET`")

    elif mesaj.startswith('/ayar'):
        try:
            _, mod, miktar, max_islem = mesaj.split()
            if mod.upper() not in ['PERCENT', 'FIXED']:
                raise ValueError("Mod hatalı")
                
            db.update_user_settings(gonderen_id, mod.upper(), float(miktar), int(max_islem))
            await event.reply(f"⚙️ Ayarların güncellendi!\nMod: {mod.upper()}\nMiktar: {miktar}\nMaksimum Açık İşlem: {max_islem}")
        except Exception:
            await event.reply("❌ Hatalı kullanım!\nÖrnek: `/ayar PERCENT 5 8` veya `/ayar FIXED 50 5`")
            
    elif mesaj.startswith('/durdur'):
        db.toggle_user_active(gonderen_id, 0)
        await event.reply("🛑 Bot uyku moduna alındı! Artık gelen sinyaller sende işlem açmayacak.\nYeniden başlatmak için `/devam` yazabilirsin.")

    elif mesaj.startswith('/devam'):
        db.toggle_user_active(gonderen_id, 1)
        await event.reply("✅ Kalkanlar indirildi, silahlar aktif! Bot yeniden piyasayı dinliyor... 🦅")
        
    elif mesaj == '/fisi_cek':
        if gonderen_id == KRALIN_ID:
            await event.reply("🚨 KRAL EMRİ ALINDI. TÜM SİSTEM FİŞTEN ÇEKİLİYOR... 🚨")
            print("!!! ACİL DURUM ŞALTERİ ÇEKİLDİ. SİSTEM KAPATILIYOR !!!")
            await client.disconnect() 
        else:
            await event.reply("❌ Bu komutu sadece Kral kullanabilir.")

@client.on(events.NewMessage(chats=VIP_KANAL_ID))
async def sinyal_handler(event):
    mesaj_metni = event.message.message
    sinyal_verisi = parse_signal(mesaj_metni)
    
    if not sinyal_verisi: return
        
    print(f"\n🚀 [YENİ SİNYAL] {sinyal_verisi['coin']} için operasyon başlatılıyor...")
    db.sinyal_kaydet(
        sinyal_verisi['coin'], sinyal_verisi['yon'], 
        sinyal_verisi['giris'], sinyal_verisi['tp_listesi'][0], sinyal_verisi['sl']
    )
    
    aktif_uyeler = db.get_all_active_users()
    if not aktif_uyeler: return
        
    gorevler = []
    for uye in aktif_uyeler:
        ayarlar = {
            'trade_mode': uye['trade_mode'],
            'trade_amount': uye['trade_amount'],
            'max_trades': uye['max_trades']
        }
        gorev = islem_ac(uye['api_key'], uye['api_secret'], ayarlar, sinyal_verisi)
        gorevler.append(gorev)
        
    sonuclar = await asyncio.gather(*gorevler, return_exceptions=True)
    basarili = sum(1 for r in sonuclar if isinstance(r, dict) and r.get('durum') == 'BASARILI')
    print(f"✅ Operasyon Tamamlandı: {len(aktif_uyeler)} üyeden {basarili} tanesine emir iletildi.")

async def fiyat_takip_radari():
    # Eski, hatalı olan "await client.wait_until_ready()" satırı buradan sökülüp atıldı.
    borsa = ccxt.mexc()
    
    while True:
        try:
            conn = sqlite3.connect(db.DB_NAME)
            cursor = conn.cursor()
            cursor.execute("SELECT id, coin, yon, giris, tp1, sl, durum FROM active_signals WHERE durum IN ('BEKLIYOR', 'ISLEMDE')")
            bekleyenler = cursor.fetchall()
            
            if bekleyenler:
                tickerlar = await borsa.fetch_tickers()
                
                for sinyal in bekleyenler:
                    s_id, coin, yon, giris, tp1, sl, durum = sinyal
                    sembol = coin.replace('USDT', '') + '/USDT:USDT'
                    
                    if sembol in tickerlar:
                        guncel_fiyat = tickerlar[sembol]['last']
                        
                        yeni_durum, bildirim = None, None
                        
                        # 1. AŞAMA: ENTRY KONTROLÜ
                        if durum == 'BEKLIYOR':
                            entry_vurdu_mu = (yon == 'LONG' and guncel_fiyat <= giris) or (yon == 'SHORT' and guncel_fiyat >= giris)
                            if entry_vurdu_mu:
                                yeni_durum = 'ISLEMDE'
                                bildirim = f"🟢 **İŞLEME GİRİLDİ!** 🟢\n\n#{coin} {yon} işlemi {giris} seviyesinden aktifleşti!\nHedefler bekleniyor... 🚀"
                        
                        # 2. AŞAMA: TP VE SL KONTROLÜ
                        elif durum == 'ISLEMDE':
                            tp_vurdu_mu = (yon == 'LONG' and guncel_fiyat >= tp1) or (yon == 'SHORT' and guncel_fiyat <= tp1)
                            stop_oldu_mu = (yon == 'LONG' and guncel_fiyat <= sl) or (yon == 'SHORT' and guncel_fiyat >= sl)
                            
                            if tp_vurdu_mu:
                                yeni_durum = 'TP_VURDU'
                                bildirim = f"🎯 **HEDEF VURULDU!** 🎯\n\n#{coin} {yon} işlemimiz başarıyla TP1 hedefine ulaştı!\nKralın Sinyalleri kazandırmaya devam ediyor. 👑💰"
                            elif stop_oldu_mu:
                                yeni_durum = 'STOP_OLDU'
                                bildirim = f"🛡 **Kalkan Devrede (STOP)** 🛡\n\n#{coin} {yon} işlemi stop seviyesine ulaştı. Kasa güvenliği sağlandı."
                            
                        if yeni_durum:
                            cursor.execute("UPDATE active_signals SET durum = ? WHERE id = ?", (yeni_durum, s_id))
                            conn.commit()
                            await client.send_message(VIP_KANAL_ID, bildirim)
            conn.close()
        except Exception as e:
            print(f"Radar Hatası: {e}")
        
        await asyncio.sleep(30)

async def main():
    print("Sistem ayağa kaldırılıyor...")
    await client.start(bot_token=config.BOT_TOKEN)
    print("🤖 VIP Bot Telegram'a bağlandı.")
    
    db.init_db()
    client.loop.create_task(fiyat_takip_radari())
    print("🦅 Fiyat Radarı (Tracker) çalıştırıldı. Hedefler bekleniyor...")
    
    print("\n👑 KRALIN MAKİNESİ TAMAMEN AKTİF. EMİRLERİNİZİ BEKLİYOR. 👑\n")
    await client.run_until_disconnected()

if __name__ == '__main__':
    # asyncio.run(main()) yerine manuel kurduğumuz loop'u çağırıyoruz.
    loop.run_until_complete(main())
