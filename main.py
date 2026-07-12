import asyncio
import sqlite3
import time
import datetime
import ccxt.pro as ccxt 
from telethon import TelegramClient, events

import config
import database as db
from parser import parse_signal
from trader import islem_ac, bekleyen_emri_iptal_et, pozisyon_guncelle

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

client = TelegramClient('kralin_makinesi_session', config.API_ID, config.API_HASH)
VIP_KANAL_ID = int(config.VIP_CHANNEL)

def hayalet_enjektor(borsa, sembol, coin_adi):
    if borsa.markets is not None and sembol not in borsa.markets:
        base = coin_adi.replace('USDT', '')
        borsa.markets[sembol] = {
            'id': f"{base}_USDT",
            'symbol': sembol,
            'base': base,
            'quote': 'USDT',
            'settle': 'USDT',
            'type': 'swap',
            'spot': False,
            'swap': True,
            'contract': True,
            'linear': True,
            'contractSize': 1,
            'limits': {'amount': {'min': 0}, 'cost': {'min': 0}},
            'precision': {'amount': 1.0, 'price': 0.0001}
        }

@client.on(events.NewMessage(func=lambda e: e.is_private))
async def dm_handler(event):
    mesaj = event.message.message
    gonderen_id = event.sender_id
    
    if mesaj == '/start':
        await event.reply("👑 **KSVİX Motorları Aktif.**\n`/kayit API_KEY API_SECRET`")
    elif mesaj.startswith('/kayit'):
        try:
            _, api_key, api_secret = mesaj.split()
            db.add_user(gonderen_id, api_key, api_secret)
            await event.reply("✅ **Kasaya Kilitlendi! KSVİX Emrinde.**")
        except: await event.reply("❌ Örnek: `/kayit API_KEY API_SECRET`")
    elif mesaj.startswith('/ayar'):
        try:
            _, mod, miktar, max_islem = mesaj.split()
            db.update_user_settings(gonderen_id, mod.upper(), float(miktar), int(max_islem))
            await event.reply(f"⚙️ Ayarlandı! Mod: {mod.upper()}, Miktar: {miktar}, Max İşlem: {max_islem}")
        except: await event.reply("❌ Örnek: `/ayar PERCENT 5 8`")
    elif mesaj.startswith('/hedef'):
        try:
            _, t1, t2, t3, t4 = mesaj.split()
            db.update_tp_ratios(gonderen_id, f"{t1},{t2},{t3},{t4}")
            await event.reply(f"🎯 Kâr Oranları Ayarlandı: TP1:%{t1} | TP2:%{t2} | TP3:%{t3} | TP4:%{t4}")
        except: await event.reply("❌ Örnek: `/hedef 25 25 25 25`")
    elif mesaj.startswith('/stop'):
        try:
            _, mode = mesaj.split()
            db.update_stop_mode(gonderen_id, mode.upper())
            await event.reply(f"🛡️ Stop Kalkanı: **{mode.upper()}**")
        except: await event.reply("❌ Örnek: `/stop MOVING`")
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
        
    signal_id = db.sinyal_kaydet(
        sinyal['coin'], sinyal['yon'], sinyal['giris'], 
        sinyal['tp1'], sinyal['tp2'], sinyal['tp3'], sinyal['tp4'], sinyal['sl'], sinyal['kaldirac']
    )
    
    aktif_uyeler = db.get_all_active_users()
    if not aktif_uyeler: return
        
    gorevler = []
    for uye in aktif_uyeler:
        ayarlar = {'trade_mode': uye['trade_mode'], 'trade_amount': uye['trade_amount'], 'max_trades': uye['max_trades']}
        gorevler.append(islem_ac(uye['mexc_api_key'], uye['mexc_api_secret'], ayarlar, sinyal))
        
    sonuclar = await asyncio.gather(*gorevler, return_exceptions=True)
    
    for uye, sonuc in zip(aktif_uyeler, sonuclar):
        telegram_id = uye['telegram_id']
        if isinstance(sonuc, Exception): pass
        elif sonuc.get('durum') == 'BASARILI':
            db.sinyale_katilan_ekle(signal_id, telegram_id)
            db.update_daily_stat(telegram_id, 'open', value=1)
            try: await client.send_message(telegram_id, f"✅ **#{sinyal['coin']} Sinyali Alındı!**\nPusudayız. 🦅")
            except: pass

async def fiyat_takip_radari():
    borsa_ws = ccxt.mexc({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    try: await borsa_ws.load_markets()
    except: pass
    son_db_okuma = 0
    
    while True:
        try:
            su_an = time.time()
            if su_an - son_db_okuma >= 2:
                conn = db.get_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT id, coin, yon, giris, tp1, tp2, tp3, tp4, sl, durum, asama, eklenme_zamani, katilanlar, kaldirac FROM active_signals WHERE durum IN ('BEKLIYOR', 'ISLEMDE')")
                bekleyenler = cursor.fetchall()
                conn.close()
                son_db_okuma = su_an
            
            if not bekleyenler:
                await asyncio.sleep(2)
                continue

            sembol_map, semboller = {}, []
            for sinyal in bekleyenler:
                sembol = sinyal[1].replace('USDT', '') + '/USDT:USDT'
                hayalet_enjektor(borsa_ws, sembol, sinyal[1])
                semboller.append(sembol)
                sembol_map[sembol] = sinyal
            
            tickers = await asyncio.wait_for(borsa_ws.watch_tickers(semboller), timeout=2.0)
            aktif_uyeler = db.get_all_active_users()
            degisiklik_var = False
            conn = db.get_connection()
            cursor = conn.cursor()
            
            for sembol, ticker in tickers.items():
                if sembol not in sembol_map: continue
                
                # 🎯 ÇİFT ÇEKİRDEKLİ MİMARİ
                fiyat_last = float(ticker.get('last') or 0)
                if not fiyat_last: continue
                fiyat_mark = float(ticker.get('mark') or ticker.get('info', {}).get('markPrice', fiyat_last))
                
                sinyal = sembol_map[sembol]
                s_id, coin, yon, giris, tp1, tp2, tp3, tp4, sl, durum, asama, eklenme_zamani, katilanlar, kaldirac = sinyal
                katilanlar_listesi = [x for x in str(katilanlar).split(',') if x]
                yeni_durum, yeni_asama, bildirim = None, None, None

                if durum == 'BEKLIYOR':
                    # GİRİŞ: İğneyi Affetmez (Last Price)
                    if (yon == 'LONG' and fiyat_last <= giris) or (yon == 'SHORT' and fiyat_last >= giris):
                        yeni_durum, yeni_asama = 'ISLEMDE', 1
                        bildirim = f"🟢 **İŞLEME GİRİLDİ** | #{coin}\n⚡ **Yön:** {yon} | **Giriş:** {giris} 🚀"
                
                elif durum == 'ISLEMDE':
                    for uye in aktif_uyeler:
                        tid_str = str(uye['telegram_id'])
                        if tid_str in katilanlar_listesi:
                            kullanici_stop, stop_tipi = sl, "ORIJINAL"
                            if uye['stop_mode'] == 'BREAKEVEN' and asama >= 2: kullanici_stop, stop_tipi = giris, "BREAK_EVEN"
                            elif uye['stop_mode'] == 'MOVING':
                                if asama == 2: kullanici_stop, stop_tipi = giris, "BREAK_EVEN"
                                elif asama == 3: kullanici_stop, stop_tipi = tp1, "MOVING_TP1"
                                elif asama == 4: kullanici_stop, stop_tipi = tp2, "MOVING_TP2"
                                elif asama == 5: kullanici_stop, stop_tipi = tp3, "MOVING_TP3"

                            # KİŞİSEL STOP: Kalkan Devrede (Mark Price)
                            if (yon == 'LONG' and fiyat_mark <= kullanici_stop) or (yon == 'SHORT' and fiyat_mark >= kullanici_stop):
                                katilanlar_listesi.remove(tid_str)
                                cursor.execute("UPDATE active_signals SET katilanlar = ? WHERE id = ?", (",".join(katilanlar_listesi), s_id))
                                degisiklik_var = True
                                
                                # DM Mesajları (ROE Hesaplamalı)
                                roe = (abs(kullanici_stop - giris) / giris) * kaldirac * 100
                                if stop_tipi == "ORIJINAL": 
                                    db.update_daily_stat(uye['telegram_id'], 'stop', value=1, profit=-(uye['trade_amount']*(roe/100)))
                                    dm_msg = f"🚨 **#{coin} Stop Loss.**\n🩸 `-{roe:.2f}%` ({kaldirac}x ROE) 🛡️"
                                elif stop_tipi == "BREAK_EVEN":
                                    db.update_daily_stat(uye['telegram_id'], 'be', value=1, profit=0.0)
                                    dm_msg = f"🛡️ **#{coin} Break-Even!**\n⚖️ Sıfır riskle ayrıldık. 💸"
                                else:
                                    db.update_daily_stat(uye['telegram_id'], 'tp', value=1, profit=(uye['trade_amount']*(roe/100)))
                                    dm_msg = f"🛡️ **#{coin} İz Süren Stop!**\n📈 `+{roe:.2f}%` ({kaldirac}x ROE) kârla kapandı. 🔥"
                                try: await client.send_message(uye['telegram_id'], dm_msg)
                                except: pass

                    # GLOBAL STOP: Kalkan Devrede (Mark Price)
                    if (yon == 'LONG' and fiyat_mark <= sl) or (yon == 'SHORT' and fiyat_mark >= sl):
                        yeni_durum = 'STOP_OLDU'
                        roe = (abs(sl - giris) / giris) * kaldirac * 100
                        bildirim = f"🛡 **STOP PATLADI** | #{coin}\n🩸 **Zarar:** `-{roe:.2f}%` ({kaldirac}x ROE) ⚔️"
                    else:
                        # TP HEDEFLERİ: İğneyi Affetmez (Last Price)
                        if asama < 2 and ((yon == 'LONG' and fiyat_last >= tp1) or (yon == 'SHORT' and fiyat_last <= tp1)):
                            yeni_asama = 2
                            roe = (abs(tp1 - giris) / giris) * kaldirac * 100
                            bildirim = f"🎯 **TP1 VURULDU!** | #{coin}\n💸 **Kâr:** `+{roe:.2f}%` ({kaldirac}x ROE) 📈"
                        elif asama < 3 and ((yon == 'LONG' and fiyat_last >= tp2) or (yon == 'SHORT' and fiyat_last <= tp2)):
                            yeni_asama = 3
                            roe = (abs(tp2 - giris) / giris) * kaldirac * 100
                            bildirim = f"🎯🎯 **TP2 VURULDU!** | #{coin}\n🔥 **Kâr:** `+{roe:.2f}%` ({kaldirac}x ROE) 📈"
                        elif asama < 4 and ((yon == 'LONG' and fiyat_last >= tp3) or (yon == 'SHORT' and fiyat_last <= tp3)):
                            yeni_asama = 4
                            roe = (abs(tp3 - giris) / giris) * kaldirac * 100
                            bildirim = f"🎯🎯🎯 **TP3 VURULDU!** | #{coin}\n🚀 **Kâr:** `+{roe:.2f}%` ({kaldirac}x ROE) 📈"
                        elif asama < 5 and ((yon == 'LONG' and fiyat_last >= tp4) or (yon == 'SHORT' and fiyat_last <= tp4)):
                            yeni_asama, yeni_durum = 5, 'FULL_TP'
                            roe = (abs(tp4 - giris) / giris) * kaldirac * 100
                            bildirim = f"👑 **FULL TP** | #{coin}\n🤑 **Maksimum Kâr:** `+{roe:.2f}%` ({kaldirac}x ROE) 🥂"

                if yeni_durum or yeni_asama:
                    cursor.execute("UPDATE active_signals SET durum = ?, asama = ? WHERE id = ?", (yeni_durum or durum, yeni_asama or asama, s_id))
                    degisiklik_var = True
                    if bildirim: await client.send_message(VIP_KANAL_ID, bildirim)
            if degisiklik_var: conn.commit()
            conn.close()
        except: await asyncio.sleep(2)

async def gunluk_pnl_raporlayici():
    while True:
        try:
            su_an = datetime.datetime.now()
            if su_an.hour == 20 and su_an.minute == 59:
                aktif_uyeler = db.get_all_active_users()
                for uye in aktif_uyeler:
                    stats = db.get_daily_stats(uye['telegram_id'])
                    acilan = stats['acilan_islem'] if stats else 0
                    tps = stats['tp_adet'] if stats else 0
                    stops = stats['stop_adet'] if stats else 0
                    bes = stats['be_adet'] if stats else 0
                    kar = stats['kar_usdt'] if stats else 0.0
                    kar_metni = f"{kar:+.2f} USDT" if uye['trade_mode'] == 'FIXED' else f"{kar*100:+.2f}% Net Kasa Büyümesi"
                        
                    pnl_msg = (
                        f"👑 **KRALIN SİNYALLERİ - GÜNLÜK BİLANÇO** 👑\n"
                        f"📅 **Tarih:** {su_an.strftime('%d %B %Y')}\n\n"
                        f"🚀 **Açılan Toplam Operasyon:** {acilan}\n"
                        f"🎯 **Başarılı TP:** {tps}\n"
                        f"🛡️ **Orijinal Stop (Zarar):** {stops}\n"
                        f"⚖️ **Break-Even (Zararsız):** {bes}\n\n"
                        f"💰 **Net Kasa Durumu:** `{kar_metni}`\n"
                    )
                    try: await client.send_message(uye['telegram_id'], pnl_msg)
                    except: pass
                await asyncio.sleep(70) 
        except Exception:
            await asyncio.sleep(30)

async def main():
    print("KSVİX Motorları Ateşleniyor...")
    db.init_db()
    await client.start(bot_token=config.BOT_TOKEN)
    print("🤖 KSVİX VIP Telegram'a Sızdı.")
    client.loop.create_task(fiyat_takip_radari())
    client.loop.create_task(gunluk_pnl_raporlayici())
    print("🦅 V8 Radarları (WebSocket) ve Muhasebe Motoru Aktif...")
    await client.run_until_disconnected()

if __name__ == '__main__':
    loop.run_until_complete(main())
