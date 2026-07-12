import ccxt.async_support as ccxt
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
            'precision': {'amount': 1.0, 'price': 0.0001}
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
            
        # 🛡️ PİRAMİTLEME KORUMASI: Aynı coine iki kere girip ortalamayı bozmasını engeller
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
        await borsa.load_markets()
        hayalet_enjektor(borsa, sembol, coin)
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
        
        # 🧠 KRALIN MATEMATİĞİ (Zeno'nun Paradoksu Çözümü)
        onceki_satilan_toplam = sum(oranlar[:asama-2]) if asama > 2 else 0
        kalan_yuzde = 100.0 - onceki_satilan_toplam
        
        # Eğer son aşamadaysa (TP4) veya satılacak miktar kalanın %99'una denk geliyorsa masayı tamamen temizle!
        if asama == 5 or kalan_yuzde <= 0 or (hedef_oran / kalan_yuzde) >= 0.99:
            gercek_satis_orani = 1.0 
        else:
            gercek_satis_orani = hedef_oran / kalan_yuzde
            
        kapatilacak_miktar = float(borsa.amount_to_precision(sembol, toplam_miktar * gercek_satis_orani))
        
        if kapatilacak_miktar > 0:
            await borsa.create_order(sembol, 'market', ters_yon, kapatilacak_miktar, params={'reduceOnly': True})

        kalan_miktar = toplam_miktar - kapatilacak_miktar

        if stop_mode != 'NONE' and kalan_miktar > 0:
            yeni_sl = None
            if stop_mode == 'BREAKEVEN' and asama >= 2:
                yeni_sl = fiyatlar['giris']
            elif stop_mode == 'MOVING':
                if asama == 2: yeni_sl = fiyatlar['giris']
                elif asama == 3: yeni_sl = fiyatlar['tp1']
                elif asama == 4: yeni_sl = fiyatlar['tp2']
                elif asama == 5: yeni_sl = fiyatlar['tp3']

            if yeni_sl:
                await borsa.cancel_all_orders(sembol)
                await borsa.create_order(
                    symbol=sembol, 
                    type='market', 
                    side=ters_yon, 
                    amount=float(borsa.amount_to_precision(sembol, kalan_miktar)), 
                    params={'triggerPrice': yeni_sl, 'reduceOnly': True}
                )

    except Exception as e:
        print(f"Hata (Kısmi Kar/Stop Güncelleme): {e}")
    finally:
        await borsa.close()
