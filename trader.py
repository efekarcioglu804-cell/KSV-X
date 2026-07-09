import ccxt.async_support as ccxt
import asyncio

# KRİTİK AYAR: Her VIP üyenin her işlemde kullanacağı sabit USDT (Ana Para) miktarı.
# Kaldıraç bu paranın üzerine etki edecektir. (Örn: 20$ * 20x Kaldıraç = 400$ Pozisyon Büyüklüğü)
ISLEM_BASINA_USDT = 20

async def islem_ac(api_key, api_secret, sinyal):
    """
    Çözümlenmiş sinyal verisini alır ve MEXC borsasında vadeli işlem pozisyonu açar.
    Asenkron olduğu için diğer kullanıcıları bekletmez.
    """
    # 1. Borsa Bağlantısı (Vadeli İşlemler - Swap için 'defaultType': 'swap' zorunludur)
    borsa = ccxt.mexc({
        'apiKey': api_key,
        'secret': api_secret,
        'enableRateLimit': True,
        'options': {
            'defaultType': 'swap'
        }
    })

    try:
        # CCXT Vadeli İşlemler Sembol Formatı (Örn: ROSEUSDT -> ROSE/USDT:USDT)
        sembol = sinyal['coin'].replace('USDT', '') + '/USDT:USDT'
        yon = 'buy' if sinyal['yon'] == 'LONG' else 'sell'
        
        # Piyasayı yüklüyoruz (Borsadaki coin'lerin minimum/maksimum alım kurallarını çeker)
        await borsa.load_markets()

        # 2. Kaldıraç ve Margin Tipini Ayarlama
        try:
            await borsa.set_leverage(sinyal['kaldirac'], sembol)
            await borsa.set_margin_mode(sinyal['margin_tipi'].lower(), sembol)
        except Exception as e:
            # Bazı borsalar zaten ayarlıysa uyarı verir, sistemi durdurmaması için pass geçiyoruz.
            pass

        # 3. Miktar Hesaplama
        # Toplam pozisyon büyüklüğü = Ana Para * Kaldıraç
        toplam_hacim_usdt = ISLEM_BASINA_USDT * sinyal['kaldirac']
        
        # Alınacak coin miktarı = Toplam Hacim / Giriş Fiyatı
        miktar = toplam_hacim_usdt / sinyal['giris']
        
        # Borsanın kabul edeceği ondalık sayıya yuvarlıyoruz (Örn: 10.5555 yerine 10.5)
        miktar = borsa.amount_to_precision(sembol, miktar)

        # 4. Ana Emri Gönderme (Giriş, TP ve SL)
        # MEXC V3 API'si Stop Loss ve Take Profit hedeflerini ana emirle birlikte alabilir.
        # İlk etapta sistemi güvende tutmak için TP listesindeki ilk hedefi (TP1) kullanıyoruz.
        params = {
            'stopLossPrice': sinyal['sl'],
            'takeProfitPrice': sinyal['tp_listesi'][0],
            'reduceOnly': False # Bu yeni bir pozisyon açılışıdır
        }
        
        # Sinyalde "%1 Limit Emir" dediğin için limit emri kullanıyoruz.
        emir = await borsa.create_order(
            symbol=sembol,
            type='limit',
            side=yon,
            amount=float(miktar),
            price=sinyal['giris'],
            params=params
        )

        # Başarılı olursa konsola kimlik numarasıyla döner
        return {"durum": "BASARILI", "emir_id": emir['id']}

    except Exception as e:
        return {"durum": "HATA", "hata_mesaji": str(e)}
        
    finally:
        # Geleneksel mühendislik kuralı: İşin bitince dükkanı kapat.
        # Borsa bağlantısını kapatmazsak RAM şişer, sunucu patlar.
        await borsa.close()
