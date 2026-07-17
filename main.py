import asyncio
import sqlite3
import time
import datetime
import math
import os
import json
import requests
import ccxt.pro as ccxt 
from telethon import TelegramClient, events

import config
import database as db
from parser import parse_signal
from trader import islem_ac, bekleyen_emri_iptal_et, pozisyon_guncelle, acil_kapat
from visuals import create_pnl_image
import ai_engine  

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

client = TelegramClient('kralin_makinesi_session', config.API_ID, config.API_HASH)
VIP_KANAL_ID = int(config.VIP_CHANNEL)

# --- KSVİX HFT (YÜKSEK FREKANSLI) CANLI YAYIN HAFIZASI ---
CANLI_FIYATLAR = {}
AKTIF_YAYINLAR = set()

async def canli_yayin_ajani(borsa, sembol):
    """Bu ajan sadece tek bir coine kilitlenir ve 7/24 websocket akışını RAM'e yazar."""
    while sembol in AKTIF_YAYINLAR:
        try:
            ticker = await borsa.watch_ticker(sembol)
            CANLI_FIYATLAR[sembol] = float(ticker.get('last') or 0)
        except Exception:
            await asyncio.sleep(0.5)
# --------------------------------------------------------

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

def hesapla_ema(fiyatlar, periyot):
    if not fiyatlar: return 0
    k = 2 / (periyot + 1)
    ema_serisi = [fiyatlar[0]]
    for fiyat in fiyatlar[1:]:
        ema_serisi.append(fiyat * k + ema_serisi[-1] * (1 - k))
    return ema_serisi[-1]

def get_fear_and_greed():
    try:
        r = requests.get('https://api.alternative.me/fng/?limit=1', timeout=5)
        return int(r.json()['data'][0]['value'])
    except:
        return 50

async def piyasa_fotografi_cek(borsa, sembol):
    try:
        mumlar = await borsa.fetch_ohlcv(sembol, '15m', limit=50)
        if not mumlar or len(mumlar) < 30: return 0.0, 0.0, 0.0, 0.0, '[]'
        
        kapanislar = [mum[4] for mum in mumlar]
        hacim = mumlar[-1][5] 
        
        farklar = [kapanislar[i] - kapanislar[i-1] for i in range(1, len(kapanislar))]
        kazanclar = [f if f > 0 else 0 for f in farklar[-14:]]
        kayiplar = [-f if f < 0 else 0 for f in farklar[-14:]]
        ort_kazanc = sum(kazanclar) / 14
        ort_kayip = sum(kayiplar) / 14
        rs = ort_kazanc / ort_kayip if ort_kayip > 0 else 0
        rsi = 100 - (100 / (1 + rs)) if ort_kayip > 0 else 100
        
        ema_12 = hesapla_ema(kapanislar, 12)
        ema_26 = hesapla_ema(kapanislar, 26)
        macd = ema_12 - ema_26
        
        tr_list = []
        for i in range(1, len(mumlar)):
            high, low, prev_close = mumlar[i][2], mumlar[i][3], mumlar[i-1][4]
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_list.append(tr)
        atr = sum(tr_list[-14:]) / 14 if tr_list else 0.0
        
        video_verisi = []
        for m in mumlar[-20:]:
            video_verisi.append([m[1], m[2], m[3], m[4], m[5]])
            
        return round(rsi, 2), round(macd, 4), round(hacim, 2), atr, json.dumps(video_verisi)
    except: return 0.0, 0.0, 0.0, 0.0, '[]'

@client.on(events.NewMessage(incoming=True))
async def genel_handler(event):
    mesaj = event.raw_text.strip()
    
    if event.is_private:
        gonderen_id = event.sender_id
        if mesaj.startswith('/start'):
            await client.send_message(gonderen_id, "👑 **KSVİX KOMUTA MERKEZİNE HOŞ GELDİNİZ!** 👑\n\n🔒 **Kayıt Komutu:**\n`/kayit API_KEY API_SECRET`")
            
        elif mesaj.startswith('/kayit'):
            try:
                _, api_key, api_secret = mesaj.split()
                db.add_user(gonderen_id, api_key, api_secret)
                await client.send_message(gonderen_id, "✅ **Kasa Başarıyla Kilitlendi! KSVİX Otomasyonu Sağlandı.** 🦅")
            except: await client.send_message(gonderen_id, "❌ **Hatalı format!**")
                
        elif mesaj.startswith('/ayar'):
            try:
                _, mod, miktar, max_islem = mesaj.split()
                db.update_user_settings(gonderen_id, mod.upper(), float(miktar), int(max_islem))
                await client.send_message(gonderen_id, f"⚙️ **Ayarlar Güncellendi!**\nMod: `{mod.upper()}` | Miktar: `{miktar}` | Maksimum Açık İşlem: `{max_islem}`")
            except: await client.send_message(gonderen_id, "❌ **Hatalı format!**")
            
        elif mesaj.startswith('/hedef'):
            try:
                _, t1, t2, t3, t4 = mesaj.split()
                db.update_tp_ratios(gonderen_id, f"{t1},{t2},{t3},{t4}")
                await client.send_message(gonderen_id, f"🎯 **Kâr Oranları Ayarlandı!**")
            except: await client.send_message(gonderen_id, "❌ **Hatalı format!**")
            
        elif mesaj.startswith('/stop'):
            try:
                _, mode = mesaj.split()
                db.update_stop_mode(gonderen_id, mode.upper())
                await client.send_message(gonderen_id, f"🛡️ **Stop Kalkanı Aktif:** `{mode.upper()}`")
            except: await client.send_message(gonderen_id, "❌ **Hatalı format! /stop TRAILING şeklinde yazın.**")
            
        elif mesaj.startswith('/durdur'):
            db.toggle_user_active(gonderen_id, 0)
            await client.send_message(gonderen_id, "🛑 **Sistem Uyku Modunda!** Yeni sinyallere giriş yapılmayacak.")
            
        elif mesaj.startswith('/devam'):
            db.toggle_user_active(gonderen_id, 1)
            await client.send_message(gonderen_id, "✅ **Sistem Aktif!** Silahlar devrede, piyasa taranıyor. 🦅")
            
        elif mesaj.startswith('/sayac'):
            conn = sqlite3.connect(db.DB_NAME, timeout=30)
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM active_signals")
                toplam_sinyal = cursor.fetchone()[0]
            except: toplam_sinyal = 0
            finally: conn.close()
            
            sayac_msg = f"🧠 **KSVİX LSTM Yapay Zeka (AI) Havuzu:**\n\n🗃️ Toplanan Eğitim Videosu: `{toplam_sinyal}` İşlem\n✅ Derin Öğrenme Ağları Aktif!"
            await client.send_message(gonderen_id, sayac_msg)
            
    else:
        if event.chat_id == VIP_KANAL_ID:
            sinyal = parse_signal(mesaj)
            if not sinyal: return

            borsa_tmp = ccxt.mexc({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
            rsi_degeri, macd_degeri, hacim_degeri, atr, mum_video = 0.0, 0.0, 0.0, 0.0, '[]'
            fng = get_fear_and_greed()
            
            try:
                sembol_tmp = sinyal['coin'].replace('USDT', '') + '/USDT:USDT'
                await borsa_tmp.load_markets()
                hayalet_enjektor(borsa_tmp, sembol_tmp, sinyal['coin'])
                
                rsi_degeri, macd_degeri, hacim_degeri, atr, mum_video = await piyasa_fotografi_cek(borsa_tmp, sembol_tmp)
                
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
                    elif oran < 0.2: 
                        carpan = 10 ** round(math.log10(1/oran))
                        sinyal['giris'] *= carpan
                        sinyal['tp1'] *= carpan
                        sinyal['tp2'] *= carpan
                        sinyal['tp3'] *= carpan
                        sinyal['tp4'] *= carpan
                        sinyal['sl'] *= carpan
            except: pass
            finally: 
                try: await borsa_tmp.close()
                except: pass

            islem_sayisi, ai_ihtimal = 0, 100.0
            coin = sinyal['coin']
            try:
                islem_sayisi, ai_ihtimal = await asyncio.to_thread(ai_engine.sinyali_analiz_et, rsi_degeri, macd_degeri, hacim_degeri, fng, mum_video)
            except Exception as e:
                print(f"⚠️ AI Analiz Hatası: {e}")

            if islem_sayisi >= 50 and ai_ihtimal < 40.0:
                red_mesaj = f"🤖 **KSVİX LSTM AI YARGICI DEVREDE!**\n\n⚠️ **#{coin}** sinyali izlendi.\n📈 **Korku/Açgözlülük:** `{fng}`\n📉 **Başarı İhtimali:** `%{ai_ihtimal}`\n🛑 **Karar:** Bu bir tuzak formasyonu. Sinyal reddedildi!"
                try: await client.send_message(VIP_KANAL_ID, red_mesaj)
                except Exception as e: print(f"🛑 AI Mesaj Hatası: {e}")
                return

            ai_ek_metin = f"\n🤖 **AI LSTM Başarı Tahmini:** `%{ai_ihtimal}`" if islem_sayisi >= 50 else ""
                
            try:
                signal_id = db.sinyal_kaydet(
                    sinyal['coin'], sinyal['yon'], sinyal['giris'], 
                    sinyal['tp1'], sinyal['tp2'], sinyal['tp3'], sinyal['tp4'], sinyal['sl'], 
                    sinyal['kaldirac'], rsi_degeri, macd_degeri, hacim_degeri, atr, fng, mum_video
                )
            except Exception as e:
                print(f"🛑 DB KAYIT HATASI (sinyal_kaydet): {e}")
                return
            
            conn = sqlite3.connect(db.DB_NAME, timeout=30)
            try:
                cursor = conn.cursor()
                cursor.execute("UPDATE active_signals SET durum = 'IPTAL' WHERE coin = ? AND durum = 'BEKLIYOR' AND id != ?", (sinyal['coin'], signal_id))
                conn.commit()
            except: pass
            finally: conn.close()
            
            aktif_uyeler = db.get_all_active_users()
            if not aktif_uyeler: return
                
            gorevler = []
            for uye in aktif_uyeler:
                ayarlar = {'trade_mode': uye['trade_mode'], 'trade_amount': uye['trade_amount'], 'max_trades': uye['max_trades']}
                gorevler.append(islem_ac(uye['mexc_api_key'], uye['mexc_api_secret'], ayarlar, sinyal))
                
            sonuclar = await asyncio.gather(*gorevler, return_exceptions=True)
            
            for uye, sonuc in zip(aktif_uyeler, sonuclar):
                telegram_id = uye['telegram_id']
                if isinstance(sonuc, Exception): 
                    print(f"🛑 Python/CCXT Çöküşü ({telegram_id}): {sonuc}")
                elif sonuc.get('durum') == 'BASARILI':
                    try:
                        db.sinyale_katilan_ekle(signal_id, telegram_id)
                        db.update_daily_stat(telegram_id, 'open', value=1)
                    except Exception as e: print(f"🛑 DB Güncelleme Hatası ({telegram_id}): {e}")
                    
                    if sonuc.get('eski_silindi'):
                        mesaj_metni = f"✅ **#{sinyal['coin']} Sinyali Alındı!**{ai_ek_metin}\n🧹 Eski pusu emri iptal edildi, yeni sinyale geçildi. 🦅"
                    else:
                        mesaj_metni = f"✅ **#{sinyal['coin']} Sinyali Alındı!**{ai_ek_metin}\nPusudayız. 🦅"
                        
                    try: 
                        await client.send_message(telegram_id, mesaj_metni)
                        print(f"✅ Giriş mesajı atıldı: {telegram_id}")
                    except Exception as e: 
                        print(f"🛑 TELEGRAM MESAJ HATASI (Başarılı) -> {telegram_id}: {e}")
                else:
                    hata_nedeni = sonuc.get('hata_mesaji', 'Bilinmiyor')
                    print(f"⚠️ İşlem Reddedildi ({telegram_id}): {hata_nedeni}")
                    try: 
                        await client.send_message(telegram_id, f"⚠️ **#{sinyal['coin']} Pas Geçildi!**\n🛑 **Sebep:** `{hata_nedeni}`")
                        print(f"✅ Pas geçildi mesajı atıldı: {telegram_id}")
                    except Exception as e: 
                        print(f"🛑 TELEGRAM MESAJ HATASI (Pas Geçildi) -> {telegram_id}: {e}")

async def fiyat_takip_radari():
    borsa_ws = ccxt.mexc({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    try: await borsa_ws.load_markets()
    except: pass
    son_db_okuma = 0
    
    while True:
        try:
            su_an = time.time()
            if su_an - son_db_okuma >= 0.5:
                conn = sqlite3.connect(db.DB_NAME, timeout=30)
                try:
                    cursor = conn.cursor()
                    cursor.execute("SELECT id, coin, yon, giris, tp1, tp2, tp3, tp4, sl, durum, asama, eklenme_zamani, katilanlar, kaldirac, atr, en_iyi_fiyat FROM active_signals WHERE durum IN ('BEKLIYOR', 'ISLEMDE')")
                    bekleyenler = cursor.fetchall()
                    son_db_okuma = su_an
                finally:
                    conn.close()
            
            if not bekleyenler:
                AKTIF_YAYINLAR.clear()
                CANLI_FIYATLAR.clear()
                await asyncio.sleep(0.5)
                continue

            sembol_map = {}
            gerekli_semboller = set()
            for sinyal in bekleyenler:
                sembol = sinyal[1].replace('USDT', '') + '/USDT:USDT'
                hayalet_enjektor(borsa_ws, sembol, sinyal[1])
                sembol_map[sembol] = sinyal
                gerekli_semboller.add(sembol)
            
            # İşi biten coinlerin canlı yayın ajanlarını kapat
            for s in list(AKTIF_YAYINLAR):
                if s not in gerekli_semboller:
                    AKTIF_YAYINLAR.remove(s)
                    CANLI_FIYATLAR.pop(s, None)
                    
            # Yeni sinyaller için RAM tabanlı ajanları başlat
            for s in gerekli_semboller:
                if s not in AKTIF_YAYINLAR:
                    AKTIF_YAYINLAR.add(s)
                    client.loop.create_task(canli_yayin_ajani(borsa_ws, s))
            
            # 🔥 İŞTE HFT MUCİZESİ: Radar interneti beklemez, RAM'den okur!
            # Döngü hızı: Saniyede 10 kez (0.1 Saniye)
            await asyncio.sleep(0.1)
            
            aktif_uyeler = db.get_all_active_users()
            db_guncellemeler = []
            istatistik_guncellemeler = []
            vip_mesajlar = []
            dm_mesajlar = []
            mexc_gorevleri = [] 
            
            for sembol, sinyal in sembol_map.items():
                # Ajanın anlık olarak RAM'e yazdığı fiyatı çeker
                fiyat_last = CANLI_FIYATLAR.get(sembol, 0.0)
                if fiyat_last == 0.0: continue
                
                s_id, coin, yon, giris, tp1, tp2, tp3, tp4, sl, durum, asama, eklenme_zamani, katilanlar, kaldirac, atr, en_iyi_fiyat = sinyal
                katilanlar_listesi = [x for x in str(katilanlar).split(',') if x]
                yeni_durum, yeni_asama, bildirim = None, None, None

                yeni_en_iyi = en_iyi_fiyat
                if durum == 'ISLEMDE':
                    if yon == 'LONG' and fiyat_last > en_iyi_fiyat: yeni_en_iyi = fiyat_last
                    elif yon == 'SHORT' and (fiyat_last < en_iyi_fiyat or en_iyi_fiyat == 0.0): yeni_en_iyi = fiyat_last
                    if yeni_en_iyi != en_iyi_fiyat:
                        db_guncellemeler.append(("UPDATE active_signals SET en_iyi_fiyat = ? WHERE id = ?", (yeni_en_iyi, s_id)))

                if durum == 'BEKLIYOR':
                    gecen_sure = su_an - (eklenme_zamani or su_an)
                    
                    if fiyat_last > 0 and giris > 0 and ((giris / fiyat_last > 5) or (fiyat_last / giris > 5)):
                        yeni_durum = 'IPTAL'
                        bildirim = f"⚠️ **ÖLÇEK UYUŞMAZLIĞI** ⚠️\n#{coin} iptal edildi!"
                        for uye in aktif_uyeler:
                            if str(uye['telegram_id']) in katilanlar_listesi:
                                mexc_gorevleri.append(bekleyen_emri_iptal_et(uye['mexc_api_key'], uye['mexc_api_secret'], coin))
                    
                    elif gecen_sure > (8 * 3600):
                        yeni_durum = 'ZAMAN_ASIMI'
                        bildirim = f"⏳ **ZAMAN AŞIMI (8 SAAT)** ⏳\n#{coin} iptal edildi."
                        for uye in aktif_uyeler:
                            if str(uye['telegram_id']) in katilanlar_listesi:
                                mexc_gorevleri.append(bekleyen_emri_iptal_et(uye['mexc_api_key'], uye['mexc_api_secret'], coin))
                    
                    elif (yon == 'LONG' and fiyat_last <= giris) or (yon == 'SHORT' and fiyat_last >= giris):
                        yeni_durum, yeni_asama = 'ISLEMDE', 1
                        bildirim = f"🟢 **İŞLEME GİRİLDİ** | #{coin}\n⚡ **Yön:** {yon} | 🎯 **Giriş:** {giris} 🚀"
                
                elif durum == 'ISLEMDE':
                    if asama >= 1 and asama < 5:
                        tp_fiyatlar = {1: tp1, 2: tp2, 3: tp3, 4: tp4}
                        hedef_fiyat = tp_fiyatlar.get(asama, tp1)
                        mesafe_orani = abs(hedef_fiyat - fiyat_last) / fiyat_last
                        
                        if mesafe_orani < 0.005 and ((yon == 'LONG' and fiyat_last > giris * 1.01) or (yon == 'SHORT' and fiyat_last < giris * 0.99)):
                            try:
                                ob = await borsa_ws.fetch_order_book(sembol, limit=20)
                                asks_vol = sum([x[1] for x in ob['asks']])
                                bids_vol = sum([x[1] for x in ob['bids']])
                                
                                balina_kacti = False
                                if yon == 'LONG' and asks_vol > (bids_vol * 4): 
                                    balina_kacti = True
                                    bildirim = f"🐋 **BALİNA DUVARI TESPİTİ!** | #{coin}\n🚨 {hedef_fiyat} hedefine yakın devasa satıcı tespit edildi!\n💸 Çarpışmadan kaçıldı, Kâr erken alındı!"
                                elif yon == 'SHORT' and bids_vol > (asks_vol * 4): 
                                    balina_kacti = True
                                    bildirim = f"🐋 **BALİNA DUVARI TESPİTİ!** | #{coin}\n🚨 {hedef_fiyat} hedefine yakın devasa alıcı tespit edildi!\n💸 Çarpışmadan kaçıldı, Kâr erken alındı!"
                                
                                if balina_kacti:
                                    yeni_asama = asama + 1
                                    fiyat_last = hedef_fiyat 
                            except: pass

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
                            elif uye['stop_mode'] == 'TRAILING':
                                mesafe = (atr * 1.5) if atr > 0 else (giris * 0.02)
                                if yon == 'LONG':
                                    dinamik_s = yeni_en_iyi - mesafe
                                    kullanici_stop = dinamik_s if dinamik_s > sl else sl
                                else:
                                    dinamik_s = yeni_en_iyi + mesafe
                                    kullanici_stop = dinamik_s if (dinamik_s < sl or sl == 0) else sl
                                stop_tipi = "TRAILING"

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
                                elif stop_tipi == "TRAILING":
                                    if (yon == 'LONG' and kullanici_stop > giris) or (yon == 'SHORT' and kullanici_stop < giris):
                                        istatistik_guncellemeler.append((uye['telegram_id'], 'tp', 1, (uye['trade_amount']*(roe/100))))
                                        dm_msg = f"🛡️ **#{coin} Trailing (İz Süren) Stop!**\n📈 `+{roe:.2f}%` kâr cüzdana kilitlendi! 🔥"
                                    else:
                                        istatistik_guncellemeler.append((uye['telegram_id'], 'stop', 1, -(uye['trade_amount']*(roe/100))))
                                        dm_msg = f"🛡️ **#{coin} Trailing Stop.**\n🩸 Orijinal zarardan daha az kayıpla çıkıldı: `-{roe:.2f}%`"
                                else:
                                    istatistik_guncellemeler.append((uye['telegram_id'], 'tp', 1, (uye['trade_amount']*(roe/100))))
                                    dm_msg = f"🛡️ **#{coin} Hareketli Stop!**\n📈 `+{roe:.2f}%` kârla kapandı. 🔥"
                                dm_mesajlar.append((uye['telegram_id'], dm_msg))

                    if (yon == 'LONG' and fiyat_last <= sl) or (yon == 'SHORT' and fiyat_last >= sl):
                        yeni_durum = 'STOP_OLDU'
                        roe = (abs(sl - giris) / giris) * kaldirac * 100
                        bildirim = f"🛡 **STOP PATLADI** | #{coin}\n🩸 **Zarar:** `-{roe:.2f}%` ({kaldirac}x ROE) ⚔️"
                    else:
                        if asama < 2 and ((yon == 'LONG' and fiyat_last >= tp1) or (yon == 'SHORT' and fiyat_last <= tp1)):
                            yeni_asama = 2
                            roe = (abs(tp1 - giris) / giris) * kaldirac * 100
                            if not bildirim: bildirim = f"🎯 **TP1 VURULDU!** | #{coin}\n💸 **Kâr:** `+{roe:.2f}%` ({kaldirac}x ROE) 📈"
                        elif asama < 3 and ((yon == 'LONG' and fiyat_last >= tp2) or (yon == 'SHORT' and fiyat_last <= tp2)):
                            yeni_asama = 3
                            roe = (abs(tp2 - giris) / giris) * kaldirac * 100
                            if not bildirim: bildirim = f"🎯🎯 **TP2 VURULDU!** | #{coin}\n🔥 **Kâr:** `+{roe:.2f}%` ({kaldirac}x ROE) 📈"
                        elif asama < 4 and ((yon == 'LONG' and fiyat_last >= tp3) or (yon == 'SHORT' and fiyat_last <= tp3)):
                            yeni_asama = 4
                            roe = (abs(tp3 - giris) / giris) * kaldirac * 100
                            if not bildirim: bildirim = f"🎯🎯🎯 **TP3 VURULDU!** | #{coin}\n🚀 **Kâr:** `+{roe:.2f}%` ({kaldirac}x ROE) 📈"
                        elif asama < 5 and ((yon == 'LONG' and fiyat_last >= tp4) or (yon == 'SHORT' and fiyat_last <= tp4)):
                            yeni_asama, yeni_durum = 5, 'FULL_TP'
                            roe = (abs(tp4 - giris) / giris) * kaldirac * 100
                            if not bildirim: bildirim = f"👑 **FULL TP** | #{coin}\n🤑 **Maksimum Kâr:** `+{roe:.2f}%` ({kaldirac}x ROE) 🥂"
                            
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

            if db_guncellemeler:
                try:
                    conn = sqlite3.connect(db.DB_NAME, timeout=30)
                    cursor = conn.cursor()
                    for query, params in db_guncellemeler:
                        cursor.execute(query, params)
                    conn.commit()
                    conn.close()
                except Exception as e: print(f"🛑 DB Toplu Güncelleme Hatası: {e}")
            
            for tid, stype, val, prof in istatistik_guncellemeler:
                try: db.update_daily_stat(tid, stype, val, prof)
                except Exception as e: print(f"🛑 İstatistik DB Hatası: {e}")
                
            for msg in vip_mesajlar:
                try: await client.send_message(VIP_KANAL_ID, msg)
                except Exception as e: print(f"🛑 VIP Kanal Mesaj Hatası: {e}")
                
            for tid, msg in dm_mesajlar:
                try: await client.send_message(tid, msg)
                except Exception as e: print(f"🛑 DM Mesaj Hatası -> {tid}: {e}")

            for gorev in mexc_gorevleri:
                client.loop.create_task(gorev)

        except asyncio.TimeoutError: pass
        except Exception as e: 
            print(f"🛑 RADAR GENEL DÖNGÜ HATASI: {e}")
            await asyncio.sleep(0.5)

async def golge_senkronizator():
    while True:
        await asyncio.sleep(20) 
        try:
            aktif_uyeler = db.get_all_active_users()
            if not aktif_uyeler: continue

            conn = sqlite3.connect(db.DB_NAME, timeout=30)
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT id, coin, yon, giris, katilanlar FROM active_signals WHERE durum = 'BEKLIYOR'")
                bekleyenler = cursor.fetchall()
                
                cursor.execute("SELECT id, coin, katilanlar FROM active_signals WHERE durum = 'ISLEMDE'")
                islemdekiler = cursor.fetchall()
                
                for uye in aktif_uyeler:
                    try:
                        borsa = ccxt.mexc({'apiKey': uye['mexc_api_key'], 'secret': uye['mexc_api_secret'], 'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
                        pozisyonlar = await borsa.fetch_positions()
                        aktif_semboller = set()
                        for p in pozisyonlar:
                            if float(p.get('contracts', 0) or p.get('positionAmt', 0)) > 0:
                                aktif_semboller.add(p['symbol'])
                        
                        uye_tid = str(uye['telegram_id'])
                        
                        for b_id, coin, yon, giris, katilanlar in bekleyenler:
                            sembol = coin.replace('USDT', '') + '/USDT:USDT'
                            if sembol in aktif_semboller:
                                cursor.execute("UPDATE active_signals SET durum = 'ISLEMDE', asama = 1 WHERE id = ?", (b_id,))
                                conn.commit()
                                
                                katilanlar_listesi = [x for x in str(katilanlar).split(',') if x]
                                msg = f"🟢 **#{coin} İşleme Girildi!**\n⚡ **Yön:** {yon} | 🎯 **Giriş:** {giris}\n🦅 KSVİX pusudan çıktı, operasyon başladı! (Ajan Onayı)"
                                if uye_tid in katilanlar_listesi:
                                    try: await client.send_message(int(uye_tid), msg)
                                    except: pass
                        
                        for i_id, coin, katilanlar in islemdekiler:
                            sembol = coin.replace('USDT', '') + '/USDT:USDT'
                            katilanlar_listesi = [x for x in str(katilanlar).split(',') if x]
                            
                            if sembol not in aktif_semboller and uye_tid in katilanlar_listesi:
                                katilanlar_listesi.remove(uye_tid)
                                cursor.execute("UPDATE active_signals SET katilanlar = ? WHERE id = ?", (",".join(katilanlar_listesi), i_id))
                                conn.commit()
                                
                    except: pass
                    finally: 
                        try: await borsa.close()
                        except: pass
                        
            finally: conn.close()
        except: pass

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
                    except: await client.send_message(uye['telegram_id'], pnl_msg) 
                
                conn = sqlite3.connect(db.DB_NAME, timeout=30)
                try:
                    cursor = conn.cursor()
                    cursor.execute("SELECT COUNT(*) FROM active_signals")
                    toplam_sinyal = cursor.fetchone()[0]
                    cursor.execute("SELECT COUNT(*) FROM active_signals WHERE durum IN ('BEKLIYOR', 'ISLEMDE')")
                    aktif_sinyal = cursor.fetchone()[0]
                except: toplam_sinyal, aktif_sinyal = 0, 0
                finally: conn.close()

                vip_msg = (
                    f"🧠 **KSVİX YAPAY ZEKA (AI) İSTİHBARAT MERKEZİ** 🧠\n"
                    f"📅 **Tarih:** {su_an.strftime('%d %B %Y')}\n\n"
                    f"🗃️ **Havuzdaki Toplam Eğitim Videoları:** `{toplam_sinyal} İşlem`\n"
                    f"⏳ **Şu An Radarda Takip Edilen:** `{aktif_sinyal} İşlem`\n\n"
                    f"*(Not: KSVİX LSTM Derin Öğrenme Ağları AKTİFTİR. Bütün sinyaller zaman dizisine göre filtrelenmektedir.)* 🦅"
                )
                
                try: await client.send_message(VIP_KANAL_ID, vip_msg)
                except: pass

                await asyncio.sleep(70) 
        except: pass
        await asyncio.sleep(30)

async def main():
    print("KSVİX Motorları Ateşleniyor...")
    db.init_db()
    await client.start(bot_token=config.BOT_TOKEN)
    print("🤖 KSVİX VIP Telegram'a Sızdı.")
    client.loop.create_task(fiyat_takip_radari())
    client.loop.create_task(golge_senkronizator())
    client.loop.create_task(gunluk_pnl_raporlayici())
    print("🦅 V8 Radarları, Balina İz Sürücü ve LSTM (AI) Motoru Aktif...")
    await client.run_until_disconnected()

if __name__ == '__main__':
    loop.run_until_complete(main())
