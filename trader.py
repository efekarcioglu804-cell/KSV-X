import ccxt.async_support as ccxt
import asyncio
import database as db

def hayalet_enjektor(borsa, sembol, coin_adi):
    if borsa.markets is not None and sembol not in borsa.markets:
        base = coin_adi.replace('USDT', '')
        print(f"💉 {coin_adi} için Hayalet Enjektör Devrede! Borsaya zorla tanıtılıyor...")
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
            # 👑 KRALIN TESPİTİYLE DÜZELTİLEN YER: Virgülden sonra 8 basamağa (1e-8) çıkarıldı!
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
        
        aktif_coinler = set()
        for p in acik_pozisyonlar:
            if float(p.get('contracts', 0) or p.get('positionAmt', 0)) > 0:
                aktif_coinler.add(p['symbol'])
        for e in bekleyen_emirler:
            aktif_coinler.add(e['symbol'])
            
        if sembol in aktif_coinler:
            return {"durum": "IPTAL", "hata_mesaji": f"Pusuda zaten {sinyal['coin']} var! Çifte işlem reddedildi."}
            
        if len(aktif_coinler) >= ayarlar['max_trades']:
            return {"durum": "IPTAL", "hata_mesaji": f"Maksimum sınır aşıldı ({ayarlar['max_trades']})"}

        try:
            await borsa.set_leverage(sinyal['kaldirac'], sembol)
            await borsa.set_margin_mode(sinyal['margin_tipi'].lower(), sembol)
        except:
            pass

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
        return {"durum": "BASARILI", "emir_id": emir['id']}

    except Exception as e:
        return {"durum": "HATA", "hata_mesaji": str(e)}
    finally:
        await borsa.close()

async def bekleyen_emri_iptal_et(api_key, api_secret, coin):
    borsa = ccxt.mexc({'apiKey': api_key, 'secret': api_secret, 'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    try:
        sembol = coin.replace('USDT', '') + '/USDT:USDT'
        await borsa.load_markets()
        hayalet_enjektor(borsa, sembol, coin)
        await borsa.cancel_all_orders(sembol)
    except:
        pass
    finally:
        await borsa.close()

async def acil_kapat(api_key, api_secret, coin, yon):
    borsa = ccxt.mexc({'apiKey': api_key, 'secret': api_secret, 'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    try:
        sembol = coin.replace('USDT', '') + '/USDT:USDT'
        await borsa.load_markets()
        hayalet_enjektor(borsa, sembol, coin)
        
        pozisyonlar = await borsa.fetch_positions([sembol])
        if pozisyonlar:
            poz = pozisyonlar[0]
            miktar = float(poz.get('contracts', 0) or poz.get('positionAmt', 0))
            if miktar > 0:
                ters_yon = 'sell' if yon == 'LONG' else 'buy'
                await borsa.create_order(sembol, 'market', ters_yon, miktar, params={'reduceOnly': True})
        
        await borsa.cancel_all_orders(sembol)
    except:
        pass
    finally:
        await borsa.close()

async def pozisyon_guncelle(api_key, api_secret, coin, yon, asama, tp_ratios, stop_mode, fiyatlar):
    borsa = ccxt.mexc({'apiKey': api_key, 'secret': api_secret, 'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    try:
        sembol = coin.replace('USDT', '') + '/USDT:USDT'
        await borsa.load_markets()
        hayalet_enjektor(borsa, sembol, coin)
        
        oranlar = [float(x) for x in tp_ratios.split(',')]
        hedef_oran = oranlar[asama - 2]
        
        pozisyonlar = await borsa.fetch_positions([sembol])
        if not pozisyonlar: return
            
        poz = pozisyonlar[0]
        toplam_miktar = float(poz.get('contracts', 0) or poz.get('positionAmt', 0))
        if toplam_miktar <= 0: return

        ters_yon = 'sell' if yon == 'LONG' else 'buy'
        
        onceki_satilan_toplam = sum(oranlar[:asama-2]) if asama > 2 else 0
        kalan_yuzde = 100.0 - onceki_satilan_toplam
        
        if asama == 5 or kalan_yuzde <= 0 or (hedef_oran / kalan_yuzde) >= 0.99:
            gercek_satis_orani = 1.0 
        else:
            gercek_satis_orani = hedef_oran / kalan_yuzde
            
        kapatilacak_miktar = float(borsa.amount_to_precision(sembol, toplam_miktar * gercek_satis_orani))
        
        if kapatilacak_miktar > 0:
            await borsa.create_order(sembol, 'market', ters_yon, kapatilacak_miktar, params={'reduceOnly': True})

        await asyncio.sleep(1)
        guncel_pozisyonlar = await borsa.fetch_positions([sembol])
        if not guncel_pozisyonlar: return
        
        kalan_gercek_miktar = float(guncel_pozisyonlar[0].get('contracts', 0) or guncel_pozisyonlar[0].get('positionAmt', 0))

        if stop_mode != 'NONE' and kalan_gercek_miktar > 0:
            yeni_sl = None
            if stop_mode == 'BREAKEVEN' and asama >= 2:
                yeni_sl = fiyatlar['giris']
            elif stop_mode == 'MOVING':
                if asama == 2: yeni_sl = fiyatlar['giris']
                elif asama == 3: yeni_sl = fiyatlar['tp1']
                elif asama == 4: yeni_sl = fiyatlar['tp2']
                elif asama == 5: yeni_sl = fiyatlar['tp3']

            if yeni_sl:
                yeni_sl_hassas = float(borsa.price_to_precision(sembol, yeni_sl))
                
                await borsa.cancel_all_orders(sembol)
                await borsa.create_order(
                    symbol=sembol, 
                    type='market', 
                    side=ters_yon, 
                    amount=float(borsa.amount_to_precision(sembol, kalan_gercek_miktar)), 
                    params={'triggerPrice': yeni_sl_hassas, 'reduceOnly': True}
                )

    except Exception as e:
        print(f"Hata (Kısmi Kar/Stop Güncelleme): {e}")
    finally:
        await borsa.close()
