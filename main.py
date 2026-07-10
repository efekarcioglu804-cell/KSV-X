import asyncio
import sqlite3
import ccxt.async_support as ccxt
from telethon import TelegramClient, events

import config
import database as db
from parser import parse_signal
from trader import islem_ac

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

client = TelegramClient('kralin_makinesi_session', config.API_ID, config.API_HASH)
VIP_KANAL_ID = int(config.VIP_CHANNEL)
KRALIN_ID = 39983605 

@client.on(events.NewMessage(func=lambda e: e.is_private))
async def dm_handler(event):
    mesaj = event.message.message
    gonderen_id = event.sender_id
    
    if mesaj == '/start':
        await event.reply("👑 **Kralın Sinyalleri VIP Sistemine Hoş Geldin.** 👑\nSisteme entegre olmak için:\n`/kayit API_KEY API_SECRET`")
        return

    if mesaj.startswith('/kayit'):
        try:
            _, api_key, api_secret = mesaj.split()
            db.add_user(gonderen_id, api_key, api_secret)
            await event.reply("✅ Kasaya kilitlendi! Risk ayarları için örnek:\n`/ayar PERCENT 5 8` veya `/ayar FIXED 50 5`")
        except ValueError:
            await event.reply("❌ Doğrusu: `/kayit API_KEY API_SECRET`")

    elif mesaj.startswith('/ayar'):
        try:
            _, mod, miktar, max_islem = mesaj.split()
            if mod.upper() not in ['PERCENT', 'FIXED']: raise ValueError
            db.update_user_settings(gonderen_id, mod.upper(), float(miktar), int(max_islem))
            await event.reply(f"⚙️ Ayarlandı! Mod: {mod.upper()}, Miktar: {miktar}, Max İşlem: {max_islem}")
        except:
            await event.reply("❌ Örnek: `/ayar PERCENT 5 8`")

    elif mesaj.startswith('/durdur'):
        db.toggle_user_active(gonderen_id, 0)
        await event.reply("🛑 Bot uyku moduna alındı!")

    elif mesaj.startswith('/devam'):
        db.toggle_user_active(gonderen_id, 1)
        await event.reply("✅ Kalkanlar indirildi, silahlar aktif! 🦅")
        
    elif mesaj == '/fisi_cek':
        if gonderen_id == KRALIN_ID:
            await event.reply("🚨 KRAL EMRİ ALINDI. TÜM SİSTEM FİŞTEN ÇEKİLİYOR... 🚨")
            await client.disconnect() 
        else:
            await event.reply("❌ Bu komutu sadece Kral kullanabilir.")

@client.on(events.NewMessage(chats=VIP_KANAL_ID))
async def sinyal_handler(event):
    mesaj = event.message.message
    sinyal = parse_signal(mesaj)
    if not sinyal: return
        
    print(f"\n🚀 [YENİ SİNYAL] {sinyal['coin']} operasyonu başlatılıyor...")
    db.sinyal_kaydet(
        sinyal['coin'], sinyal['yon'], sinyal['giris'], 
        sinyal['tp1'], sinyal['tp2'], sinyal['tp3'], sinyal['tp4'], sinyal['sl']
    )
    
    aktif_uyeler = db.get_all_active_users()
    if not aktif_uyeler: return
        
    gorevler = []
    for uye in aktif_uyeler:
        ayarlar = {'trade_mode': uye['trade_mode'], 'trade_amount': uye['trade_amount'], 'max_trades': uye['max_trades']}
        gorevler.append(islem_ac(uye['mexc_api_key'], uye['mexc_api_secret'], ayarlar, sinyal))
        
    sonuclar = await asyncio.gather(*gorevler, return_exceptions=True)
    basarili = sum(1 for r in sonuclar if isinstance(r, dict) and r.get('durum') == 'BASARILI')
    print(f"✅ Operasyon: {len(aktif_uyeler)} üyeden {basarili} tanesine iletildi.")

async def fiyat_takip_radari():
    borsa = ccxt.mexc()
    
    while True:
        try:
            conn = sqlite3.connect(db.DB_NAME)
            cursor = conn.cursor()
            cursor.execute("SELECT id, coin, yon, giris, tp1, tp2, tp3, tp4, sl, durum, asama FROM active_signals WHERE durum IN ('BEKLIYOR', 'ISLEMDE')")
            bekleyenler = cursor.fetchall()
            
            if bekleyenler:
                gorevler = []
                for sinyal in bekleyenler:
                    sembol = sinyal[1].replace('USDT', '') + '/USDT:USDT'
                    gorevler.append(borsa.fetch_ohlcv(sembol, '1m', limit=2))
                
                # Işık Hızı: Tüm coinleri aynı milisaniyede sorgula
                mum_sonuclari = await asyncio.gather(*gorevler, return_exceptions=True)
                
                for i, sinyal in enumerate(bekleyenler):
                    s_id, coin, yon, giris, tp1, tp2, tp3, tp4, sl, durum, asama = sinyal
                    mum_verisi = mum_sonuclari[i]
                    
                    if isinstance(mum_verisi, Exception) or not mum_verisi: continue 
                        
                    son_mum = mum_verisi[-1]
                    fiyat_high, fiyat_low = son_mum[2], son_mum[3]
                    yeni_durum, yeni_asama, bildirim = None, None, None
                    
                    if durum == 'BEKLIYOR':
                        if (yon == 'LONG' and fiyat_low <= giris) or (yon == 'SHORT' and fiyat_high >= giris):
                            yeni_durum, yeni_asama = 'ISLEMDE', 1
                            bildirim = f"🟢 **İŞLEME GİRİLDİ**\n#{coin} {yon} | {giris} 🚀"
                    
                    elif durum == 'ISLEMDE':
                        if (yon == 'LONG' and fiyat_low <= sl) or (yon == 'SHORT' and fiyat_high >= sl):
                            yeni_durum = 'STOP_OLDU'
                            bildirim = f"🛡 **STOP PATLADI** | #{coin} - Kasa korundu."
                        else:
                            if asama < 2 and ((yon == 'LONG' and fiyat_high >= tp1) or (yon == 'SHORT' and fiyat_low <= tp1)):
                                yeni_asama = 2
                                bildirim = f"🎯 **TP1 VURULDU!** | #{coin}"
                            elif asama < 3 and ((yon == 'LONG' and fiyat_high >= tp2) or (yon == 'SHORT' and fiyat_low <= tp2)):
                                yeni_asama = 3
                                bildirim = f"🎯🎯 **TP2 VURULDU!** | #{coin}"
                            elif asama < 4 and ((yon == 'LONG' and fiyat_high >= tp3) or (yon == 'SHORT' and fiyat_low <= tp3)):
                                yeni_asama = 4
                                bildirim = f"🎯🎯🎯 **TP3 VURULDU!** | #{coin}"
                            elif asama < 5 and ((yon == 'LONG' and fiyat_high >= tp4) or (yon == 'SHORT' and fiyat_low <= tp4)):
                                yeni_asama, yeni_durum = 5, 'FULL_TP'
                                bildirim = f"👑 **FULL TP (TÜM HEDEFLER)** 👑\n#{coin} operasyonu tamamlandı!"

                    if yeni_durum or yeni_asama:
                        cursor.execute("UPDATE active_signals SET durum = ?, asama = ? WHERE id = ?", (yeni_durum or durum, yeni_asama or asama, s_id))
                        conn.commit()
                        if bildirim: await client.send_message(VIP_KANAL_ID, bildirim)
            conn.close()
        except Exception as e:
            print(f"Radar: {e}")
            
        await asyncio.sleep(1) # V8 MOTORU - SADECE 1 SANİYE NEFES ALIR

async def main():
    print("KSVİX Motorları Ateşleniyor...")
    db.init_db()
    await client.start(bot_token=config.BOT_TOKEN)
    print("🤖 KSVİX VIP Telegram'a Sızdı.")
    client.loop.create_task(fiyat_takip_radari())
    print("🦅 V8 Radarı Aktif. Piyasa taranıyor...")
    await client.run_until_disconnected()

if __name__ == '__main__':
    loop.run_until_complete(main())
