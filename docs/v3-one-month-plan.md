# Probora V3 — Dört Haftalık Üretim Adayı Planı

Başlangıç: 14 Temmuz 2026
Üretim adayı hedefi: 10 Ağustos 2026
30 günlük shadow kanıtının en erken tamamlanması: 13 Ağustos 2026

## Değişmez kabul kapıları

- Purged walk-forward testlerinde ortalama Brier, en güçlü baseline'dan en az %5 daha iyi olmalı.
- En az üç dış fold'un ikisi Brier açısından kazanılmalı.
- ECE en fazla %5 olmalı.
- Kalibre p10–p90 kapsamı %75–%85 aralığında olmalı.
- Risk MAE, volatilite baseline'ını en az %5 yenmeli ve üç fold'un ikisini kazanmalı.
- Hiçbir özellik test dönemine bakılarak seçilmemeli; seçim yalnızca train/validation içinde yapılmalı.
- Kapıları geçmeyen model production olarak işaretlenmemeli.

## 1. hafta — Ölçüm ve hedef düzeltme (14–20 Temmuz)

- V2 hatalarını volatilite, hacim, trend, mean-reversion ve geçiş rejimlerine ayır.
- Robust, geçmişe dönük volatiliteye bağlı neutral band'i dataset kimliğine kaydet.
- Rejim bazlı kalibrasyon ve güven küçültme adaylarını yalnızca validation'da seç.
- Risk modelini yön modelinden bağımsız değerlendir.

Çıkış kriteri: yeniden üretilebilir V3 dataset, rejim raporu ve sabitlenmiş kabul kapıları.

## 2. hafta — Sınırlı model araması (21–27 Temmuz)

- Logistic/climatology, LightGBM ve sınırlı bir ikinci ağaç modelini karşılaştır.
- Hiperparametre aramasını küçük ve önceden tanımlı tut; dış test fold'larına dokunma.
- Spot ve türev gruplarını IC cezası ve blok-bootstrap ile değerlendir.
- Mean-reversion/geçiş rejiminde selective confidence veya baseline fallback uygula.

Çıkış kriteri: en fazla iki production-candidate konfigürasyonu.

## 3. hafta — Kilitli backtest ve stres testleri (28 Temmuz–3 Ağustos)

- Seçilen konfigürasyonları değişiklik yapmadan üç dış fold ve çoklu seed ile çalıştır.
- Varlık, rejim, yıl ve veri gecikmesi streslerini raporla.
- ONNX/Python/.NET tahmin paritesini doğrula.
- Tahmin yayınlama, abstention ve veri readiness kapılarını uçtan uca test et.

Çıkış kriteri: kapıları geçen imzalı model bundle veya açık bir “no-go” kararı.

## 4. hafta — Dağıtım ve operasyon (4–10 Ağustos)

- Kapıları geçen bundle'ı model registry'de production-candidate yap.
- DailyPredictionJob, dashboard, model card ve alarm akışını doğrula.
- Shadow tahminleri ve gerçekleşen sonuçları değiştirilemez audit kaydıyla sakla.
- Runbook, rollback ve veri kaynağı kesinti prosedürünü tamamla.

Çıkış kriteri: çalışan üretim adayı. Model kapıları geçmezse sistem Research Beta olarak kalır ve sahte sinyal yayınlamaz.

## Takvim konusunda dürüst sınır

Kod, veri hattı ve üretim adayı dört haftadan kısa sürede tamamlanabilir. Buna karşılık 30 günlük canlı shadow performansı 30 takvim günü dolmadan kanıtlanmış sayılamaz. İlk yayın Research Beta olabilir; “güvenilir production” etiketi ancak shadow süresi ve kabul kapıları tamamlandıktan sonra verilir.
