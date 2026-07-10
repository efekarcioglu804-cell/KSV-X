import ccxt.async_support as ccxt
import database as db

async def islem_ac(api_key, api_secret, ayarlar, sinyal):
    borsa = ccxt.mexc({
        'apiKey': api_key,
        'secret': api_secret,
        'enableRateLimit': True,
        'options': {'defaultType': 'swap'}
    })

    try:
        sembol = sinyal['coin'].replace('USDT', '') + '/USDT:USDT'
        yon = 'buy' if sinyal['yon'] == 'LONG' else 'sell'
        await borsa.load_markets()

        # 1. MAKSİMUM İŞLEM SINIRI KONTROLÜ
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

        # KALDIRAÇ VE MARJİN TİPİ AYARLAMA
        try:
            await borsa.set_leverage(sinyal['kaldirac'], sembol)
            await borsa.set_margin_mode(sinyal['margin_tipi'].lower(), sembol)
        except:
            pass

        # 2. CÜZDAN BAKİYESİ VE MOD HESAPLAMA
        bakiye = await borsa.fetch_balance()
        wallet_balance = float(bakiye['total'].get('USDT', 0))
        
        if wallet_balance < 2:
            return {"durum": "HATA", "hata_mesaji": "Bakiye Çok Düşük"}

        if ayarlar['trade_mode'] == 'FIXED':
            kullanilacak_usdt = ayarlar['trade_amount']
        else:
            kullanilacak_usdt = wallet_balance * (ayarlar['trade_amount'] / 100.0)
        
        toplam_hacim_usdt = kullanilacak_usdt * sinyal['kaldirac']
        miktar = toplam_hacim_usdt / sinyal['giris']
        miktar = borsa.amount_to_precision(sembol, miktar)

        # 3. EMRİ BORSAYA GÖNDERME (Limit Emir ve TP1/SL)
        params = {
            'stopLossPrice': sinyal['sl'],
            'takeProfitPrice': sinyal['tp1'],
            'reduceOnly': False
        }
        
        emir = await borsa.create_order(
            symbol=sembol, type='limit', side=yon,
            amount=float(miktar), price=sinyal['giris'], params=params
        )
        return {"durum": "BASARILI", "emir_id": emir['id']}

    except Exception as e:
        return {"durum": "HATA", "hata_mesaji": str(e)}
        
    finally:
        await borsa.close()
