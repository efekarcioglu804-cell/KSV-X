import asyncio
import sqlite3
import time
import datetime
import math
import os
import ccxt.pro as ccxt 
from telethon import TelegramClient, events

import config
import database as db
from parser import parse_signal
from trader import islem_ac, bekleyen_emri_iptal_et, pozisyon_guncelle, acil_kapat
from visuals import create_pnl_image

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
            'precision': {'amount': 0.0001, 'price': 0.00000001}
        }

# 🧠 YAPAY ZEKA İÇİN PİYASA FOTOĞRAFÇISI (RSI, MACD, HACİM HESAPLAYICI)
def hesapla_ema(fiyatlar, periyot):
    if not fiyatlar: return 0
    k = 2 / (periyot + 1)
    ema_serisi = [fiyatlar[0]]
    for fiyat in fiyatlar[1:]:
        ema_serisi.append(fiyat * k + ema_serisi[-1] * (1 - k))
    return ema_serisi[-1]

async def piyasa_fotografi_cek(borsa, sembol):
    try:
        # Son 50 adet 15 dakikalık mumu çek (Geçmiş 12 saatlik trendi okur)
        mumlar = await borsa.fetch_ohlcv(sembol, '15m', limit=50)
        if not mumlar or len(mumlar) < 30: return 0.0, 0.0, 0.0
        
        kapanislar = [mum[4] for mum in mumlar]
        hacim = mumlar[-1][5] # Son mumun hacmi (Büyük balina tespiti için)
        
        # Matematiksel RSI Hesaplama (14 Periyot)
        farklar = [kapanislar[i] - kapanislar[i-1] for i in range(1, len(kapanislar))]
        kazanclar = [f if f > 0 else 0 for f in farklar[-14:]]
        kayiplar = [-f if f < 0 else 0 for f in farklar[-14:]]
        ort_kazanc = sum(kazanclar) / 14
        ort_kayip = sum(kayiplar) / 14
        rs = ort_kazanc / ort_kayip if ort_kayip > 0 else 0
        rsi = 100 - (100 / (1 + rs)) if ort_kayip > 0 else 100
        
        # Matematiksel MACD Hesaplama
        ema_12 = hesapla_ema(kapanislar, 12)
        ema_26 = hesapla_ema(kapanislar, 26)
        macd = ema_12 - ema_26
        
        return round(rsi, 2), round(macd, 4), round(hacim, 2)
    except Exception as e:
        print(f"Piyasa Fotoğrafı Çekilemedi: {e}")
        return 0.0, 0.0, 0.0

@client.on(events.NewMessage(incoming=True))
async def genel_handler(event):
    mesaj = event.raw_text.strip()
    
    if event.is_private:
        gonderen_id = event.sender_id
        if mesaj.startswith('/start'):
            start_msg = (
                "👑 **KSVİX KOMUTA MERKEZİNE HOŞ GELDİNİZ!** 👑\n\n"
                "Wall Street standartlarında, duygusuz ve keskin nişancı ticaret botunuz aktif edildi.\n"
                "Bütün piyasa radarları sizin emrinizi bekliyor.\n\n"
                "🔒 **Kayıt Komutu:**\n`/kayit API_KEY API_SECRET`"
            )
            await event.reply(start_msg)
            
        elif mesaj.startswith('/kayit'):
            try:
                _, api_key, api_secret = mesaj.split()
                db.add_user(gonderen_id, api_key, api_secret)
                await event.reply("✅ **Kasa Başarıyla Kilitlendi! KSVİX Otomasyonu Sağlandı.** 🦅\n\nAyarlar için: `/ayar PERCENT 5 8`, `/hedef 50 25 15 10`, `/stop MOVING`")
            except: 
                await event.reply("❌ **Hatalı format!** Örnek kullanım: `/kayit API_KEY API_SECRET`")
                
        elif mesaj.startswith('/ayar'):
            try:
                _, mod, miktar, max_islem = mesaj.split()
                db.update_user_settings(gonderen_id, mod.upper(), float(miktar), int(max_islem))
                await event.reply(f"⚙️ **Ayarlar Güncellendi!**\nMod: `{mod.upper()}` | Miktar: `{miktar}` | Maksimum Açık İşlem: `{max_islem}`")
            except: await event.reply("❌ **Hatalı format!** Örnek: `/ayar PERCENT 5 8`")
            
        elif mesaj.startswith('/hedef'):
            try:
                _, t1, t2, t3, t4 = mesaj.split()
                db.update_tp_ratios(gonderen_id, f"{t1},{t2},{t3},{t4}")
                await event.reply(f"🎯 **Kâr Oranları Ayarlandı!**\nTP1: `%{t1}` | TP2: `%{t2}` | TP3: `%{t3}` | TP4: `%{t4}`")
            except: await event.reply("❌ **Hatalı format!** Örnek: `/hedef 50 25 15 10`")
            
        elif mesaj.startswith('/stop'):
            try:
                _, mode = mesaj.split()
                db.update_stop_mode(gonderen_id, mode.upper())
                await event.reply(f"🛡️ **Stop Kalkanı Aktif:** `{mode.upper()}`")
            except: await event.reply("❌ **Hatalı format!** Örnek: `/stop MOVING`")
            
        elif mesaj.startswith('/durdur'):
            db.toggle_user_active(gonderen_id, 0)
            await event.reply("🛑 **Sistem Uyku Modunda!** Yeni sinyallere giriş yapılmayacak.")
            
        elif mesaj.startswith('/devam'):
            db.toggle_user_active(gonderen_id, 1)
            await event.reply("✅ **Sistem Aktif!** Silahlar devrede, piyasa taranıyor. 🦅")
            
        # 👑 KRALIN YENİ KOMUTU: YAPAY ZEKA SAYACI
        elif mesaj.startswith('/sayac'):
            conn = sqlite3.connect(db.DB_NAME, timeout=30)
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM active_signals")
                toplam_sinyal = cursor.fetchone()[0]
            except Exception as e:
                toplam_sinyal = 0
            finally:
                conn.close()
            
            kalan = 800 - toplam_sinyal if toplam_sinyal < 800 else 0
            
            sayac_msg = (
                f"🧠 **KSVİX Yapay Zeka (AI) Veri Havuzu:**\n\n"
                f"🗃️ Toplanan Eğitim Verisi: `{toplam_sinyal}` İşlem\n"
                f"🎯 800 Barajına Kalan: `{kalan}` İşlem\n\n"
                f"{'🔥 **Kritik eşiğe ulaşıldı! Modeli eğitmeye başlayabiliriz Kralım!**' if toplam_sinyal >= 800 else '🦅 İstihbarat toplanmaya devam ediyor...'}"
            )
            await event.reply(sayac_msg)
            
    else:
        if event.chat_id == VIP_KANAL_ID:
            print(f"🚀 [VIP KANAL] Sinyal yakalandı: {mesaj}")
            sinyal = parse_signal(mesaj)
            if not sinyal: return

            borsa_tmp = ccxt.mexc({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
            rsi_degeri, macd_degeri, hacim_degeri = 0.0, 0.0, 0.0
            try:
                sembol_tmp = sinyal['coin'].replace('USDT', '') + '/USDT:USDT'
                await borsa_tmp.load_markets()
                hayalet_enjektor(borsa_tmp, sembol_tmp, sinyal['coin'])
                
                # 🧠 Sinyal gelir gelmez fotoğraf çek!
                rsi_degeri, macd_degeri, hacim_degeri = await piyasa_fotografi_cek(borsa_tmp, sembol_tmp)
                
                ticker = await borsa_tmp.fetch_ticker(sembol_tmp)
                fiyat_mexc = float(ticker['last'])
                giris_fiyati = float(sinyal['giris'])
                
                if fiyat_mexc > 0 and giris_fiyati > 0:
                    oran = giris_fiyati / fiyat_mexc
                    if oran > 5: 
                        carpan = 10 ** round(math.log10(oran))
                        sinyal['giris'] /= carpan
                        sinyal['tp1'] /= carpan
                        sinyal['tp2'] /= carpan
                        sinyal['tp3'] /= carpan
                        sinyal['tp4'] /= carpan
                        sinyal['sl'] /= carpan
                        print(f"🔧 Ölçek Küçültüldü! Çarpan: /{carpan}")
                    elif oran < 0.2: 
                        carpan = 10 ** round(math.log10(1/oran))
                        sinyal['giris'] *= carpan
                        sinyal['tp1'] *= carpan
                        sinyal['tp2'] *= carpan
                        sinyal['tp3'] *= carpan
                        sinyal['tp4'] *= carpan
                        sinyal['sl'] *= carpan
                        print(f"🔧 Ölçek Büyütüldü! Çarpan: x{carpan}")
            except Exception as e:
                print(f"Ölçekleyici hatası: {e}")
            finally:
                await borsa_tmp.close()
                
            # 🧠 Veritabanına Yapay Zeka için 3 yeni metrik de sessizce kaydediliyor
            signal_id = db.sinyal_kaydet(
                sinyal['coin'], sinyal['yon'], sinyal['giris'], 
                sinyal['tp1'], sinyal['tp2'], sinyal['tp3'], sinyal['tp4'], sinyal['sl'], 
                sinyal['kaldirac'], rsi_degeri, macd_degeri, hacim_degeri
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
                else:
                    hata_nedeni = sonuc.get('hata_mesaji', 'Bilinmiyor')
                    try: await client.send_message(telegram_id, f"⚠️ **#{sinyal['coin']} Pas Geçildi!**\n🛑 **Sebep:** `{hata_nedeni}`")
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
                conn = sqlite3.connect(db.DB_NAME, timeout=30)
                try:
                    cursor = conn.cursor()
                    cursor.execute("SELECT id, coin, yon, giris, tp1, tp2, tp3, tp4, sl, durum, asama, eklenme_zamani, katilanlar, kaldirac FROM active_signals WHERE durum IN ('BEKLIYOR', 'ISLEMDE')")
                    bekleyenler = cursor.fetchall()
                    son_db_okuma = su_an
                finally:
                    conn.close()
            
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
            
            db_guncellemeler = []
            istatistik_guncellemeler = []
            vip_mesajlar = []
            dm_mesajlar = []
            mexc_gorevleri = [] 
            
            for sembol, ticker in tickers.items():
                if sembol not in sembol_map: continue
                
                fiyat_last = float(ticker.get('last') or 0)
                if not fiyat_last: continue
                
                sinyal = sembol_map[sembol]
                s_id, coin, yon, giris, tp1, tp2, tp3, tp4, sl, durum, asama, eklenme_zamani, katilanlar, kaldirac = sinyal
                katilanlar_listesi = [x for x in str(katilanlar).split(',') if x]
                yeni_durum, yeni_asama, bildirim = None, None, None

                if durum == 'BEKLIYOR':
                    gecen_sure = su_an - (eklenme_zamani or su_an)
                    
                    if fiyat_last > 0 and giris > 0 and ((giris / fiyat_last > 5) or (fiyat_last / giris > 5)):
                        yeni_durum = 'IPTAL'
                        bildirim = f"⚠️ **ÖLÇEK UYUŞMAZLIĞI (Sistem Koruması)** ⚠️\n#{coin} işlemi iptal edildi!\nSinyal Fiyatı: `{giris}`\nMEXC Fiyatı: `{fiyat_last}`"
                        for uye in aktif_uyeler:
                            if str(uye['telegram_id']) in katilanlar_listesi:
                                mexc_gorevleri.append(bekleyen_emri_iptal_et(uye['mexc_api_key'], uye['mexc_api_secret'], coin))
                    
                    elif gecen_sure > (8 * 3600):
                        yeni_durum = 'ZAMAN_ASIMI'
                        bildirim = f"⏳ **ZAMAN AŞIMI (8 SAAT)** ⏳\n#{coin} operasyonu giriş bölgesine ulaşamadığı için iptal edildi."
                        for uye in aktif_uyeler:
                            if str(uye['telegram_id']) in katilanlar_listesi:
                                mexc_gorevleri.append(bekleyen_emri_iptal_et(uye['mexc_api_key'], uye['mexc_api_secret'], coin))
                    
                    # 👑 KRALIN YENİ KORUMASI: GİRİŞTEN ÖNCE TP VURURSA İPTAL ET (Falling Knife Koruması)
                    elif tp1 > 0 and ((yon == 'LONG' and fiyat_last >= tp1) or (yon == 'SHORT' and fiyat_last <= tp1)):
                        yeni_durum = 'IPTAL'
                        bildirim = f"⚠️ **#{coin} İptal Edildi!**\n🛑 **Sebep:** KSVİX işleme giremeden coin hedefine (TP) ulaştı (Hit Profit Before Entry). Tuzaktan kurtulduk! 🦅"
                        for uye in aktif_uyeler:
                            if str(uye['telegram_id']) in katilanlar_listesi:
                                mexc_gorevleri.append(bekleyen_emri_iptal_et(uye['mexc_api_key'], uye['mexc_api_secret'], coin))

                    elif (yon == 'LONG' and fiyat_last <= giris) or (yon == 'SHORT' and fiyat_last >= giris):
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

                            if (yon == 'LONG' and fiyat_last <= kullanici_stop) or (yon == 'SHORT' and fiyat_last >= kullanici_stop):
                                katilanlar_listesi.remove(tid_str)
                                db_guncellemeler.append(("UPDATE active_signals SET katilanlar = ? WHERE id = ?", (",".join(katilanlar_listesi), s_id)))
                                
                                mexc_gorevleri.append(acil_kapat(uye['mexc_api_key'], uye['mexc_api_secret'], coin, yon))
                                
                                roe = (abs(kullanici_stop - giris) / giris) * kaldirac * 100
                                if stop_tipi == "ORIJINAL": 
                                    istatistik_guncellemeler.append((uye['telegram_id'], 'stop', 1, -(uye['trade_amount']*(roe/100))))
                                    dm_msg = f"🚨 **#{coin} Stop Loss.**\n🩸 `-{roe:.2f}%` ({kaldirac}x ROE) 🛡️"
                                elif stop_tipi == "BREAK_EVEN":
                                    istatistik_guncellemeler.append((uye['telegram_id'], 'be', 1, 0.0))
                                    dm_msg = f"🛡️ **#{coin} Break-Even!**\n⚖️ Sıfır riskle ayrıldık. 💸"
                                else:
                                    istatistik_guncellemeler.append((uye['telegram_id'], 'tp', 1, (uye['trade_amount']*(roe/100))))
                                    dm_msg = f"🛡️ **#{coin} İz Süren Stop!**\n📈 `+{roe:.2f}%` ({kaldirac}x ROE) kârla kapandı. 🔥"
                                dm_mesajlar.append((uye['telegram_id'], dm_msg))

                    if (yon == 'LONG' and fiyat_last <= sl) or (yon == 'SHORT' and fiyat_last >= sl):
                        yeni_durum = 'STOP_OLDU'
                        roe = (abs(sl - giris) / giris) * kaldirac * 100
                        bildirim = f"🛡 **STOP PATLADI** | #{coin}\n🩸 **Zarar:** `-{roe:.2f}%` ({kaldirac}x ROE) ⚔️"
                    else:
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
                            
                            for uye in aktif_uyeler:
                                if str(uye['telegram_id']) in katilanlar_listesi:
                                    mexc_gorevleri.append(acil_kapat(uye['mexc_api_key'], uye['mexc_api_secret'], coin, yon))

                if yeni_durum or yeni_asama:
                    db_guncellemeler.append(("UPDATE active_signals SET durum = ?, asama = ? WHERE id = ?", (yeni_durum or durum, yeni_asama or asama, s_id)))
                    if bildirim: vip_mesajlar.append(bildirim)

                    if yeni_durum == 'ISLEMDE' and durum == 'BEKLIYOR':
                        for uye in aktif_uyeler:
                            if str(uye['telegram_id']) in katilanlar_listesi:
                                dm_mesajlar.append((uye['telegram_id'], f"🟢 **#{coin} İşleme Girildi!**\n⚡ **Yön:** {yon} | 🎯 **Giriş:** {giris}\n🦅 KSVİX pusudan çıktı, operasyon başladı!"))

                    if yeni_asama and yeni_asama > asama and yeni_asama >= 2:
                        tp_fiyatlar = {1: tp1, 2: tp2, 3: tp3, 4: tp4}
                        vurulan_tp = yeni_asama - 1
                        hedef_fiyat = tp_fiyatlar.get(vurulan_tp, tp1)
                        tp_roe = (abs(hedef_fiyat - giris) / giris) * kaldirac * 100
                        
                        for uye in aktif_uyeler:
                            if str(uye['telegram_id']) in katilanlar_listesi:
                                if yeni_asama == 5:
                                    dm_mesajlar.append((uye['telegram_id'], f"👑 **#{coin} FULL TP Vuruldu!**\n🤑 Maksimum kâr (`+{tp_roe:.2f}%` {kaldirac}x ROE) cebinde! İşlem kapandı. 🥂"))
                                else:
                                    dm_mesajlar.append((uye['telegram_id'], f"🎯 **#{coin} TP{vurulan_tp} Vuruldu!**\n💸 Kısmi kâr satıldı (`+{tp_roe:.2f}%` {kaldirac}x ROE).\n🛡️ Stop kalkanı güncellendi! 🦅"))

                    if yeni_asama and yeni_asama >= 2 and yeni_asama < 5:
                        fiyatlar = {'giris': giris, 'tp1': tp1, 'tp2': tp2, 'tp3': tp3}
                        for uye in aktif_uyeler:
                            if str(uye['telegram_id']) in katilanlar_listesi:
                                mexc_gorevleri.append(
                                    pozisyon_guncelle(
                                        uye['mexc_api_key'], uye['mexc_api_secret'], 
                                        coin, yon, yeni_asama, uye['tp_ratios'], uye['stop_mode'], fiyatlar
                                    )
                                )
                
                elif durum == 'ISLEMDE' and not katilanlar_listesi:
                     db_guncellemeler.append(("UPDATE active_signals SET durum = 'KAPANDI' WHERE id = ?", (s_id,)))

            if db_guncellemeler:
                conn = sqlite3.connect(db.DB_NAME, timeout=30)
                try:
                    cursor = conn.cursor()
                    for query, params in db_guncellemeler:
                        cursor.execute(query, params)
                    conn.commit()
                finally:
                    conn.close()
            
            for tid, stype, val, prof in istatistik_guncellemeler:
                db.update_daily_stat(tid, stype, val, prof)
                
            for msg in vip_mesajlar:
                try: await client.send_message(VIP_KANAL_ID, msg)
                except: pass
                
            for tid, msg in dm_mesajlar:
                try: await client.send_message(tid, msg)
                except: pass

            for gorev in mexc_gorevleri:
                client.loop.create_task(gorev)

        except asyncio.TimeoutError:
            pass
        except Exception as e:
            print(f"Radar Kritik Hata: {e}")
            await asyncio.sleep(2)

async def gunluk_pnl_raporlayici():
    while True:
        try:
            su_an = datetime.datetime.now()
            if su_an.hour == 20 and su_an.minute == 59:
                
                # 1. KISIM: KULLANICILARA ÖZEL BİLANÇO VE GRAFİK (DM)
                aktif_uyeler = db.get_all_active_users()
                for uye in aktif_uyeler:
                    stats = db.get_daily_stats(uye['telegram_id'])
                    acilan = stats['acilan_islem'] if stats else 0
                    tps = stats['tp_adet'] if stats else 0
                    stops = stats['stop_adet'] if stats else 0
                    bes = stats['be_adet'] if stats else 0
                    kar = stats['kar_usdt'] if stats else 0.0
                    
                    kar_metni = f"{kar:+.2f} USDT" if uye['trade_mode'] == 'FIXED' else f"% {kar:+.2f} Net Kasa Büyümesi"
                        
                    pnl_msg = (
                        f"👑 **KRALIN SİNYALLERİ - GÜNLÜK BİLANÇO** 👑\n"
                        f"📅 **Tarih:** {su_an.strftime('%d %B %Y')}\n\n"
                        f"🚀 **Açılan Toplam Operasyon:** {acilan}\n"
                        f"🎯 **Başarılı TP:** {tps}\n"
                        f"🛡️ **Orijinal Stop (Zarar):** {stops}\n"
                        f"⚖️ **Break-Even (Zararsız):** {bes}\n\n"
                        f"💰 **Net Kasa Durumu:** `{kar_metni}`\n"
                    )
                    
                    try:
                        img_path = create_pnl_image(acilan, tps, stops, bes, kar, uye['trade_mode'])
                        await client.send_file(uye['telegram_id'], img_path, caption=pnl_msg)
                        os.remove(img_path) 
                    except Exception as e:
                        print(f"Görsel gönderilemedi: {e}")
                        await client.send_message(uye['telegram_id'], pnl_msg) 
                
                # 2. KISIM: VİP GRUBA YAPAY ZEKA (ML) VERİ RAPORU
                conn = sqlite3.connect(db.DB_NAME, timeout=30)
                try:
                    cursor = conn.cursor()
                    cursor.execute("SELECT COUNT(*) FROM active_signals")
                    toplam_sinyal = cursor.fetchone()[0]
                    
                    cursor.execute("SELECT COUNT(*) FROM active_signals WHERE durum IN ('BEKLIYOR', 'ISLEMDE')")
                    aktif_sinyal = cursor.fetchone()[0]
                except Exception as e:
                    print(f"Veri sayımı hatası: {e}")
                    toplam_sinyal, aktif_sinyal = 0, 0
                finally:
                    conn.close()

                vip_msg = (
                    f"🧠 **KSVİX YAPAY ZEKA (AI) İSTİHBARAT MERKEZİ** 🧠\n"
                    f"📅 **Tarih:** {su_an.strftime('%d %B %Y')}\n\n"
                    f"Wall Street standartlarında Makine Öğrenmesi (Machine Learning) modelimizi eğitmek için piyasadan toplanan güncel veri seti raporudur:\n\n"
                    f"🗃️ **Havuzdaki Toplam Eğitim Verisi:** `{toplam_sinyal} İşlem`\n"
                    f"⏳ **Şu An Radarda Takip Edilen:** `{aktif_sinyal} İşlem`\n\n"
                    f"*(Not: Veri setimiz 800-1000 işlem eşiğine ulaştığında K-Means ve Rastgele Orman algoritmaları devreye alınacaktır. KSVİX şu an sadece veri toplamaktadır.)* 🦅"
                )
                
                try: 
                    await client.send_message(VIP_KANAL_ID, vip_msg)
                except Exception as e:
                    print(f"VIP Gruba mesaj atılamadı: {e}")

                await asyncio.sleep(70) 
        except Exception:
            pass
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
