# Veri kaynakları ve izlenebilirlik

## Aktif kaynaklar

| Veri | Kaynak | Kullanım |
|---|---|---|
| Tarihsel spot mumlar | Binance Public Data | Aylık ZIP + SHA-256 checksum, değişmez ham arşiv |
| Güncel spot mumlar | Binance Market Data REST | Son 1.000 mumla periyodik mutabakat |
| Kapanmış saatlik mum | Binance WebSocket | Düşük gecikmeli incremental kayıt |
| ABD hisse/ETF günlük mumları | Twelve Data | API anahtarlı EOD shadow toplama ve readiness kontrolü |

Kripto evreni BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT, ADAUSDT, LINKUSDT ve
DOGEUSDT sembollerinden oluşur. ABD evreninde 20 yüksek likiditeli Nasdaq hissesi/ETF aynı shadow
yönetişim kurallarıyla izlenir. Güncel evren veritabanındaki `assets` tablosu ve API üzerinden
denetlenir; arayüz sahte veya sabit sayaç kullanmaz.

## Kalite kuralları

- Kaynak checksum'ı uyuşmayan dosya işlenmez.
- Aynı `(asset, open_time, interval, source)` kimliği iki kez eklenmez.
- Fiyatlar pozitif, `high >= max(open, close)` ve `low <= min(open, close)` olmalıdır.
- Hacim ve işlem sayısı negatif olamaz.
- Tüm zamanlar UTC'ye çevrilir; 2025 sonrası Binance arşiv mikrosaniyeleri ayrıca tanınır.
- Bir varlık 365 tamamlanmış günlük gözlem olmadan tahmin hattına girmez.
- ABD varlıklarında yalnızca tamamlanmış işlem günleri kabul edilir; hafta sonu ve tatiller takvim
  boşluğu olarak değerlendirilmez.

## Haber shadow hattı

Haberler v1 aktif modeline dahil değildir. GDELT/RSS entegrasyonu eklendiğinde yalnızca başlık, URL, kaynak, yayın zamanı, varlık eşleşmesi ve türetilmiş skorlar tutulacaktır. Tam metin yalnızca açık saklama izni olan kaynaklarda depolanabilir. Haber özelliği bağımsız walk-forward kapılarını geçmeden production modelini etkileyemez.

## V2 türev challenger hattı

| Veri | Kaynak | Özellik grubu |
|---|---|---|
| Perpetual funding | Binance USD-M aylık `fundingRate` | 7/30 günlük ortalama, 90 günlük z-skor |
| Premium/basis | Binance USD-M aylık `premiumIndexKlines` | 7/30 günlük ortalama, 90 günlük z-skor |
| Futures mumları | Binance USD-M aylık `klines` | quote-volume z-skoru, taker-buy oranı |
| Open interest ve oranlar | Binance USD-M günlük `metrics` | OI değişimi/z-skoru, long-short ve taker oranları |

Tüm tamamlanmış UTC günleri ancak ertesi gün 00:00 UTC'de erişilebilir kabul edilir. Arşiv ZIP'leri
SHA-256 checksum ile saklanır; günlük konsolide tablolar kaynak dosyalardan daha eskiyse otomatik
yeniden oluşturulur. USD-M arşivinde tarihsel liquidation snapshot bulunmadığı için Coin-M
liquidation verisi ana V2 grubuna karıştırılmaz; farklı sözleşme nominali nedeniyle ayrı challenger
olarak değerlendirilmelidir.

## Canlı türev shadow collector

Canlı toplama için günün veri kesim anı ile job başlama anı ayrıdır. Kesim her zaman `D 00:00 UTC`,
veri penceresi `[D-1 00:00, D 00:00)` ve ilk deneme `D 00:05 UTC`'dir. Collector 00:45'e kadar
beş dakikada bir idempotent biçimde yeniden denenir. Sabit bekleme tek başına hazır kabul edilmez:

- Binance sunucu saati buffer sınırını geçmiş ve yerel saat farkı en fazla 30 saniye olmalıdır.
- Futures ve premium serilerinde 24 kesintisiz saatlik, OI/long-short/taker serilerinde 288
  kesintisiz beş dakikalık kova bulunmalıdır.
- Her istek açık `startTime` ve `endTime=D 00:00-1 ms` ile yapılır; cutoff'a eşit veya daha yeni
  olay kabul edilmez.
- Funding noktaları aynı yarı-açık pencerede olmalı ve boş olmamalıdır.
- Tam olmayan gün yazılmaz. Retry penceresi sonunda eksik kalan varlık için
  `DERIVATIVE_CUTOFF_INCOMPLETE` kalite olayı açılır.

Her tamamlanmış snapshot `source_max_event_time`, `available_at`, ham nokta sayıları ve içerik
checksum'ıyla saklanır. Tahmin job'u 00:10–00:55 arasında tekrar çalışır, fakat sabit saate güvenmez:
hedef cutoff'a kadar son 90 türev günü eksiksiz ve kesintisiz değilse tahmin üretmez. Binance OI ve
oran REST uçları yalnızca son 30–31 günü sunduğu için collector verisi günlük kalıcılaştırılır;
geçmişin sonradan API'den eksiksiz yeniden kurulabileceği varsayılmaz.
