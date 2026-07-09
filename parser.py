import re

def parse_signal(message_text):
    metin = message_text.upper()
    if "LONG" not in metin and "SHORT" not in metin:
        return None
        
    sonuc = {
        "coin": None, "yon": None, "giris": None, 
        "tp_listesi": [], "sl": None, 
        "kaldirac": None, "margin_tipi": "CROSS"
    }
    
    if re.search(r'SHORT', metin): sonuc["yon"] = "SHORT"
    elif re.search(r'LONG', metin): sonuc["yon"] = "LONG"
        
    coin_match = re.search(r'#?([A-Z0-9]+USDT)', metin) 
    if coin_match: sonuc["coin"] = coin_match.group(1)
        
    giris_match = re.search(r'ENTRY:\s*([0-9.,]+)', metin)
    if giris_match: sonuc["giris"] = float(giris_match.group(1).replace(',', '.'))
        
    tp_matches = re.findall(r'TP\d*:\s*([0-9.,]+)', metin)
    if tp_matches: sonuc["tp_listesi"] = [float(tp.replace(',', '.')) for tp in tp_matches]
        
    sl_match = re.search(r'STOP\s*LOSS:\s*([0-9.,]+)', metin)
    if sl_match: sonuc["sl"] = float(sl_match.group(1).replace(',', '.'))

    kaldirac_match = re.search(r'LEVERAGE:\s*(CROSS|ISOLATED)?\s*([0-9]+)X?', metin)
    if kaldirac_match:
        if kaldirac_match.group(1): sonuc["margin_tipi"] = kaldirac_match.group(1)
        sonuc["kaldirac"] = int(kaldirac_match.group(2))

    if not sonuc["coin"] or not sonuc["giris"] or not sonuc["sl"] or not sonuc["kaldirac"]:
        return None

    return sonuc
