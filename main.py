import asyncio
import sqlite3
import time
import datetime
import ccxt.async_support as ccxt
from telethon import TelegramClient, events

import config
import database as db
from parser import parse_signal
from trader import islem_ac, bekleyen_emri_iptal_et, pozisyon_guncelle

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
            await event.reply(
                "✅ **Kasaya Kilitlendi! KSVİX Emrinde.**\n\n"
                "👑 **%s KONTROL PANELİ** 👑\n"
                "Aşağıdaki komutlarla kasanı bir Balina gibi yönet:\n\n"
                "⚙️ **Risk:** `/ayar PERCENT 5 8` (Kasanın %%5'i, Max 8 işlem)\n"
                "🎯 **Kâr:** `/hedef 25 25 25 25` (TP1,2,3,4'te satış %%)\n"
                "🛡️ **Stop:** `/stop BREAKEVEN` (TP1'de risksiz), `/stop MOVING` (İz süren) veya `/stop NONE`\n\n"
                "Sistemi durdurmak için: `/durdur`\nDevam etmek için: `/devam`"
            )
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

    elif mesaj.startswith('/hedef'):
        try:
            _, t1, t2, t3, t4 = mesaj.split()
            if sum(map(float, [t1, t2, t3, t4])) > 100:
                await event.reply("❌ Toplam %%100'ü geçemez Kralım!")
                return
            db.update_tp_ratios(gonderen_id, f"{t1},{t2},{t3},{t4}")
            await event.reply(f"🎯 Kâr Oranları Ayarlandı: TP1:%%{t1} | TP2:%%{t2} | TP3:%%{t3} | TP4:%%{t4}")
        except:
            await event.reply("❌ Örnek: `/hedef 25 25 25 25` veya `/hedef 50 30 20 0`")

    elif mesaj.startswith('/stop'):
        try:
            _, mode = mesaj.split()
            if mode.upper() not in ['BREAKEVEN', 'MOVING', 'NONE']: raise ValueError
            db.update_stop_mode(gonderen_id, mode.upper())
            await event.reply(f"🛡️ Stop Kalkanı Güncellendi: **{mode.upper()}**")
        except:
            await event.reply("❌ Örnek: `/stop BREAKEVEN` veya `/stop MOVING` veya `/stop NONE`")

    elif mesaj.startswith('/durdur'):
        db.toggle_user_active(gonderen_id, 0)
        await event.reply("🛑 Bot uyku moduna alındı!")

    elif mesaj.startswith('/devam'):
        db.toggle_user_active(gonderen_id, 1)
        await event.reply("✅ Kalkanlar indirildi, silahlar aktif! 🦅")

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
    basarili = 0
    
    # ANLIK KULLANICIYA ÖZEL DM RAPORLAMA SİSTEMİ
    for uye, sonuc in zip(aktif_uyeler, sonuclar):
        telegram_id = uye['telegram_id']
        if isinstance(sonuc, Exception):
            mesaj_metni = f"❌ **#{sinyal['coin']} İşleme Girilemedi!**\nSistem Hatası: `{str(sonuc)}`"
        elif sonuc.get('durum') == 'BASARILI':
            basarili += 1
            db.update_daily_stat(telegram_id, 'open', value=1) # İstatistiğe ekle
            mesaj_metni = f"✅ **#{sinyal['coin']} Sinyali Alındı!**\nBorsaya limit emir dizildi. Pusudayız, fiyatın gelmesi bekleniyor. 🦅"
        else:
            hata = sonuc.get('hata_mesaji', 'Bilinmeyen Hata')
            mesaj_metni = f"⚠️ **#{sinyal['coin']} İşleme Girilemedi!**\nSebep: {hata}"
            
        try: await client.send_message(telegram_id, mesaj_metni)
        except Exception as e: print(f"DM Hatası: {e}")

    print(f"✅ Operasyon: {len(aktif_uyeler)} üyeden {basarili} tanesine iletildi.")

async def fiyat_takip_radari():
    borsa = ccxt.mexc()
    while True:
        try:
            conn = sqlite3.connect(db.DB_NAME)
            cursor = conn.cursor()
            cursor.execute("SELECT id, coin, yon, giris, tp1, tp2, tp3, tp4, sl, durum, asama, eklenme_zamani FROM active_signals WHERE durum IN ('BEKLIYOR', 'ISLEMDE')")
            bekleyenler = cursor.fetchall()
            
            if bekleyenler:
                gorevler = []
                for sinyal in bekleyenler:
                    sembol = sinyal[1].replace('USDT', '') + '/USDT:USDT'
                    gorevler.append(borsa.fetch_ohlcv(sembol, '1m', limit=2))
                
                mum_sonuclari = await asyncio.gather(*gorevler, return_exceptions=True)
                
                for i, sinyal in enumerate(bekleyenler):
                    s_id, coin, yon, giris, tp1, tp2, tp3, tp4, sl, durum, asama, eklenme_zamani = sinyal
                    mum_verisi = mum_sonuclari[i]
                    
                    if isinstance(mum_verisi, Exception) or not mum_verisi: continue 
                        
                    son_mum = mum_verisi[-1]
                    fiyat_high, fiyat_low = son_mum[2], son_mum[3]
                    yeni_durum, yeni_asama, bildirim = None, None, None
                    
                    aktif_uyeler = db.get_all_active_users()
                    
                    if durum == 'BEKLIYOR':
                        gecen_sure = time.time() - (eklenme_zamani or time.time())
                        if gecen_sure > (8 * 3600):
                            yeni_durum = 'ZAMAN_ASIMI'
                            bildirim = f"⏳ **ZAMAN AŞIMI (8 SAAT)** ⏳\n#{coin} operasyonu iptal edildi.\nBorsadaki bekleyen emirler geri çekiliyor."
                            for uye in aktif_uyeler:
                                client.loop.create_task(bekleyen_emri_iptal_et(uye['mexc_api_key'], uye['mexc_api_secret'], coin))
                        elif (yon == 'LONG' and fiyat_low <= giris) or (yon == 'SHORT' and fiyat_high >= giris):
                            yeni_durum, yeni_asama = 'ISLEMDE', 1
                            bildirim = f"🟢 **İŞLEME GİRİLDİ**\n#{coin} {yon} | {giris} 🚀"
                    
                    elif durum == 'ISLEMDE':
                        # 1. KULLANICIYA ÖZEL GİRİŞTEN STOP (BREAK-EVEN / MOVING PATLAMASI) KONTROLÜ
                        if asama == 2 and ((yon == 'LONG' and fiyat_low <= giris) or (yon == 'SHORT' and fiyat_high >= giris)):
                            for uye in aktif_uyeler:
                                if uye['stop_mode'] in ['BREAKEVEN', 'MOVING']:
                                    db.update_daily_stat(uye['telegram_id'], 'stop', value=1, profit=0.0)
                                    dm_msg = f"🛡️ **#{coin} İşlemi Giriş Fiyatından Kapatıldı (Break-Even)!**\nTP1 alındıktan sonra fiyat giriş seviyene geri döndü. Sıfır riskle, kâr cebimizde operasyondan ayrıldık! 💸"
                                    try: await client.send_message(uye['telegram_id'], dm_msg)
                                    except: pass
                        
                        # 2. KÜRESEL ORİJİNAL STOP LOSS KONTROLÜ
                        if (yon == 'LONG' and fiyat_low <= sl) or (yon == 'SHORT' and fiyat_high >= sl):
                            yeni_durum = 'STOP_OLDU'
                            bildirim = f"🛡 **STOP PATLADI** | #{coin} - Kasa korundu."
                            
                            # Orijinal stop olan kullanıcıların istatistiğini negatif güncelle
                            for uye in aktif_uyeler:
                                oranlar = [float(x) for x in uye['tp_ratios'].split(',')]
                                kalan_oran = 100.0
                                if asama == 2: kalan_oran = 100.0 - oranlar[0]
                                elif asama == 3: kalan_oran = 100.0 - sum(oranlar[:2])
                                elif asama == 4: kalan_oran = 100.0 - sum(oranlar[:3])
                                
                                zarar_yuzdesi = (abs(sl - giris) / giris) * 20 * (kalan_oran / 100.0) # Kaldıraç default 20x baz alındı
                                zarar_degeri = uye['trade_amount'] * zarar_yuzdesi if uye['trade_mode'] == 'FIXED' else zarar_yuzdesi
                                db.update_daily_stat(uye['telegram_id'], 'stop', value=1, profit=-zarar_degeri)
                                
                                dm_msg = f"🚨 **#{coin} Orijinal Stop Loss Noktasına Ulaştı.**\nPozisyon kalan kısmı ile zararla kapatıldı, cüzdan koruma altına alındı. 🛡️"
                                try: await client.send_message(uye['telegram_id'], dm_msg)
                                except: pass
                        else:
                            # KADEMELİ HEDEF (TP) KONTROLLERİ
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
                        
                        # KISMI KAR VE STOP YÖNETİM TETİĞİ + KULLANICI ÖZEL BİLGİLENDİRME DM'LERİ
                        if yeni_asama and yeni_asama >= 2:
                            fiyatlar = {'giris': giris, 'tp1': tp1, 'tp2': tp2, 'tp3': tp3}
                            for uye in aktif_uyeler:
                                client.loop.create_task(pozisyon_guncelle(
                                    uye['mexc_api_key'], uye['mexc_api_secret'], 
                                    coin, yon, yeni_asama, uye['tp_ratios'], uye['stop_mode'], fiyatlar
                                ))
                                
                                # Anlık Kâr Hesaplama Modülü
                                oranlar = [float(x) for x in uye['tp_ratios'].split(',')]
                                mevcut_satilan_oran = oranlar[yeni_asama - 2]
                                hedef_fiyat = tp1 if yeni_asama == 2 else (tp2 if yeni_asama == 3 else (tp3 if yeni_asama == 4 else tp4))
                                
                                kar_yuzdesi = (abs(hedef_fiyat - giris) / giris) * 20 * (mevcut_satilan_oran / 100.0)
                                kar_degeri = uye['trade_amount'] * kar_yuzdesi if uye['trade_mode'] == 'FIXED' else kar_yuzdesi
                                db.update_daily_stat(uye['telegram_id'], 'tp', value=1, profit=kar_degeri)
                                
                                # Kişiye Özel VIP Bildirim Mesajı
                                dm_msg = f"🎯 **#{coin} OPERASYONUNDA TP{yeni_asama - 1} HEDEFİ VURULDU!**\n"
                                if yeni_asama == 2 and uye['stop_mode'] in ['BREAKEVEN', 'MOVING']:
                                    dm_msg += f"🛡️ Belirttiğin üzere pozisyonun %%{mevcut_satilan_oran} kısmı kârla kapatıldı ve Stop seviyen **GİRİŞ FİYATINA** çekilerek işlem tamamen risksiz hale getirildi! 🚀"
                                elif yeni_asama > 2 and uye['stop_mode'] == 'MOVING':
                                    eski_hedef = "Giriş" if yeni_asama == 3 else f"TP{yeni_asama - 2}"
                                    yeni_hedef = f"TP{yeni_asama - 1}"
                                    dm_msg += f"📈 Harika! Pozisyonun %%{mevcut_satilan_oran} kısmı daha kârla kapatıldı. İz süren stop kalkanın {eski_hedef} seviyesinden **{yeni_hedef}** seviyesine taşındı! 🔥"
                                else:
                                    dm_msg += f"💸 Belirttiğin üzere pozisyonun %%{mevcut_satilan_oran} kısmı kârla kapatıldı. Kasa büyümeye devam ediyor! 🦁"
                                    
                                try: await client.send_message(uye['telegram_id'], dm_msg)
                                except: pass
            conn.close()
        except Exception as e:
            print(f"Radar: {e}")
            
        await asyncio.sleep(1)

# GECE YARISI KRALIN GÜNLÜK BİLANÇO MOTORU
async def gunluk_pnl_raporlayici():
    while True:
        try:
            su_an = datetime.datetime.now()
            # Her gece tam 23:59'da raporları fırlatır
            if su_an.hour == 23 and su_an.minute == 59:
                aktif_uyeler = db.get_all_active_users()
                for uye in aktif_uyeler:
                    stats = db.get_daily_stats(uye['telegram_id'])
                    acilan = stats['acilan_islem'] if stats else 0
                    tps = stats['tp_adet'] if stats else 0
                    stops = stats['stop_adet'] if stats else 0
                    kar = stats['kar_usdt'] if stats else 0.0
                    
                    if uye['trade_mode'] == 'FIXED':
                        kar_metni = f"+{kar:.2f} USDT"
                    else:
                        kar_metni = f"+%%{kar*100:.2f} Kasa Büyümesi"
                        
                    pnl_msg = (
                        f"👑 **KRALIN SİNYALLERİ - GÜNLÜK BİLANÇO** 👑\n"
                        f"📅 **Tarih:** {su_an.strftime('%%d %%B %%Y')}\n\n"
                        f"Kralım, harika bir günü daha geride bıraktık! İşte senin özel hesabının bugünkü net özeti:\n\n"
                        f"🚀 **Açılan Toplam Operasyon:** {acilan} Yeni Emir\n"
                        f"🎯 **Başarıyla Vurulan Hedef (TP):** {tps} Kez\n"
                        f"🛡️ **Kalkan Savaşları (STOP/BE):** {stops} Kez\n\n"
                        f"💰 **Net Kasa Durumu:** `{kar_metni}`\n\n"
                        f"*Unutma Kralım, disiplin parayı çeker. Yarın yeni avlar için KSVİX nöbette olacak!* 🦁📈"
                    )
                    try: await client.send_message(uye['telegram_id'], pnl_msg)
                    except: pass
                await asyncio.sleep(70) # 23:59 dakikasından çıkmayı garantile
        except Exception as e:
            print(f"PNL Raporlayıcı Hata: {e}")
        await asyncio.sleep(30)

async def main():
    print("KSVİX Motorları Ateşleniyor...")
    db.init_db()
    await client.start(bot_token=config.BOT_TOKEN)
    print("🤖 KSVİX VIP Telegram'a Sızdı.")
    client.loop.create_task(fiyat_takip_radari())
    client.loop.create_task(gunluk_pnl_raporlayici()) # Gece yarısı raporlayıcı aktif
    print("🦅 V8 Radarları ve Muhasebe Motoru Aktif. Piyasa taranıyor...")
    await client.run_until_disconnected()

if __name__ == '__main__':
    loop.run_until_complete(main())
