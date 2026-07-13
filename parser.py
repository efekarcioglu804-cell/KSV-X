import re

def parse_signal(message_text):
    metin = message_text.upper()
    if "LONG" not in metin and "SHORT" not in metin:
        return None
        
    sonuc = {
        "coin": None, "yon": None, "giris": None, 
        "tp1": 0, "tp2": 0, "tp3": 0, "tp4": 0, "sl": None, 
        "kaldirac": 20, "margin_tipi": "CROSS"
    }
    
    # YÖN VE COİN
    if re.search(r'SHORT', metin): sonuc["yon"] = "SHORT"
    elif re.search(r'LONG', metin): sonuc["yon"] = "LONG"
    
    coin_match = re.search(r'#?([A-Z0-9]+)/?USDT', metin) 
    if coin_match: sonuc["coin"] = coin_match.group(1) + "USDT"
        
    # 👑 KRALIN EMRİ: ESNEME PAYI İPTAL!
    # GİRİŞ: Rakamı alır ve Cornix gibi hiçbir ekleme/çıkarma yapmadan dümdüz iletir.
    giris_match = re.search(r'ENTRY[:\s]+([0-9.,]+)', metin)
    if giris_match: 
        sonuc["giris"] = float(giris_match.group(1).replace(',', '.'))
            
    # TP
    for i in range(1, 5):
        tp_match = re.search(rf'TP{i}[:\s]+([0-9.,]+)', metin)
        if tp_match: sonuc[f"tp{i}"] = float(tp_match.group(1).replace(',', '.'))
        
    # STOP LOSS
    sl_match = re.search(r'STOP\s*LOSS[:\s]+([0-9.,]+)', metin)
    if sl_match: sonuc["sl"] = float(sl_match.group(1).replace(',', '.'))

    # KALDIRAÇ
    kaldirac_match = re.search(r'LEVERAGE[:\s]+(CROSS|ISOLATED)?\s*([0-9]+)X?', metin)
    if kaldirac_match:
        if kaldirac_match.group(1): sonuc["margin_tipi"] = kaldirac_match.group(1)
        sonuc["kaldirac"] = int(kaldirac_match.group(2))

    if not sonuc["coin"] or not sonuc["giris"] or not sonuc["sl"]:
        return None

    return sonuc
