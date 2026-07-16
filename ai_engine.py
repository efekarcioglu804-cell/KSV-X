import os
import json
import sqlite3
import numpy as np
import pandas as pd
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3' # Gereksiz logları kapat
from tensorflow.keras.models import Sequential, load_model
from tensorflow.keras.layers import LSTM, Dense, Dropout
import database as db

MODEL_PATH = "ksvix_lstm_model.h5"

def yapay_zeka_egit(df):
    # LSTM için veriyi 3D şekle (Örnek Sayısı, Zaman Adımı, Özellikler) dönüştür
    X_list = []
    y_list = []
    
    for idx, row in df.iterrows():
        try:
            video_data = json.loads(row['mum_gecmisi'])
            if len(video_data) == 20: # 5 saatlik kusursuz video
                X_list.append(video_data)
                y_list.append(row['sonuc'])
        except:
            continue
            
    if len(X_list) < 30: return None # Eğitim için minimum veri
    
    X = np.array(X_list) # Şekil: (Örnek, 20, 5)
    y = np.array(y_list)
    
    model = Sequential([
        LSTM(64, return_sequences=True, input_shape=(20, 5)),
        Dropout(0.2),
        LSTM(32),
        Dropout(0.2),
        Dense(16, activation='relu'),
        Dense(1, activation='sigmoid') # Başarı oranı (0 ile 1 arası)
    ])
    
    model.compile(optimizer='adam', loss='binary_crossentropy', metrics=['accuracy'])
    model.fit(X, y, epochs=10, batch_size=8, verbose=0)
    model.save(MODEL_PATH)
    return model

def sinyali_analiz_et(rsi, macd, hacim, fear_greed, mum_video_json):
    conn = sqlite3.connect(db.DB_NAME, timeout=30)
    query = """
        SELECT mum_gecmisi, CASE WHEN asama >= 2 THEN 1 ELSE 0 END as sonuc
        FROM active_signals 
        WHERE (asama >= 2 OR durum = 'STOP_OLDU') AND mum_gecmisi != '[]'
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    if len(df) < 50:
        return len(df), 100.0 # Yeterli video tecrübesi yoksa güven tam
        
    if os.path.exists(MODEL_PATH) and len(df) % 10 != 0:
        # Modeli her işlemde baştan eğitmemek için hazır olanı kullan
        model = load_model(MODEL_PATH)
    else:
        # Her 10 yeni veride bir beyni yeniden çalıştırıp eğit
        model = yapay_zeka_egit(df)
        
    if model is None: return len(df), 100.0
    
    # Anlık Sinyali Analiz Et
    try:
        anlik_video = np.array(json.loads(mum_video_json))
        anlik_video = anlik_video.reshape(1, 20, 5) # (1 örnek, 20 mum, 5 özellik)
        
        # Geleceği tahmin et
        tahmin = model.predict(anlik_video, verbose=0)
        basari_ihtimali = round(float(tahmin[0][0]) * 100, 2)
        
        # Korku endeksi %20'nin altındaysa ve piyasa kan ağlıyorsa AI güvenini törpüle
        if fear_greed <= 20: basari_ihtimali *= 0.8 
        
        return len(df), basari_ihtimali
    except:
        return len(df), 100.0
