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

def gercek_kar_hesapla(yon, giris, tp1, tp2, tp3, tp4, kapanis_fiyati, kaldirac, trade_amount, asama_kapanis, tp_ratios_str):
    tp_fiyatlari = [tp1, tp2, tp3, tp4]
    try:
        tp_oranlari = [float(x)/100.0 for x in tp_ratios_str.split(',')]
    except:
        tp_oranlari = [0.25, 0.25, 0.25, 0.25]
        
    net_kar = 0.0
    kalan_oran = 1.0
    
    vurulan_tp_sayisi = asama_kapanis - 1
    if vurulan_tp_sayisi > 4: vurulan_tp_sayisi = 4
    if vurulan_tp_sayisi < 0: vurulan_tp_sayisi = 0
    
    # 1. Aşama: Vurulan TP'lerin kısmi kârlarını topla
    for i in range(vurulan_tp_sayisi):
        hedef = tp_fiyatlari[i]
        satis_orani = tp_oranlari[i]
        fark_yuzde = (hedef - giris) / giris if yon == 'LONG' else (giris - hedef) / giris
        roe = fark_yuzde * kaldirac * 100
        net_kar += (trade_amount * satis_orani) * (roe / 100)
        kalan_oran -= satis_orani
        
    # 2. Aşama: İçeride kalan son parçanın kapanış (Stop/BE/Market) fiyatından kâr-zararını hesapla
    if kalan_oran > 0.01:
        fark_yuzde = (kapanis_fiyati - giris) / giris if yon == 'LONG' else (giris - kapanis_fiyati) / giris
        son_roe = fark_yuzde * kaldirac * 100
        net_kar += (trade_amount * kalan_oran) * (son_roe / 100)
        
    return net_kar

def islem_simule_et(bakiye, mod, yon, giris, tp1, tp2, tp3, tp4, sl, kaldirac, atr, en_iyi_fiyat, asama, durum):
    if giris <= 0 or bakiye <= 0: return bakiye
    if en_iyi_fiyat == 0.0: en_iyi_fiyat = giris
        
    margin = bakiye * 0.005 
    net_kar = 0.0
    kalan_oran = 1.0 
    tp_oranlari = [0.70, 0.10, 0.10, 0.10] 
    tp_fiyatlari = [tp1, tp2, tp3, tp4]

    vurulan_tp_sayisi = asama - 1
    if vurulan_tp_sayisi > 4: vurulan_tp_sayisi = 4
    if vurulan_tp_sayisi < 0: vurulan_tp_sayisi = 0

    for i in range(vurulan_tp_sayisi):
        hedef = tp_fiyatlari[i]
        satis_orani = tp_oranlari[i]
        roe = (abs(hedef - giris) / giris) * kaldirac * 100
        net_kar += (margin * satis_orani) * (roe / 100)
        kalan_oran -= satis_orani

    if kalan_oran <= 0.01: return bakiye + net_kar 

    kapanis_fiyati = sl
    if mod == 'BREAKEVEN':
        kapanis_fiyati = giris if vurulan_tp_sayisi >= 1 else sl
    elif mod == 'MOVING':
        if vurulan_tp_sayisi == 1: kapanis_fiyati = giris
        elif vurulan_tp_sayisi == 2: kapanis_fiyati = tp1
        elif vurulan_tp_sayisi == 3: kapanis_fiyati = tp2
        elif vurulan_tp_sayisi == 4: kapanis_fiyati = tp3
        else: kapanis_fiyati = sl
    elif mod == 'TRAILING':
        mesafe = (atr * 1.5) if atr > 0 else (giris * 0.02)
        if vurulan_tp_sayisi < 1: 
            kapanis_fiyati = sl
        else:
            if yon == 'LONG':
                dinamik_s = en_iyi_fiyat - mesafe
                kapanis_fiyati = dinamik_s if dinamik_s > giris else giris
            else:
                dinamik_s = en_iyi_fiyat + mesafe
                kapanis_fiyati = dinamik_s if (dinamik_s < giris and dinamik_s > 0) else giris

    fark_yuzde = (kapanis_fiyati - giris) / giris if yon == 'LONG' else (giris - kapanis_fiyati) / giris
    son_roe = fark_yuzde * kaldirac * 100
    net_kar += (margin * kalan_oran) * (son_roe / 100)
    
    return bakiye + net_kar

CANLI_FIYATLAR = {}
AKTIF_YAYINLAR = set()

async def canli_yayin_ajani(borsa, sembol):
    while sembol in AKTIF_YAYINLAR:
        try:
            ticker = await borsa.watch_ticker(sembol)
            CANLI_FIYATLAR[sembol] = float(ticker.get('last') or 0)
        except Exception:
            await asyncio.sleep(0.5)

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
        
        try:
            mumlar_4h = await borsa.fetch_ohlcv(sembol, '4h', limit=20)
            kapanislar_4h = [m[4] for m in mumlar_4h]
            ema_10_4h = hesapla_ema(kapanislar_4h, 10)
            trend_4h = 1.0 if kapanislar_4h and kapanislar_4h[-1] > ema_10_4h else 0.0
        except: trend_4h = 0.5
        
        if not mumlar or len(mumlar) < 30:
            return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5, 0.0, 0.0, 0.0, '[]'
        
        kapanislar = [mum[4] for mum in mumlar]
        hacim = mumlar[-1][5] 
        anlik_fiyat = mumlar[-1][4]
        
        en_yuksek = max([m[2] for m in mumlar])
        en_dusuk = min([m[3] for m in mumlar])
        direnc_mesafe = ((en_yuksek - anlik_fiyat) / anlik_fiyat) * 100 if anlik_fiyat > 0 else 0.0
        destek_mesafe = ((anlik_fiyat - en_dusuk) / anlik_fiyat) * 100 if anlik_fiyat > 0 else 0.0
        
        farklar = [kapanislar[i] - kapanislar[i-1] for i in range(1, len(kapanislar))]
        kazanclar = [f if f > 0 else 0 for f in farklar[-14:]]
        kayiplar = [-f if f < 0 else 0 for f in farklar[-14:]]
        ort_kazanc = sum(kazanclar) / 14
        ort_kayip = sum(kayiplar) / 14
        rs = ort_kazanc / ort_kayip if ort_kayip > 0 else 0
        rsi = 100 - (100 / (1 + rs)) if ort_kayip > 0 else 100
        
        macd = hesapla_ema(kapanislar, 12) - hesapla_ema(kapanislar, 26)
        
        cum_vp, cum_vol = 0.0, 0.0
        onceki_vwap_mesafe = 0.0
        for i, m in enumerate(mumlar):
            tp = (m[2] + m[3] + m[4]) / 3.0
            cum_vp += tp * m[5]
            cum_vol += m[5]
            
            if i == len(mumlar) - 2:
                onceki_vwap = cum_vp / cum_vol if cum_vol > 0 else m[4]
                onceki_vwap_mesafe = ((m[4] - onceki_vwap) / onceki_vwap) * 100
                
        vwap = cum_vp / cum_vol if cum_vol > 0 else anlik_fiyat
        vwap_mesafe = ((anlik_fiyat - vwap) / vwap) * 100
        
        tr_list = []
        for i in range(1, len(mumlar)):
            high, low, prev_close = mumlar[i][2], mumlar[i][3], mumlar[i-1][4]
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_list.append(tr)
        atr = sum(tr_list[-14:]) / 14 if tr_list else 0.0
        
        sikisma_orani = (atr / anlik_fiyat) * 100 if anlik_fiyat > 0 else 0.0
        
        video_verisi = [[m[1], m[2], m[3], m[4], m[5]] for m in mumlar[-20:]]
            
        return (round(rsi, 2), round(macd, 4), round(hacim, 2), atr, 
                round(vwap_mesafe, 4), round(onceki_vwap_mesafe, 4), 
                round(trend_4h, 1), round(direnc_mesafe, 2), round(destek_mesafe, 2), 
                round(sikisma_orani, 4), json.dumps(video_verisi))
    
    except Exception as e: 
        print(f"⚠️ MUM ÇEKİLEMEDİ ({sembol}): {e}")
        return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5, 0.0, 0.0, 0.0, '[]'

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
        
        elif mesaj.startswith('/ksvix_modu'):
            uye = db.get_user_by_id(gonderen_id)
            if uye:
                if uye['trade_mode'] == 'FIXED':
                    await client.send_message(gonderen_id, "🛑 **Komutanım, KSVİX Derin Öğrenme Zekası sabit (FIXED) marjinle sınırlandırılamaz.**\nKasanızı asimetrik olarak katlamak ve otonom zekayı devreye sokmak için önce ayarlarınızı PERCENT (Yüzde) olarak güncelleyiniz. (`/ayar PERCENT miktar max_islem`)")
                else:
                    yeni_durum = 1 if dict(uye).get('ksvix_mode', 0) == 0 else 0
                    db.toggle_ksvix_mode(gonderen_id, yeni_durum)
                    if yeni_durum == 1:
                        await client.send_message(gonderen_id, "🔥 **KSVİX OTONOM MODU AKTİF!** 🔥\n🧠 Kelly Kriteri (Dinamik Marjin) ve Tazelik Filtresi (Yapısal Koruma) devrede. Artık makine yüksek ihtimalli sinyallerde masaya ağırlığını koyacak!")
                    else:
                        await client.send_message(gonderen_id, "❄️ **KSVİX Otonom Modu Kapatıldı.**\nSistem standart marjin ve bekleme kurallarına döndü.")
        
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
                cursor.execute("SELECT COUNT(*) FROM active_signals WHERE (asama >= 2 OR durum = 'STOP_OLDU') AND mum_gecmisi != '[]'")
                egitim_verisi = cursor.fetchone()[0]
            except: 
                toplam_sinyal, egitim_verisi = 0, 0
            finally: conn.close()
            
            sayac_msg = (
                f"🧠 **KSVİX LSTM Yapay Zeka Anatomisi:**\n\n"
                f"🗃️ Radara Giren Toplam İşlem: `{toplam_sinyal}`\n"
                f"📚 Özümsenen Tecrübe (Eğitim Verisi): `{egitim_verisi}` İşlem\n\n"
                f"🧬 **Sinir Ağı (Nöron) Yapısı:**\n"
                f"🔄 Antrenman (Epoch) Derinliği: `25 Tur`\n"
                f"⚡ Nöron Dalları: `128 Ana + 64 Alt LSTM Ağ`\n"
                f"👁️‍🗨️ Aktif Loblar: `MTF(4H), Formasyon, Pivot(D/D), VWAP`\n\n"
                f"✅ Otonom Derin Öğrenme Motoru Tam Gaz Aktif!"
            )
            await client.send_message(gonderen_id, sayac_msg)
            
    else:
        if event.chat_id == VIP_KANAL_ID:
            sinyal = parse_signal(mesaj)
            if not sinyal: return

            borsa_tmp = ccxt.mexc({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
            rsi_degeri, macd_degeri, hacim_degeri, atr, vwap_mesafe, onceki_vwap_mesafe = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
            trend_4h, direnc_mesafe, destek_mesafe, sikisma_orani, mum_video = 0.5, 0.0, 0.0, 0.0, '[]'
            fng = get_fear_and_greed()
            
            try:
                sembol_tmp = sinyal['coin'].replace('USDT', '') + '/USDT:USDT'
                await borsa_tmp.load_markets()
                hayalet_enjektor(borsa_tmp, sembol_tmp, sinyal['coin'])
                
                (rsi_degeri, macd_degeri, hacim_degeri, atr, vwap_mesafe, onceki_vwap_mesafe,
                 trend_4h, direnc_mesafe, destek_mesafe, sikisma_orani, mum_video) = await piyasa_fotografi_cek(borsa_tmp, sembol_tmp)
                
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
            
            # 👑 FORMASYON AVCISI BYPASS KONTROLÜ
            is_formasyon_avcisi = "FORMASYON AVCISI" in mesaj.upper()
            
            # 👑 KRALIN ÇİFT ONAYLI VWAP KURALI VE HACİM LİKİDİTE KALKANI
            dinamik_sinir = max(1.2, min(3.5, sikisma_orani * 1.5))
            red_nedeni = None
            
            if not is_formasyon_avcisi:
                if sinyal['yon'] == 'LONG':
                    if vwap_mesafe <= 0.0 or vwap_mesafe > dinamik_sinir:
                        red_nedeni = f"VWAP Uyuşmazlığı (Şu Anki Mum: %{vwap_mesafe:.2f} | İstenen: 0 ile {dinamik_sinir:.2f})"
                    elif onceki_vwap_mesafe <= 0.0 or onceki_vwap_mesafe > dinamik_sinir:
                        red_nedeni = f"VWAP Uyuşmazlığı (Önceki 15Dk Mum: %{onceki_vwap_mesafe:.2f} | İstenen: 0 ile {dinamik_sinir:.2f})"
                elif sinyal['yon'] == 'SHORT':
                    if vwap_mesafe >= 0.0 or vwap_mesafe < -dinamik_sinir:
                        red_nedeni = f"VWAP Uyuşmazlığı (Şu Anki Mum: %{vwap_mesafe:.2f} | İstenen: -{dinamik_sinir:.2f} ile 0)"
                    elif onceki_vwap_mesafe >= 0.0 or onceki_vwap_mesafe < -dinamik_sinir:
                        red_nedeni = f"VWAP Uyuşmazlığı (Önceki 15Dk Mum: %{onceki_vwap_mesafe:.2f} | İstenen: -{dinamik_sinir:.2f} ile 0)"
                        
                if not red_nedeni and hacim_degeri < 75000:
                    red_nedeni = f"Yetersiz Hacim / Likidite (Minimum: 75.000 | Mevcut: {hacim_degeri:.2f})"
                    
                if red_nedeni:
                    print(f"🛑 REDDEDİLDİ: #{coin} | Sebep: {red_nedeni}")
                    aktif_uyeler = db.get_all_active_users()
                    for uye in aktif_uyeler:
                        try: await client.send_message(uye['telegram_id'], f"🛑 **#{coin} SİNYALİ REDDEDİLDİ!**\n❌ **Sebep:** `{red_nedeni}`")
                        except: pass
                    return
            
            try:
                islem_sayisi, ai_ihtimal = await asyncio.to_thread(
                    ai_engine.sinyali_analiz_et, sinyal['yon'], rsi_degeri, macd_degeri, 
                    hacim_degeri, fng, vwap_mesafe, trend_4h, direnc_mesafe, destek_mesafe, sikisma_orani, mum_video
                )
            except Exception as e:
                print(f"⚠️ AI Analiz Hatası: {e}")

            # 👑 OTONOM YARGIÇ REDDİ
            if not is_formasyon_avcisi:
                if islem_sayisi >= 50 and ai_ihtimal < 70.0:
                    red_nedeni = f"Yapay Zeka Onaylamadı (Minimum Beklenen: %70 | Mevcut Skor: %{ai_ihtimal})"
                    print(f"🛑 REDDEDİLDİ [YAPAY ZEKA]: #{coin} | Sebep: {red_nedeni}")
                    aktif_uyeler = db.get_all_active_users()
                    for uye in aktif_uyeler:
                        try: await client.send_message(uye['telegram_id'], f"🤖 **#{coin} SİNYALİ AI TARAFINDAN REDDEDİLDİ!**\n❌ **Sebep:** `{red_nedeni}`")
                        except: pass
                    return

            if is_formasyon_avcisi:
                ai_ek_metin = f"\n🎯 **Strateji:** `Formasyon Avcısı (VIP Bypass)`\n🤖 **AI Arka Plan Skoru:** `%{ai_ihtimal}`"
                print(f"⚡ FORMASYON AVCISI TESPİT EDİLDİ: #{coin} | Tüm Kalkanlar Delindi!")
            else:
                ai_ek_metin = f"\n🤖 **AI Başarı Tahmini:** `%{ai_ihtimal}`\n📉 **VWAP Çizgisine Uzaklık:** `% {vwap_mesafe}`" if islem_sayisi >= 50 else f"\n📉 **VWAP Çizgisine Uzaklık:** `% {vwap_mesafe}`"
                
            try:
                signal_id = db.sinyal_kaydet(
                    sinyal['coin'], sinyal['yon'], sinyal['giris'], 
                    sinyal['tp1'], sinyal['tp2'], sinyal['tp3'], sinyal['tp4'], sinyal['sl'], 
                    sinyal['kaldirac'], rsi_degeri, macd_degeri, hacim_degeri, atr, fng, 
                    vwap_mesafe, trend_4h, direnc_mesafe, destek_mesafe, sikisma_orani, mum_video
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
                
                # 👑 DİNAMİK MARJİN (KELLY KRİTERİ)
                if dict(uye).get('ksvix_mode', 0) == 1 and uye['trade_mode'] == 'PERCENT' and islem_sayisi >= 50:
                    if ai_ihtimal >= 80.0:
                        ayarlar['trade_amount'] *= 2.0
                        print(f"🔥 KSVİX MODU: {uye['telegram_id']} için risk 2x yapıldı! (AI: %{ai_ihtimal})")
                        
                gorevler.append(islem_ac(uye['mexc_api_key'], uye['mexc_api_secret'], ayarlar, sinyal))
                
            sonuclar = await asyncio.gather(*gorevler, return_exceptions=True)
            
            for uye, sonuc in zip(aktif_uyeler, sonuclar):
                telegram_id = uye['telegram_id']
                if isinstance(sonuc, Exception): pass
                elif sonuc.get('durum') == 'BASARILI':
                    try:
                        db.sinyale_katilan_ekle(signal_id, telegram_id)
                        db.update_daily_stat(telegram_id, 'open', value=1)
                    except: pass
                    
                    ksvix_not = "\n🔥 **KSVİX Modu Aktif:** Fırsat avı için marjin 2x yükseltildi!" if (dict(uye).get('ksvix_mode', 0) == 1 and uye['trade_mode'] == 'PERCENT' and ai_ihtimal >= 80.0) else ""
                    
                    if sonuc.get('eski_silindi'):
                        mesaj_metni = f"✅ **#{sinyal['coin']} Sinyali Alındı!**{ai_ek_metin}{ksvix_not}\n🧹 Eski pusu emri iptal edildi, yeni sinyale geçildi. 🦅"
                    else:
                        mesaj_metni = f"✅ **#{sinyal['coin']} Sinyali Alındı!**{ai_ek_metin}{ksvix_not}\nPusudayız. 🦅"
                        
                    try: await client.send_message(telegram_id, mesaj_metni)
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
            
            for s in list(AKTIF_YAYINLAR):
                if s not in gerekli_semboller:
                    AKTIF_YAYINLAR.remove(s)
                    CANLI_FIYATLAR.pop(s, None)
                    
            for s in gerekli_semboller:
                if s not in AKTIF_YAYINLAR:
                    AKTIF_YAYINLAR.add(s)
                    client.loop.create_task(canli_yayin_ajani(borsa_ws, s))
            
            await asyncio.sleep(0.1)
            
            aktif_uyeler = db.get_all_active_users()
            db_guncellemeler = []
            istatistik_guncellemeler = []
            vip_mesajlar = []
            dm_mesajlar = []
            mexc_gorevleri = [] 
            
            for sembol, sinyal in sembol_map.items():
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
                    
                    # 👑 KSVİX YAPISAL TAZELİK FİLTRESİ
                    ksvix_kullanicilar = [str(u['telegram_id']) for u in aktif_uyeler if dict(u).get('ksvix_mode', 0) == 1]
                    
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
                                
                    elif any(tid in katilanlar_listesi for tid in ksvix_kullanicilar) and ((yon == 'LONG' and fiyat_last <= sl) or (yon == 'SHORT' and fiyat_last >= sl)):
                        yeni_durum = 'IPTAL'
                        bildirim = f"⚠️ **KSVİX TAZELİK FİLTRESİ DEVREDE!** ⚠️\n#{coin} işlemi giriş bölgesine gelmeden yapısal kırılıma uğradı. Otonom zeka tuzağa düşmemek için pusu emrini iptal etti!"
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
                            
                            # 👑 ATR İZ SÜREN STOP
                            elif uye['stop_mode'] == 'TRAILING':
                                mesafe = (atr * 1.5) if atr > 0 else (giris * 0.02)
                                if asama < 2:
                                    kullanici_stop, stop_tipi = sl, "ORIJINAL"
                                else:
                                    if yon == 'LONG':
                                        dinamik_s = yeni_en_iyi - mesafe
                                        kullanici_stop = dinamik_s if dinamik_s > giris else giris
                                    else:
                                        dinamik_s = yeni_en_iyi + mesafe
                                        kullanici_stop = dinamik_s if (dinamik_s < giris and dinamik_s > 0) else giris
                                    stop_tipi = "TRAILING"

                            if (yon == 'LONG' and fiyat_last <= kullanici_stop) or (yon == 'SHORT' and fiyat_last >= kullanici_stop):
                                katilanlar_listesi.remove(tid_str)
                                db_guncellemeler.append(("UPDATE active_signals SET katilanlar = ? WHERE id = ?", (",".join(katilanlar_listesi), s_id)))
                                
                                mexc_gorevleri.append(acil_kapat(uye['mexc_api_key'], uye['mexc_api_secret'], coin, yon))
                                
                                # 👑 KÂR/ZARAR MUHASEBESİ: Geçmiş TPlere göre net kapanış bilançosu
                                roe = (abs(fiyat_last - giris) / giris) * kaldirac * 100
                                kar = gercek_kar_hesapla(yon, giris, tp1, tp2, tp3, tp4, kullanici_stop, kaldirac, uye['trade_amount'], asama, uye['tp_ratios'])
                                sembol_para = "USDT" if uye['trade_mode'] == 'FIXED' else "%"
                                
                                if stop_tipi == "ORIJINAL": 
                                    istatistik_guncellemeler.append((uye['telegram_id'], 'stop', 1, kar))
                                    dm_msg = f"🚨 **#{coin} Stop Loss.**\n🩸 Kapanış ROE: `-{roe:.2f}%` ({kaldirac}x)\n💸 **Net Bilanço:** `{kar:+.2f} {sembol_para}`"
                                elif stop_tipi == "BREAK_EVEN":
                                    istatistik_guncellemeler.append((uye['telegram_id'], 'be', 1, kar))
                                    dm_msg = f"🛡️ **#{coin} Break-Even!**\n⚖️ Kalan pozisyon sıfır riskle kapandı.\n💸 **Net (Önceki TP dahil):** `{kar:+.2f} {sembol_para}`"
                                elif stop_tipi == "TRAILING":
                                    if (yon == 'LONG' and kullanici_stop > giris) or (yon == 'SHORT' and kullanici_stop < giris):
                                        istatistik_guncellemeler.append((uye['telegram_id'], 'tp', 1, kar))
                                        dm_msg = f"🛡️ **#{coin} Trailing (İz Süren) Stop!**\n📈 Son kapanış ROE: `+{roe:.2f}%`\n💸 **Net Bilanço:** `{kar:+.2f} {sembol_para}`"
                                    else:
                                        istatistik_guncellemeler.append((uye['telegram_id'], 'be', 1, kar))
                                        dm_msg = f"🛡️ **#{coin} Trailing (Breakeven).**\n⚖️ Sıfır riskle ayrıldık.\n💸 **Net (Önceki TP dahil):** `{kar:+.2f} {sembol_para}`"
                                else:
                                    istatistik_guncellemeler.append((uye['telegram_id'], 'tp', 1, kar))
                                    dm_msg = f"🛡️ **#{coin} Hareketli Stop!**\n📈 Kapanış ROE: `+{roe:.2f}%`\n💸 **Net Bilanço:** `{kar:+.2f} {sembol_para}`"
                                dm_mesajlar.append((uye['telegram_id'], dm_msg))

                    if (yon == 'LONG' and fiyat_last <= sl) or (yon == 'SHORT' and fiyat_last >= sl):
                        yeni_durum = 'STOP_OLDU'
                        roe = (abs(fiyat_last - giris) / giris) * kaldirac * 100
                        if asama < 2:
                            bildirim = f"🛡 **STOP PATLADI** | #{coin}\n🩸 **Zarar:** `-{roe:.2f}%` ({kaldirac}x ROE) ⚔️"
                        else:
                            bildirim = None
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
                                    # 👑 FULL TP DURUMUNDA GÜNLÜK MUHASEBEYE İŞLE
                                    kar = gercek_kar_hesapla(yon, giris, tp1, tp2, tp3, tp4, tp4, kaldirac, uye['trade_amount'], 5, uye['tp_ratios'])
                                    istatistik_guncellemeler.append((uye['telegram_id'], 'tp', 1, kar))

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
                                    dm_mesajlar.append((uye['telegram_id'], f"👑 **#{coin} FULL TP Vuruldu!**\n🤑 Maksimum kâr cebinde! İşlem tamamen kapandı. 🥂"))
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
        await asyncio.sleep(5) 
        try:
            aktif_uyeler = db.get_all_active_users()
            if not aktif_uyeler: continue

            conn = sqlite3.connect(db.DB_NAME, timeout=30)
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT id, coin, yon, giris, katilanlar FROM active_signals WHERE durum = 'BEKLIYOR'")
                bekleyenler = cursor.fetchall()
                
                cursor.execute("SELECT id, coin, yon, giris, tp1, tp2, tp3, tp4, sl, kaldirac, asama, katilanlar FROM active_signals WHERE durum = 'ISLEMDE'")
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
                        sembol_para = "USDT" if uye['trade_mode'] == 'FIXED' else "%"
                        
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
                        
                        for i_id, coin, yon, giris, tp1, tp2, tp3, tp4, sl, kaldirac, asama, katilanlar in islemdekiler:
                            sembol = coin.replace('USDT', '') + '/USDT:USDT'
                            katilanlar_listesi = [x for x in str(katilanlar).split(',') if x]
                            
                            if sembol not in aktif_semboller and uye_tid in katilanlar_listesi:
                                katilanlar_listesi.remove(uye_tid)
                                cursor.execute("UPDATE active_signals SET katilanlar = ? WHERE id = ?", (",".join(katilanlar_listesi), i_id))
                                
                                if not katilanlar_listesi:
                                    cursor.execute("UPDATE active_signals SET durum = 'STOP_OLDU' WHERE id = ?", (i_id,))
                                conn.commit()
                                
                                if asama >= 2 and uye['stop_mode'] != 'NONE':
                                    kar = gercek_kar_hesapla(yon, giris, tp1, tp2, tp3, tp4, giris, kaldirac, uye['trade_amount'], asama, uye['tp_ratios'])
                                    db.update_daily_stat(uye['telegram_id'], 'be', 1, kar)
                                    msg = f"🛡️ **GÖLGE AJAN RAPORU** | #{coin}\n⚖️ İşlem borsada (Başabaş/Trailing) noktasında kapandı!\n💸 **Net Kazanç:** `{kar:+.2f} {sembol_para}`"
                                else:
                                    kar = gercek_kar_hesapla(yon, giris, tp1, tp2, tp3, tp4, sl, kaldirac, uye['trade_amount'], asama, uye['tp_ratios'])
                                    db.update_daily_stat(uye['telegram_id'], 'stop', 1, kar)
                                    msg = f"🛡️ **GÖLGE AJAN RAPORU** | #{coin}\n🚨 Borsadaki asıl Stop-Loss iğne ile tetiklendi!\n💸 **Net Bilanço:** `{kar:+.2f} {sembol_para}`"
                                    
                                try: await client.send_message(int(uye_tid), msg)
                                except: pass
                                
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
                        f"🎯 **Tam/Kısmi TP Başarısı:** {tps}\n"
                        f"🛡️ **Asıl Stop (Zarar):** {stops}\n"
                        f"⚖️ **Break-Even & İz Süren (Zararsız):** {bes}\n\n"
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
                    
                    dosya = "sanal_kasa.json"
                    kasa = {
                        "MOVING": {"bakiye": 200.0, "dunku_bakiye": 200.0},
                        "TRAILING": {"bakiye": 200.0, "dunku_bakiye": 200.0},
                        "BREAKEVEN": {"bakiye": 200.0, "dunku_bakiye": 200.0},
                        "islenen_idler": []
                    }
                    if os.path.exists(dosya):
                        try:
                            with open(dosya, 'r') as f: kasa = json.load(f)
                        except: pass

                    cursor.execute("SELECT id, coin, yon, giris, tp1, tp2, tp3, tp4, sl, kaldirac, atr, en_iyi_fiyat, asama, durum FROM active_signals WHERE durum IN ('STOP_OLDU', 'FULL_TP')")
                    kapananlar =fetchall()
                    
                    islenen_idler_set = set(kasa["islenen_idler"])
                    yeni_islenen = 0
                    
                    for islem in kapananlar:
                        s_id, coin, yon, giris, tp1, tp2, tp3, tp4, sl, kaldirac, atr, en_iyi_fiyat, asama, durum = islem
                        if s_id in islenen_idler_set: continue
                        
                        for mod in ["MOVING", "TRAILING", "BREAKEVEN"]:
                            kasa[mod]["bakiye"] = islem_simule_et(kasa[mod]["bakiye"], mod, yon, giris, tp1, tp2, tp3, tp4, sl, kaldirac, atr, en_iyi_fiyat, asama, durum)
                        
                        kasa["islenen_idler"].append(s_id)
                        yeni_islenen += 1

                    sim_msg = f"📊 **KSVİX SİMÜLASYON LABORATUVARI** 📊\n"
                    sim_msg += f"*(Sermaye: $200 | Risk: %0.5 | TP: %70-10-10-10)*\n\n"
                    sim_msg += f"⏳ **İçerideki Açık İşlem:** `{aktif_sinyal}`\n"
                    if yeni_islenen > 0: sim_msg += f"🔍 **Bugün Kapanıp Analiz Edilen:** `{yeni_islenen} İşlem`\n\n"
                    else: sim_msg += "\n"
                    
                    for mod in ["BREAKEVEN", "MOVING", "TRAILING"]:
                        guncel = kasa[mod]["bakiye"]
                        eski = kasa[mod]["dunku_bakiye"]
                        fark = guncel - eski
                        yuzde = (fark / eski) * 100 if eski > 0 else 0
                        icon = "🟢" if fark > 0 else "🔴" if fark < 0 else "⚪"
                        isaret = "+" if fark > 0 else ""
                        
                        sim_msg += f"🛡️ **{mod} Zırhı:**\n"
                        sim_msg += f"💵 Yeni Kasa: `${guncel:.2f}`\n"
                        sim_msg += f"{icon} Bugün: `{isaret}${fark:.2f}` (%{yuzde:.2f})\n\n"
                        
                        kasa[mod]["dunku_bakiye"] = guncel
                        
                    with open(dosya, 'w') as f: json.dump(kasa, f)
                    
                except Exception as e: 
                    print(f"Rapor/Simülasyon Hatası: {e}")
                    sim_msg, toplam_sinyal, aktif_sinyal = "", 0, 0
                finally: 
                    conn.close()

                vip_msg = (
                    f"{sim_msg}"
                    f"🧠 **KSVİX YAPAY ZEKA (AI) İSTİHBARAT MERKEZİ** 🧠\n"
                    f"📅 **Tarih:** {su_an.strftime('%d %B %Y')}\n\n"
                    f"🗃️ **Eğitim Havuzu:** `{toplam_sinyal} İşlem`\n"
                    f"⏳ **Radardaki İşlemler:** `{aktif_sinyal}`\n\n"
                    f"*(Otonom MTF, Pivot, VWAP ve Formasyon Lobları AKTİF!)* 🦅"
                )
                
                try: await client.send_message(VIP_KANAL_ID, vip_msg)
                except: pass

                await asyncio.sleep(70) 
        except: pass
        await asyncio.sleep(30)

async def main():
    print("KSVİX Otonom V12 Motorları Ateşleniyor...")
    db.init_db()
    await client.start(bot_token=config.BOT_TOKEN)
    print("🤖 KSVİX VIP Telegram'a Sızdı.")
    client.loop.create_task(fiyat_takip_radari())
    client.loop.create_task(golge_senkronizator())
    client.loop.create_task(gunluk_pnl_raporlayici())
    print("🦅 V8 Radarları, KSVİX Otonom Kelly Kriteri ve Çift VWAP Onayı Aktif...")
    await client.run_until_disconnected()

if __name__ == '__main__':
    loop.run_until_complete(main())
