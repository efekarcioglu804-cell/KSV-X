import ccxt.async_support as ccxt
import asyncio
import database as db

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

async def islem_ac(api_key, api_secret, ayarlar, sinyal):
    borsa = ccxt.mexc({'apiKey': api_key, 'secret': api_secret, 'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    try:
        sembol = sinyal['coin'].replace('USDT', '') + '/USDT:USDT'
        yon = 'buy' if sinyal['yon'] == 'LONG' else 'sell'
        
        await borsa.load_markets()
        hayalet_enjektor(borsa, sembol, sinyal['coin'])
        
        market = borsa.market(sembol)
        
        acik_pozisyonlar = await borsa.fetch_positions()
        bekleyen_emirler = await borsa.fetch_open_orders()
        
        aktif_pozisyon_coinleri = set()
        for p in acik_pozisyonlar:
            if float(p.get('contracts', 0) or p.get('positionAmt', 0)) > 0:
                aktif_pozisyon_coinleri.add(p['symbol'])
                
        if sembol in aktif_pozisyon_coinleri:
            return {"durum": "IPTAL", "hata_mesaji": f"İçeride aktif {sinyal['coin']} işlemi var! Yeni sinyal reddedildi."}
            
        eski_pusu_var = any(e['symbol'] == sembol for e in bekleyen_emirler)
        if eski_pusu_var:
            await borsa.cancel_all_orders(sembol)
            await asyncio.sleep(0.5) 
            
        bekleyen_limit_coinleri = set()
        for e in bekleyen_emirler:
            if e['symbol'] != sembol and e['symbol'] not in aktif_pozisyon_coinleri:
                bekleyen_limit_coinleri.add(e['symbol'])
                
        aktif_islem_sayisi = len(aktif_pozisyon_coinleri) + len(bekleyen_limit_coinleri)
        
        if aktif_islem_sayisi >= ayarlar['max_trades']:
            return {"durum": "IPTAL", "hata_mesaji": f"Maksimum sınır aşıldı ({ayarlar['max_trades']})"}

        try:
            await borsa.set_leverage(sinyal['kaldirac'], sembol)
            await borsa.set_margin_mode(sinyal['margin_tipi'].lower(), sembol)
        except: pass

        bakiye = await borsa.fetch_balance({'type': 'swap'})
        wallet_balance = float(bakiye.get('free', {}).get('USDT', bakiye['total'].get('USDT', 0)))
        if wallet_balance < 2: return {"durum": "HATA", "hata_mesaji": "Bakiye Çok Düşük"}

        kullanilacak_usdt = ayarlar['trade_amount'] if ayarlar['trade_mode'] == 'FIXED' else wallet_balance * (ayarlar['trade_amount'] / 100.0)
        toplam_hacim_usdt = kullanilacak_usdt * sinyal['kaldirac']
        
        contract_size = market.get('contractSize', 1)
        if contract_size is None: contract_size = 1
        
        hedef_coin_miktari = toplam_hacim_usdt / sinyal['giris']
        kontrat_miktari = hedef_coin_miktari / contract_size
        
        miktar = borsa.amount_to_precision(sembol, kontrat_miktari)
        fiyat_hassas = float(borsa.price_to_precision(sembol, sinyal['giris']))
        sl_hassas = float(borsa.price_to_precision(sembol, sinyal['sl']))

        params = {'stopLossPrice': sl_hassas, 'reduceOnly': False}
        emir = await borsa.create_order(symbol=sembol, type='limit', side=yon, amount=float(miktar), price=fiyat_hassas, params=params)
        
        return {"durum": "BASARILI", "emir_id": emir['id'], "eski_silindi": eski_pusu_var}

    except Exception as e:
        return {"durum": "HATA", "hata_mesaji": str(e)}
    finally:
        try: await borsa.close()
        except: pass

async def bekleyen_emri_iptal_et(api_key, api_secret, coin):
    borsa = ccxt.mexc({'apiKey': api_key, 'secret': api_secret, 'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    try:
        sembol = coin.replace('USDT', '') + '/USDT:USDT'
        await borsa.load_markets()
        hayalet_enjektor(borsa, sembol, coin)
        await borsa.cancel_all_orders(sembol)
    except: pass
    finally: 
        try: await borsa.close()
        except: pass

async def acil_kapat(api_key, api_secret, coin, yon):
    borsa = ccxt.mexc({'apiKey': api_key, 'secret': api_secret, 'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    try:
        sembol = coin.replace('USDT', '') + '/USDT:USDT'
        await borsa.load_markets()
        hayalet_enjektor(borsa, sembol, coin)
        
        ters_yon = 'sell' if yon == 'LONG' else 'buy'
        
        for deneme in range(3):
            pozisyonlar = await borsa.fetch_positions([sembol])
            if not pozisyonlar: break
                
            poz = pozisyonlar[0]
            miktar = abs(float(poz.get('contracts', 0) or poz.get('positionAmt', 0)))
            
            if miktar <= 0: break 
                
            try:
                await borsa.create_order(sembol, 'market', ters_yon, int(miktar), params={'reduceOnly': True})
                break
            except:
                await asyncio.sleep(1.5)
        
        await borsa.cancel_all_orders(sembol)
    except: pass
    finally: 
        try: await borsa.close()
        except: pass

async def pozisyon_guncelle(api_key, api_secret, coin, yon, asama, tp_ratios, stop_mode, fiyatlar):
    borsa = ccxt.mexc({'apiKey': api_key, 'secret': api_secret, 'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    try:
        sembol = coin.replace('USDT', '') + '/USDT:USDT'
        await borsa.load_markets()
        hayalet_enjektor(borsa, sembol, coin)
        
        oranlar = [float(x) for x in tp_ratios.split(',')]
        hedef_oran = oranlar[asama - 2]
        
        ters_yon = 'sell' if yon == 'LONG' else 'buy'
        onceki_satilan_toplam = sum(oranlar[:asama-2]) if asama > 2 else 0
        kalan_yuzde = 100.0 - onceki_satilan_toplam
        
        if asama == 5 or kalan_yuzde <= 0 or (hedef_oran / kalan_yuzde) >= 0.99: 
            gercek_satis_orani = 1.0 
        else: 
            gercek_satis_orani = hedef_oran / kalan_yuzde

        for deneme in range(3):
            pozisyonlar = await borsa.fetch_positions([sembol])
            if not pozisyonlar: break
                
            poz = pozisyonlar[0]
            toplam_miktar = abs(float(poz.get('contracts', 0) or poz.get('positionAmt', 0)))
            if toplam_miktar <= 0: break
            
            kapatilacak_miktar_ham = toplam_miktar * gercek_satis_orani
            kapatilacak_miktar = int(kapatilacak_miktar_ham)
            if kapatilacak_miktar < 1 and toplam_miktar >= 1: kapatilacak_miktar = 1
            
            if kapatilacak_miktar > 0:
                try:
                    await borsa.create_order(sembol, 'market', ters_yon, kapatilacak_miktar, params={'reduceOnly': True})
                    break
                except Exception as e: 
                    await asyncio.sleep(1)
            else: break

        await asyncio.sleep(1)
        
        guncel_pozisyonlar = await borsa.fetch_positions([sembol])
        if not guncel_pozisyonlar: return
        
        kalan_gercek_miktar = abs(float(guncel_pozisyonlar[0].get('contracts', 0) or guncel_pozisyonlar[0].get('positionAmt', 0)))

        if stop_mode != 'NONE' and kalan_gercek_miktar > 0:
            yeni_sl = None
            if stop_mode == 'BREAKEVEN' and asama >= 2: yeni_sl = fiyatlar['giris']
            elif stop_mode == 'MOVING':
                if asama == 2: yeni_sl = fiyatlar['giris']
                elif asama == 3: yeni_sl = fiyatlar['tp1']
                elif asama == 4: yeni_sl = fiyatlar['tp2']
                elif asama == 5: yeni_sl = fiyatlar['tp3']

            if yeni_sl:
                yeni_sl_hassas = float(borsa.price_to_precision(sembol, yeni_sl))
                try:
                    await borsa.cancel_all_orders(sembol)
                    await borsa.create_order(
                        symbol=sembol, 
                        type='market', 
                        side=ters_yon, 
                        amount=int(kalan_gercek_miktar), 
                        params={'triggerPrice': yeni_sl_hassas, 'reduceOnly': True}
                    )
                except: pass

    except: pass
    finally: 
        try: await borsa.close()
        except: pass
