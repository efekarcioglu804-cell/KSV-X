import ccxt.async_support as ccxt
import database as db

async def islem_ac(api_key, api_secret, ayarlar, sinyal):
    borsa = ccxt.mexc({'apiKey': api_key, 'secret': api_secret, 'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    try:
        sembol = sinyal['coin'].replace('USDT', '') + '/USDT:USDT'
        yon = 'buy' if sinyal['yon'] == 'LONG' else 'sell'
        await borsa.load_markets()

        # --- GÜVENLİK KAPISI: MİNİMUM LİMİT KONTROLÜ (FİLTRE KALDIRILDI) ---
        market = borsa.market(sembol)
        # Hata vermesin diye None değerlerini 0 yaptık
        min_amount = market['limits']['amount']['min'] if market['limits']['amount']['min'] is not None else 0
        
        # Sınırı 0 yaparak botun her işleme denemesini sağladık
        min_cost = 0
        
        acik_pozisyonlar = await borsa.fetch_positions()
        bekleyen_emirler = await borsa.fetch_open_orders()
        
        aktif_coinler = set()
        for p in acik_pozisyonlar:
            if float(p.get('contracts', 0) or p.get('positionAmt', 0)) > 0:
                aktif_coinler.add(p['symbol'])
        for e in bekleyen_emirler:
            aktif_coinler.add(e['symbol'])
            
        if len(aktif_coinler) >= ayarlar['max_trades']:
            return {"durum": "IPTAL", "hata_mesaji": f"Maksimum sınır aşıldı ({ayarlar['max_trades']})"}

        try:
            await borsa.set_leverage(sinyal['kaldirac'], sembol)
            await borsa.set_margin_mode(sinyal['margin_tipi'].lower(), sembol)
        except:
            pass

        bakiye = await borsa.fetch_balance()
        wallet_balance = float(bakiye['total'].get('USDT', 0))
        if wallet_balance < 2: return {"durum": "HATA", "hata_mesaji": "Bakiye Çok Düşük"}

        kullanilacak_usdt = ayarlar['trade_amount'] if ayarlar['trade_mode'] == 'FIXED' else wallet_balance * (ayarlar['trade_amount'] / 100.0)
        toplam_hacim_usdt = kullanilacak_usdt * sinyal['kaldirac']
        
        miktar = borsa.amount_to_precision(sembol, toplam_hacim_usdt / sinyal['giris'])

        # Başlangıçta sadece SL kuruyoruz, TP'leri radar manuel kapatacak
        params = {'stopLossPrice': sinyal['sl'], 'reduceOnly': False}
        emir = await borsa.create_order(symbol=sembol, type='limit', side=yon, amount=float(miktar), price=sinyal['giris'], params=params)
        return {"durum": "BASARILI", "emir_id": emir['id']}

    except Exception as e:
        return {"durum": "HATA", "hata_mesaji": str(e)}
    finally:
        await borsa.close()

async def bekleyen_emri_iptal_et(api_key, api_secret, coin):
    borsa = ccxt.mexc({'apiKey': api_key, 'secret': api_secret, 'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    try:
        sembol = coin.replace('USDT', '') + '/USDT:USDT'
        await borsa.cancel_all_orders(sembol)
    except Exception as e:
        pass
    finally:
        await borsa.close()

async def pozisyon_guncelle(api_key, api_secret, coin, yon, asama, tp_ratios, stop_mode, fiyatlar):
    borsa = ccxt.mexc({'apiKey': api_key, 'secret': api_secret, 'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    try:
        sembol = coin.replace('USDT', '') + '/USDT:USDT'
        oranlar = [float(x) for x in tp_ratios.split(',')]
        su_anki_hedef_oran = oranlar[asama - 2] # asama 2 = TP1
        
        pozisyonlar = await borsa.fetch_positions([sembol])
        if not pozisyonlar: return
            
        poz = pozisyonlar[0]
        toplam_miktar = float(poz.get('contracts', 0) or poz.get('positionAmt', 0))
        ters_yon = 'sell' if yon == 'LONG' else 'buy'
        
        # 1. KISMİ KÂR ALMA
        if toplam_miktar > 0 and su_anki_hedef_oran > 0:
            kapatilacak_miktar = borsa.amount_to_precision(sembol, toplam_miktar * (su_anki_hedef_oran / 100))
            await borsa.create_order(sembol, 'market', ters_yon, kapatilacak_miktar, params={'reduceOnly': True})
            print(f"💸 {coin} için %{su_anki_hedef_oran} kâr satışı yapıldı.")

        # 2. STOP-LOSS TAŞIMA
        if stop_mode != 'NONE':
            yeni_sl = None
            if stop_mode == 'BREAKEVEN' and asama >= 2:
                yeni_sl = fiyatlar['giris']
            elif stop_mode == 'MOVING':
                if asama == 2: yeni_sl = fiyatlar['giris']
                elif asama == 3: yeni_sl = fiyatlar['tp1']
                elif asama == 4: yeni_sl = fiyatlar['tp2']
                elif asama == 5: yeni_sl = fiyatlar['tp3']

            if yeni_sl:
                await borsa.cancel_all_orders(sembol) # Eski stopu siler
                await borsa.create_order(sembol, 'limit', ters_yon, toplam_miktar, yeni_sl, params={'stopLossPrice': yeni_sl, 'reduceOnly': True})
                print(f"🛡️ {coin} Stop Loss güncellendi: {yeni_sl} ({stop_mode})")

    except Exception as e:
        print(f"Hata (Kısmi Kar/Stop): {e}")
    finally:
        await borsa.close()
