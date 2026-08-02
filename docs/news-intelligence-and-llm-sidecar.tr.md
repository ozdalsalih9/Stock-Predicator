# Probora haber zekâsı ve LLM yorum katmanı

Bu belge, fiyat tahmin modelini değiştirmeden haber kanıtı toplayan ve model çıktısını günlük olarak açıklayan yan servisin çalışma sözleşmesidir.

## 1. Kaynak sırası

1. **Federal Reserve RSS** varsayılan olarak açıktır. Para politikası ve Fed duyuruları doğrudan resmi kaynaktan alınır.
2. **Finnhub** API anahtarı verilirse şirket ve kripto haberlerinde birincil kaynak olur. Anahtar `X-Finnhub-Token` başlığıyla gönderilir; URL'ye veya loglara yazılmaz.
3. **GDELT** geniş haber taraması ve yedek kaynak olarak çalışır. Oran sınırı ve geçici sunucu hatalarında aralıklı tekrar dener.
4. **SEC EDGAR** şirket bildirimleri için planlanan sonraki adaptördür. Üretime eklenmeden önce ticker-CIK eşlemesi ve SEC'e uygun iletişim içeren User-Agent tanımlanmalıdır.

Kaynaklar aynı `NewsArticle` tablosuna yazılır. URL normalleştirilir ve hash ile yinelenen kayıtlar engellenir. Daha güvenilir resmi kaynak aynı haberi görürse sağlayıcı ve güvenilirlik bilgisi yükseltilir.

## 2. Zaman ve veri sızıntısı kuralı

Her haberde iki ayrı zaman tutulur:

- `PublishedAt`: yayıncının bildirdiği yayın zamanı.
- `AvailableAt`: Probora'nın bu haberi ilk kez gerçekten görebildiği zaman.

Bir tahmini açıklayan LLM yalnızca `PublishedAt <= AnalysisTime` ve `AvailableAt <= AnalysisTime` koşullarının ikisini de sağlayan haberleri görebilir. Sonradan bulunan eski bir haber geçmiş tahminin gerekçesine eklenemez. Yeniden görülen haberde `RetrievedAt` güncellenebilir fakat `AvailableAt` değiştirilmez.

## 3. Haber toplama takvimi

- Finnhub şirket/kripto haberleri: saatte bir.
- Fed RSS: saatte bir.
- GDELT geniş tarama: mevcut shadow haber takvimiyle ve kontrollü istek aralığıyla.
- LLM açıklaması: 15 dakikada bir; her çalışmada en fazla 4 yeni tahmin.

Haber toplama ve LLM işleri Quartz tarafından ayrı çalıştırılır. Bir kaynak hata verdiğinde fiyat tahmini ve shadow sayaçları durmaz.

## 4. LLM'ye verilen sözleşme

LLM'ye serbest bir veritabanı özeti gönderilmez. Sürümü belirlenmiş, deterministik bir JSON paketi gönderilir:

- modelin düşüş/yatay/yükseliş olasılıkları,
- baseline karşılaştırması,
- P10/P50/P90 aralığı,
- güven, risk ve veri durumu,
- modelin sayısal pozitif/negatif faktörleri,
- özellik zamanları ve UTC cutoff,
- yalnızca cutoff anında bilinen haber başlıkları ve URL'leri,
- model sürümü ve artefakt hash'i.

LLM'nin görevi yeni tahmin üretmek değildir. Olasılıkları değiştiremez; yalnızca verilen kanıtı Türkçe açıklar, çelişkileri ve belirsizliği belirtir. Haber başlıkları güvenilmeyen içerik sayılır ve içlerindeki talimatlar yok sayılır. Çıktıdaki kaynak URL'leri girişteki izinli URL listesiyle filtrelenir.

Sonuç `prediction_explanations` tablosunda sağlayıcı, model, prompt sürümü, giriş hash'i, ham giriş ve yapılandırılmış çıktı ile saklanır. Aynı tahmin/sağlayıcı/model/prompt birleşimi ikinci kez üretilmez. Başarısız yorum tahmini bozmaz ve daha sonra kontrollü yeniden denenebilir.

## 5. LLM seçimi

### Ücretsiz başlangıç: Groq üzerinde GPT-OSS 20B

`.env.vps` içine gerçek anahtar yalnızca sunucuda yazılır:

```dotenv
LLM_EXPLANATIONS_ENABLED=true
LLM_PROVIDER=groq
LLM_BASE_URL=https://api.groq.com/openai/v1/
LLM_API_KEY=...
LLM_MODEL=openai/gpt-oss-20b
```

Bu seçim OpenAI uyumlu istemciyi değiştirmeden ücretsiz kota içinde günlük açıklama üretmek için uygundur. Ücretsiz kota üretim garantisi değildir; limit aşılırsa açıklama işi başarısız olarak kaydedilir, tahmin akışı devam eder.

### Kalite karşılaştırması: OpenAI GPT-5.6 Luna

```dotenv
LLM_EXPLANATIONS_ENABLED=true
LLM_PROVIDER=openai
LLM_BASE_URL=https://api.openai.com/v1/
LLM_API_KEY=...
LLM_MODEL=gpt-5.6-luna
```

ChatGPT Plus üyeliği OpenAI API kotası sağlamaz. Bu seçenek ayrı API anahtarı ve API faturalandırması gerektirir. Önce ücretsiz sağlayıcıyla operasyonu doğrulayıp aynı sabit test kümesinde özet doğruluğu, kaynak sadakati, gecikme ve maliyeti karşılaştırmak önerilir.

## 6. Haber sağlayıcı ayarları

```dotenv
MACRO_NEWS_ENABLED=true
GDELT_ENABLED=true
FINNHUB_NEWS_ENABLED=true
FINNHUB_API_KEY=...
```

Finnhub anahtarı yoksa `FINNHUB_NEWS_ENABLED=false` bırakılır. Anahtarlar repoya commit edilmez.

## 7. İzleme ve API

- `GET /api/v1/system/news-intelligence`: sağlayıcı bazında son görülme, 24 saatlik haber sayısı ve LLM başarı/hata sayıları.
- `GET /api/v1/assets/{symbol}/news`: varlık haberleri, sağlayıcı ve erişilebilirlik zamanı.
- `GET /api/v1/assets/{symbol}/explanations/latest?horizonDays=30&includeShadowPreview=true`: son yapılandırılmış açıklama.

Arayüz varlık detayında 30 ve 90 günlük açıklamaları ayrı gösterir. Açıklama yoksa bu, tahminin olmadığı anlamına gelmez; LLM kapalı, kotası dolu veya ilgili tahmin henüz yorumlanmamış olabilir.

## 8. Güvenli devreye alma sırası

1. Migration ve haber kaynakları LLM kapalıyken devreye alınır.
2. Haber sağlık endpoint'i ve `AvailableAt` kuralları doğrulanır.
3. LLM tek sağlayıcı ve düşük günlük limit ile açılır.
4. Kaynak uydurma, olasılık değiştirme ve prompt-injection testleri izlenir.
5. Yeterli örnekten sonra Groq ile OpenAI çıktıları kör değerlendirme setinde karşılaştırılır.
6. LLM metni hiçbir aşamada model skoru, Brier hesabı veya shadow sonucunu değiştirmez.
