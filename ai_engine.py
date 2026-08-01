import os
import json
import sqlite3
import numpy as np
import pandas as pd
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
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
                arr = np.array(video_data, dtype=float)
                
                max_price = np.max(arr[:, 3]) if np.max(arr[:, 3]) > 0 else 1.0
                arr[:, 0:4] = arr[:, 0:4] / max_price
                
                max_vol = np.max(arr[:, 4]) if np.max(arr[:, 4]) > 0 else 1.0
                arr[:, 4] = arr[:, 4] / max_vol
                
                X_lstm_list.append(arr)
                
                r = float(row['rsi_degeri']) if pd.notnull(row['rsi_degeri']) else 50.0
                m = float(row['macd_degeri']) if pd.notnull(row['macd_degeri']) else 0.0
                h = float(row['hacim_degeri']) if pd.notnull(row['hacim_degeri']) else 0.0
                f = float(row['fear_greed']) if pd.notnull(row['fear_greed']) else 50.0
                y_num = 1.0 if row['yon'] == 'LONG' else 0.0
                v_mesafe = float(row['vwap_mesafe']) if pd.notnull(row['vwap_mesafe']) else 0.0
                
                # 👑 YENİ LOBLARIN VERİLERİ (Hafıza Çağrısı)
                t_4h = float(row['trend_4h']) if pd.notnull(row['trend_4h']) else 0.5
                d_m = float(row['direnc_mesafe']) if pd.notnull(row['direnc_mesafe']) else 0.0
                ds_m = float(row['destek_mesafe']) if pd.notnull(row['destek_mesafe']) else 0.0
                s_o = float(row['sikisma_orani']) if pd.notnull(row['sikisma_orani']) else 0.0
                
                feat = [
                    y_num,                  
                    r / 100.0,              
                    np.tanh(m),             
                    np.log1p(h) / 20.0,     
                    f / 100.0,              
                    np.tanh(v_mesafe / 5.0),
                    t_4h,                   # Makro Trend (1=Boğa, 0=Ayı)
                    np.tanh(d_m / 5.0),     # Direnç Mesafesi (Filtrelenmiş)
                    np.tanh(ds_m / 5.0),    # Destek Mesafesi (Filtrelenmiş)
                    np.tanh(s_o)            # Sıkışma / Formasyon Şiddeti
                ]
                X_feat_list.append(feat)
                y_list.append(row['sonuc'])
        except:
            continue
            
    if len(X_lstm_list) < 30: return None
    
    X_lstm = np.array(X_lstm_list)
    X_feat = np.array(X_feat_list)
    y = np.array(y_list)
    
    input_lstm = Input(shape=(20, 5), name="mum_girisi")
    x1 = LSTM(128, return_sequences=True)(input_lstm)
    x1 = Dropout(0.3)(x1) 
    x1 = LSTM(64)(x1)
    x1 = Dropout(0.3)(x1)
    
    # İndikatör Girişi: 10 Parametreye Çıktı!
    input_feat = Input(shape=(10,), name="indikator_girisi")
    x2 = Dense(32, activation='relu')(input_feat)
    
    birlesim = concatenate([x1, x2])
    
    z = Dense(64, activation='relu')(birlesim)
    z = Dropout(0.2)(z)
    z = Dense(32, activation='relu')(z)
    
    out = Dense(1, activation='sigmoid', name="karar_ciktisi")(z)
    
    model = Model(inputs=[input_lstm, input_feat], outputs=out)
    model.compile(optimizer='adam', loss='binary_crossentropy', metrics=['accuracy'])
    
    model.fit([X_lstm, X_feat], y, epochs=25, batch_size=8, verbose=0)
    model.save(MODEL_PATH)
    return model

def sinyali_analiz_et(yon, rsi, macd, hacim, fear_greed, vwap_mesafe, trend_4h, direnc_mesafe, destek_mesafe, sikisma_orani, mum_video_json):
    conn = sqlite3.connect(db.DB_NAME, timeout=30)
    query = """
        SELECT yon, mum_gecmisi, rsi_degeri, macd_degeri, hacim_degeri, fear_greed, vwap_mesafe, trend_4h, direnc_mesafe, destek_mesafe, sikisma_orani,
        CASE WHEN asama >= 2 THEN 1 ELSE 0 END as sonuc
        FROM active_signals 
        WHERE (asama >= 2 OR durum = 'STOP_OLDU') AND mum_gecmisi != '[]'
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    if len(df) < 50:
        return len(df), 50.0
        
    model = None
    if os.path.exists(MODEL_PATH) and len(df) % 10 != 0:
        try:
            model = load_model(MODEL_PATH)
            # Modelin girişi 10 oldu, eskisi varsa reddet ve yeniden eğit
            if model.input_shape[1][1] != 10: raise ValueError("Eski model")
        except:
            model = yapay_zeka_egit(df)
    else:
        model = yapay_zeka_egit(df)
        
    if model is None: return len(df), 50.0
    
    try:
        arr = np.array(json.loads(mum_video_json), dtype=float)
        if arr.size == 0 or arr.shape[0] != 20: return len(df), 50.0 
        
        max_price = np.max(arr[:, 3]) if np.max(arr[:, 3]) > 0 else 1.0
        arr[:, 0:4] = arr[:, 0:4] / max_price
        
        max_vol = np.max(arr[:, 4]) if np.max(arr[:, 4]) > 0 else 1.0
        arr[:, 4] = arr[:, 4] / max_vol

        anlik_video = arr.reshape(1, 20, 5)
        y_num = 1.0 if yon == 'LONG' else 0.0
        
        anlik_feat = np.array([[
            y_num,
            float(rsi) / 100.0, 
            np.tanh(float(macd)), 
            np.log1p(float(hacim)) / 20.0, 
            float(fear_greed) / 100.0,
            np.tanh(float(vwap_mesafe) / 5.0),
            float(trend_4h),
            np.tanh(float(direnc_mesafe) / 5.0),
            np.tanh(float(destek_mesafe) / 5.0),
            np.tanh(float(sikisma_orani))
        ]])
        
        tahmin = model.predict([anlik_video, anlik_feat], verbose=0)
        basari_ihtimali = round(float(tahmin[0][0]) * 100, 2)
        if fear_greed <= 20: basari_ihtimali *= 0.8 
        return len(df), basari_ihtimali
    except Exception as e:
        print(f"🛑 AI Tahmin Hatası: {e}")
        return len(df), 50.0
