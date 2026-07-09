import re

def parse_signal(message_text):
    """
    Gelen sinyal metnini analiz eder ve CCXT'nin anlayacağı saf formata çevirir.
    Eğer mesaj geçerli bir sinyal formatında değilse makineyi durdurmak için None döner.
    """
    # Büyük/küçük harf sorununu kökten çözüyoruz
    metin = message_text.upper()
    
    # 1. GÜVENLİK FİLTRESİ: Metinde LONG veya SHORT geçmiyorsa bu bir duyuru/sohbet mesajıdır.
    if "LONG" not in metin and "SHORT" not in metin:
        return None
        
    sonuc = {
        "coin": None, 
        "yon": None, 
        "giris": None, 
        "tp_listesi": [], 
        "sl": None, 
        "kaldirac": None,
        "margin_tipi": "CROSS" # Çoğu sinyal Cross olduğu için varsayılanı bu yaptık
    }
    
    # 2. Yön (LONG veya SHORT)
    if re.search(r'SHORT', metin):
        sonuc["yon"] = "SHORT"
    elif re.search(r'LONG', metin):
        sonuc["yon"] = "LONG"
        
    # 3. Coin Adı (#ROSEUSDT -> ROSEUSDT olarak cımbızlar)
    coin_match = re.search(r'#?([A-Z0-9]+USDT)', metin) 
    if coin_match: 
        sonuc["coin"] = coin_match.group(1)
        
    # 4. Giriş Seviyesi (Virgülleri noktaya çevirerek float veri tipine uygun hale getirir)
    giris_match = re.search(r'ENTRY:\s*([0-9.,]+)', metin)
    if giris_match: 
        sonuc["giris"] = float(giris_match.group(1).replace(',', '.'))
        
    # 5. Kademeli Hedefler (TP1, TP2, TP3... hepsini bir listeye toplar)
    tp_matches = re.findall(r'TP\d*:\s*([0-9.,]+)', metin)
    if tp_matches:
        sonuc["tp_listesi"] = [float(tp.replace(',', '.')) for tp in tp_matches]
        
    # 6. Stop Loss (SL)
    sl_match = re.search(r'STOP\s*LOSS:\s*([0-9.,]+)', metin)
    if sl_match: 
        sonuc["sl"] = float(sl_match.group(1).replace(',', '.'))

    # 7. Kaldıraç ve Margin Tipi
    kaldirac_match = re.search(r'LEVERAGE:\s*(CROSS|ISOLATED)?\s*([0-9]+)X?', metin)
    if kaldirac_match:
        if kaldirac_match.group(1):
            sonuc["margin_tipi"] = kaldirac_match.group(1)
        sonuc["kaldirac"] = int(kaldirac_match.group(2))

    # 2. GÜVENLİK FİLTRESİ: Eğer format bozuksa ve kritik verilerden biri eksikse, işlemi iptal et.
    # Eksik veriyle borsaya emir yollarsak API hata verir, sistemi kilitler.
    if not sonuc["coin"] or not sonuc["giris"] or not sonuc["sl"] or not sonuc["kaldirac"]:
        return None

    return sonuc

# Test Bloğu: Bu dosyayı terminalde tek başına çalıştırırsan (python parser.py) sistemi test edersin.
if __name__ == "__main__":
    ornek_sinyal = """
    🔴 HUNTER BEAR (PULLBACK SNIPER) 🔴
    #ROSEUSDT - SHORT (Satış)
    Leverage: Cross 20x
    ENTRY: 0.005808 (%1 Limit Emir)
    TARGETS:
    TP1: 0.005735 (25%)
    TP2: 0.005663 (50%)
    TP3: 0.005518 (100%)
    TP4: 0.005372 (150%)
    STOP LOSS: 0.006534 (250%)
    """
    
    print("Mekanizma Test Ediliyor...\n")
    test_sonucu = parse_signal(ornek_sinyal)
    
    if test_sonucu:
        print("✅ Sinyal Başarıyla Çözümlendi:")
        for anahtar, deger in test_sonucu.items():
            print(f" -> {anahtar.upper()}: {deger}")
    else:
        print("❌ HATA: Sinyal çözümlenemedi. (Eksik veri veya bozuk format)")
