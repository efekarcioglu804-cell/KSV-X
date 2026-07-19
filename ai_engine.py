import os
import json
import sqlite3
import numpy as np
import pandas as pd
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3' # Gereksiz logları kapat
from tensorflow.keras.models import Model, load_model
from tensorflow.keras.layers import LSTM, Dense, Dropout, Input, concatenate
import database as db

MODEL_PATH = "ksvix_lstm_model.h5"

def yapay_zeka_egit(df):
    X_lstm_list = []
    X_feat_list = []
    y_list = []
    
    for idx, row in df.iterrows():
        try:
            video_data = json.loads(row['mum_gecmisi'])
            if len(video_data) == 20: 
                X_lstm_list.append(video_data)
                
                # Yeni Sol Lob: İndikatörleri ve Psikolojiyi al
                feat = [
                    float(row['rsi_degeri'] if pd.notnull(row['rsi_degeri']) else 50.0),
                    float(row['macd_degeri'] if pd.notnull(row['macd_degeri']) else 0.0),
                    float(row['hacim_degeri'] if pd.notnull(row['hacim_degeri']) else 0.0),
                    float(row['fear_greed'] if pd.notnull(row['fear_greed']) else 50.0)
                ]
                X_feat_list.append(feat)
                y_list.append(row['sonuc'])
        except:
            continue
            
    if len(X_lstm_list) < 30: return None # Eğitim için minimum veri
    
    X_lstm = np.array(X_lstm_list) # Şekil: (Örnek, 20, 5)
    X_feat = np.array(X_feat_list) # Şekil: (Örnek, 4)
    y = np.array(y_list)
    
    # 🧠 1. SAĞ LOB: ZAMAN SERİSİ (MUM VİDEOSU - GÖRSEL HAFIZA)
    input_lstm = Input(shape=(20, 5), name="mum_girisi")
    x1 = LSTM(64, return_sequences=True)(input_lstm)
    x1 = Dropout(0.2)(x1)
    x1 = LSTM(32)(x1)
    x1 = Dropout(0.2)(x1)
    
    # 🧠 2. SOL LOB: PSİKOLOJİ VE HACİM (ANLIK İNDİKATÖRLER)
    input_feat = Input(shape=(4,), name="indikator_girisi")
    x2 = Dense(16, activation='relu')(input_feat)
    
    # ⚡ CORTEX: İKİ LOBU BİRLEŞTİR (Multi-Input Fusion)
    birlesim = concatenate([x1, x2])
    
    # 🎯 KARAR MEKANİZMASI
    z = Dense(16, activation='relu')(birlesim)
    out = Dense(1, activation='sigmoid', name="karar_ciktisi")(z)
    
    model = Model(inputs=[input_lstm, input_feat], outputs=out)
    model.compile(optimizer='adam', loss='binary_crossentropy', metrics=['accuracy'])
    
    # Çift loblu modeli devasa veritabanınla eğit
    model.fit([X_lstm, X_feat], y, epochs=10, batch_size=8, verbose=0)
    model.save(MODEL_PATH)
    return model

def sinyali_analiz_et(rsi, macd, hacim, fear_greed, mum_video_json):
    conn = sqlite3.connect(db.DB_NAME, timeout=30)
    query = """
        SELECT mum_gecmisi, rsi_degeri, macd_degeri, hacim_degeri, fear_greed, 
        CASE WHEN asama >= 2 THEN 1 ELSE 0 END as sonuc
        FROM active_signals 
        WHERE (asama >= 2 OR durum = 'STOP_OLDU') AND mum_gecmisi != '[]'
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    if len(df) < 50:
        return len(df), 100.0 # Yeterli tecrübe yoksa onay ver
        
    # Model var mı kontrol et, varsa çift loblu mu diye test et
    model = None
    if os.path.exists(MODEL_PATH) and len(df) % 10 != 0:
        try:
            model = load_model(MODEL_PATH)
            # Eğer model eski tek loblu modelse kasıtlı olarak hata verdirtip yenisini eğittiriyoruz
            if len(model.inputs) != 2: raise ValueError("Eski tek loblu model tespit edildi!")
        except:
            model = yapay_zeka_egit(df)
    else:
        # Her 10 yeni veride bir beyni yeniden çalıştırıp eğit
        model = yapay_zeka_egit(df)
        
    if model is None: return len(df), 100.0
    
    # Anlık Sinyali Çift Gözle Analiz Et
    try:
        anlik_video = np.array(json.loads(mum_video_json))
        anlik_video = anlik_video.reshape(1, 20, 5) # (1 örnek, 20 mum, 5 özellik)
        
        anlik_feat = np.array([[float(rsi), float(macd), float(hacim), float(fear_greed)]])
        
        # Geleceği tahmin et (Çift Lob Ateşlemesi)
        tahmin = model.predict([anlik_video, anlik_feat], verbose=0)
        basari_ihtimali = round(float(tahmin[0][0]) * 100, 2)
        
        # Korku endeksi %20'nin altındaysa ve piyasa kan ağlıyorsa AI güvenini törpüle
        if fear_greed <= 20: basari_ihtimali *= 0.8 
        
        return len(df), basari_ihtimali
    except Exception as e:
        return len(df), 100.0
