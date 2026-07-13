import matplotlib.pyplot as plt
import numpy as np
import os

def create_pnl_image(acilan, tps, stops, bes, kar, trade_mode):
    # Wall Street Karanlık Teması
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(7, 5))
    fig.patch.set_facecolor('#121212')
    ax.set_facecolor('#121212')

    # Veriler
    labels = ['Başarılı (TP)', 'Zarar (STOP)', 'Zararsız (BE)']
    values = [tps, stops, bes]
    colors = ['#00e676', '#ff1744', '#ffea00'] # Yeşil, Kırmızı, Sarı

    bars = ax.bar(labels, values, color=colors, width=0.5, edgecolor='#333333', linewidth=1)

    # Başlıklar
    ax.set_title('KSVIX GÜNLÜK BİLANÇO GRAFİĞİ', color='#d4af37', fontsize=14, fontweight='bold', pad=20)
    ax.set_ylabel('İşlem Sayısı', color='#aaaaaa')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color('#555555')
    ax.spines['bottom'].set_color('#555555')

    # Barların Üzerine Rakamları Yazma
    for bar in bars:
        yval = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2, yval + 0.1, int(yval), ha='center', color='white', fontweight='bold', fontsize=12)

    # Net Kar / Zarar Metnini Alt Kısma Şık Bir Kutuyla Ekleme
    pnl_text = f"Net Kasa Değişimi: {kar:+.2f} USDT" if trade_mode == 'FIXED' else f"Net Kasa Büyümesi: % {kar:+.2f}"
    color_pnl = '#00e676' if kar > 0 else '#ff1744' if kar < 0 else '#ffffff'
    
    plt.figtext(0.5, 0.03, pnl_text, ha="center", fontsize=13, fontweight='bold', color=color_pnl, 
                bbox=dict(facecolor='#1e1e1e', edgecolor=color_pnl, boxstyle='round,pad=0.8', linewidth=2))

    plt.tight_layout()
    plt.subplots_adjust(bottom=0.2) # Kutunun sığması için alt boşluk
    
    filepath = 'daily_pnl.png'
    plt.savefig(filepath, dpi=200, facecolor=fig.get_facecolor(), edgecolor='none')
    plt.close()
    
    return filepath
