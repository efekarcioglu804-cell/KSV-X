import matplotlib.pyplot as plt
import datetime
import os

def create_pnl_image(acilan, tps, stops, bes, kar, trade_mode):
    # 🎨 PREMİUM PİTCH-BLACK (SİMFİYAH) VIP TEMASI
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(10, 7.5), facecolor='#050505') # Saf siyah arkaplan
    ax.set_facecolor('#050505')
    
    # 📊 Veriler ve Etiketler
    labels = ['BAŞARILI\n(TP)', 'ZARAR\n(STOP)', 'ZARARSIZ\n(BE)']
    values = [tps, stops, bes]
    
    # 💥 NEON RENKLER (Siberpunk & Wall Street Karışımı)
    colors = ['#00FF87', '#FF003C', '#FFD700'] # Neon Yeşil, Kan Kırmızı, Saf Altın
    
    # 1. KATMAN: GLOW (Parlama) EFEKTİ (Arkaya hafif geniş ve saydam barlar çiziyoruz)
    ax.bar(labels, values, color=colors, width=0.65, alpha=0.15, edgecolor='none')
    
    # 2. KATMAN: ANA SÜTUNLAR (İnce, keskin ve beyaz çerçeveli)
    bars = ax.bar(labels, values, color=colors, width=0.45, edgecolor='#FFFFFF', linewidth=1.5, alpha=0.95)
    
    # 🏆 RAKAMLAR SÜTUNLARIN ÜSTÜNDE (Büyük ve Gösterişli)
    for bar in bars:
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height + (max(values)*0.03 if max(values) > 0 else 0.1),
                f'{int(height)}',
                ha='center', va='bottom', color='white', fontweight='heavy', fontsize=22)
    
    # 📏 ARKA PLAN ÇİZGİLERİ (Sadece hafif yatay çizgiler)
    ax.yaxis.grid(True, linestyle='--', alpha=0.1, color='#FFFFFF')
    ax.xaxis.grid(False)
    
    # Çirkin dış çerçeveyi tamamen sil
    for spine in ax.spines.values():
        spine.set_visible(False)
        
    ax.tick_params(colors='#A1A1AA', labelsize=14, length=0, pad=10) 
    
    # 👑 DEVASA FİLİGRAN (SU DAMGASI) Arka plana silik şekilde yazılacak
    fig.text(0.5, 0.45, '👑 KRALIN SİNYALLERİ VİP 👑', 
             fontsize=40, color='#FFD700', alpha=0.04, ha='center', va='center', rotation=12, fontweight='heavy')
    
    # 👑 BAŞLIKLAR VE HEYECAN YARATAN SLOGANLAR
    tarih = datetime.datetime.now().strftime('%d %B %Y')
    
    # Ana Başlık
    plt.suptitle('👑 KSVİX OTONOM BİLANÇO MERKEZİ 👑', color='#FFD700', fontweight='heavy', fontsize=24, y=0.95)
    
    # Alt Başlık ve VIP Sloganı
    slogan = f"Tarih: {tarih}   |   Toplam Operasyon: {acilan}\n⚔️ Duygusuz. Kusursuz. Kazançlı. ⚔️"
    plt.title(slogan, color='#D4D4D8', fontsize=14, pad=20, style='italic')
    
    # 💰 DEVASA NET KÂR KUTUSU (En altta parlayan bölüm)
    kar_metni = f"+{kar:.2f} USDT" if kar > 0 else f"{kar:.2f} USDT"
    if trade_mode != 'FIXED':
        kar_metni = f"% +{kar:.2f}" if kar > 0 else f"% {kar:.2f}"
        
    box_color = '#00FF87' if kar > 0 else '#FF003C' if kar < 0 else '#A1A1AA'
    box_text = f"💰 NET KASA BÜYÜMESİ: {kar_metni} 💰"
    
    bbox_props = dict(boxstyle="square,pad=0.9", facecolor='#0A0A0A', edgecolor=box_color, linewidth=2.5)
    plt.figtext(0.5, 0.06, box_text, ha="center", va="center", 
                fontsize=18, fontweight='heavy', color=box_color, bbox=bbox_props)
    
    # Düzeni sıkıştırıp hizala
    plt.tight_layout()
    plt.subplots_adjust(bottom=0.22, top=0.78) 
    
    # 🚀 YÜKSEK ÇÖZÜNÜRLÜKLÜ (300 DPI) KAYIT
    img_path = 'gunluk_bilanco.png'
    plt.savefig(img_path, dpi=300, facecolor=fig.get_facecolor(), edgecolor='none', bbox_inches='tight')
    plt.close()
    
    return img_path
