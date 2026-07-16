# ABD Hisseleri Shadow Tasarımı

## Kapsam

İlk aşamada sabit ve likit 20 sembollük pilot evren kullanılır:

- Piyasa/segment ETF'leri: SPY, QQQ, IWM, DIA, XLK, XLF, XLE, XLV
- Likit hisseler: AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, JPM, V, XOM, UNH, WMT

Pilot varlıklar veritabanında `AssetClass=us_equity`, `IsShadowEnabled=true`, `IsActive=false`
olarak tutulur. Veri toplanır fakat model kapıları geçmeden arayüze veya production tahminlerine karışmaz.

## Ücretsiz veri sözleşmesi

- Sağlayıcı: Twelve Data Basic
- Endpoint: `/time_series`, `interval=1day`, `outputsize=5000`
- Corporate-action ayarı: `adjust=all` (split + temettü)
- Kaynak kimliği: `twelvedata-us-eod-total-return`
- Günlük zaman: borsanın yerel seans tarihi, depoda UTC gün başlangıcına normalize edilir
- Son tamamlanan seans: SPY için yayımlanmış son EOD barı
- Her bar: payload SHA-256, `AvailableAt`, source ve final-state bilgisiyle saklanır

Basic plan 8 kredi/dakika ve 800 kredi/gün verdiği için çağrılar en az 8 saniye arayla seri yapılır.
20 sembollük ilk tarihsel dolum yaklaşık üç dakika, günlük yenileme de 20 kredi sürer. Sağlayıcı EOD
verisini seans gününden sonraki 00:00 ET civarında yayımladığı için job 05:15, 07:15 ve 09:15 UTC'de
çalışır. Cumartesi çalışması cuma seansını kapsar.

## Çalıştırma

Twelve Data ücretsiz hesabından bir anahtar alıp `.env` dosyasına ekleyin:

```text
TWELVE_DATA_ENABLED=true
TWELVE_DATA_API_KEY=...
```

Ardından:

```powershell
docker compose up -d --build worker
```

Anahtar yalnızca backend tarafından `Authorization` header'ında kullanılır; URL'ye veya web istemcisine yazılmaz.

## Sınırlar ve üretim kapıları

1. Basic lisansı internal/non-display araştırma içindir. Son kullanıcıya veri gösterimi veya ticari dağıtım öncesi lisans yeniden doğrulanır.
2. Günlük EOD verisi modelin 30/90 günlük ufku için uygundur; gerçek zamanlı işlem motoru değildir.
3. Point-in-time sembol/universe tarihi olmadan güncel hisselerle geriye dönük “tüm piyasa” sonucu üretilmez.
4. Delisting, ticker değişimi, merger/spin-off ve corporate-action audit tabloları tamamlanır.
5. ABD hisseleri crypto modelinden ayrı dataset, feature schema, baseline ve model registry kaydı kullanır.
6. Purging, 30/90 işlem seanslı event interval üzerinden uygulanır.
7. Model production kapılarını geçmeden `IsActive=true` yapılmaz ve kullanıcı sinyali yayımlanmaz.

Pilot liste yalnızca gelecekte veri toplamak ve entegrasyonu doğrulamak içindir. Geniş universe eğitimi için
tarihsel üyelik ve delisting içeren point-in-time bir security master zorunludur.

## Shadow tahmin kanıtı

Pilot evren için kriptodan tamamen ayrı iki aday model çalışır:

- 30 tamamlanmış ABD işlem seansı
- 90 tamamlanmış ABD işlem seansı

Özellik şeması `us-equity-daily-v1` sürümüdür. SPY benchmark getirileri, 252 seanslık
yıllıklaştırılmış oynaklık, overnight gap, intraday getiri, dolar hacmi ve pilot evren içindeki
kesitsel momentum/oynaklık sıraları kullanılır. Kripto türev özellikleri veya 24x7 takvim varsayımı
equity modeline taşınmaz.

Modeller promotion kapısından bağımsız olarak önce `IsShadowCandidate=true` kaydedilir. Tahminler
`IsShadow=true` tutulur, kullanıcı analiz endpointine karışmaz ve ilk etiket ancak ilgili sayıda yeni
tamamlanmış işlem seansı görüldüğünde olgunlaşır. Operasyon dashboardu kripto ve ABD modellerini aynı
toplam sayaçta, varlık sınıfı ve ufuk birimini açıkça ayırarak gösterir.
