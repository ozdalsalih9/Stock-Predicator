# Model yönetişimi

## Problem sözleşmesi

- Tahmin anı: UTC 00:00 günlük kapanış.
- Ufuklar: 30 ve 90 takvim günü.
- Yön sınıfları: yükseliş, yatay ve düşüş.
- Etiket eşiği: kısa/uzun dönem yıllıklandırılmış volatilitenin %65/%35 varyans karışımıyla
  dinamik hesaplanır; volatilite %20-%150 arasında, 30 günlük eşik %2,5-%18 arasında kırpılır ve
  ufka `sqrt(ufuk/30)` ile ölçeklenir. ABD hisselerinde 252 seans, kriptoda 365 gün kullanılır.
- Tek fiyat tahmini yerine P10, P50 ve P90 log getiri quantile'ları yayınlanır.

## Zaman güvenliği

Her veri satırı `available_at` alanıyla saklanır. Özellikler yalnızca tahmin anında erişilebilir kayıtlarla oluşturulur. Her örneğin olay aralığı `snapshot_time`–`label_end_time` olarak tutulur. Eğitim etiketi validation başlangıcına, validation etiketi test başlangıcına taşan tüm satırlar purge edilir; sınırlardan önce ayrıca 7 günlük embargo uygulanır. Aynı tarihteki bütün varlıklar aynı fold'da kalır. 2023, 2024 ve 2025 ayrı dış-test yıllarıdır. Test dönemi görüldükten sonra aynı model sürümünün hiperparametreleri değiştirilemez.

Canlıda `00:00 UTC` job saati değil veri kesimidir. Günlük inference, spot tarafta tam 24 final
saatlik mum ve türev tarafta cutoff'ta biten 90 kesintisiz tamamlanmış snapshot görmeden açılmaz.
Bir kaydın `available_at` değeri inference anından sonra veya `source_max_event_time` değeri kendi
snapshot cutoff'una eşit/sonra ise kayıt as-of ihlali sayılır. Eksik veriyle sıfır doldurulmuş tahmin
yayınlamak yerine job ertelenir.

## Üretim kapıları

- Ortalama multiclass Brier skoru en güçlü baseline'dan en az %5 iyi.
- Üç dış-test fold'unun en az ikisinde baseline üstünlüğü.
- ECE en fazla 0,05.
- P10–P90 kapsamı %75–85.
- Gelecek volatilite risk skoru MAE'si, mevcut 30 günlük volatilite baseline'ından en az %5 iyi
  ve üç fold'un en az ikisinde baseline üstü.
- ONNX dosyaları yüklenebilir, manifest hash'i doğrulanmış ve Python–ONNX–.NET runtime parity
  sözleşmesi yön, quantile, risk ve baseline çıktılarında `1e-5` toleransla geçmiş.
- Model manifestinde `productionEligible=true` bulunuyor.

Manifest yalnızca offline kanıttır ve tek başına production yetkisi değildir. Kapılardan biri
başarısızsa model registry kaydı oluşturulabilir fakat production alias verilmez. Daha yeni fakat
offline yön ve senaryo kapılarının ikisini de geçememiş bir artifact mevcut uygun shadow adayını
yerinden edemez.

Canlı tahmin kendi baseline olasılıklarını ve o anda kullanılan neutral-band eşiğini saklar. Ufuk
dolduğunda final barlardan gerçekleşen yön/getiri/volatilite çözülür; kaynak bar kimliği SHA-256 ile
dondurulur. Model Brier, baseline Brier, Brier skill, ECE, P10-P90 kapsama, pinball loss ve risk MAE
hesaplanır. Canlı inceleme için en az 100 sonuç, 20 farklı değerlendirme günü, her sınıfta en az 10
sonuç, en az +%5 Brier skill, en fazla %5 ECE ve %75-%90 interval coverage gerekir. Bu koşulların
tamamı geçse bile durum yalnızca `eligible_for_manual_review` olur; otomatik production terfisi yoktur.

## Özellik grubu ablation kuralları

- Özellikler tek tek testte seçilmez; `spot`, `derivatives` ve `cross_sectional` olarak önceden
  tanımlanmış gruplar halinde karşılaştırılır.
- Yeni grup spot modele karşı üç dış-test fold'unun en az ikisinde Brier kazanımı göstermelidir.
- Günlük kayıplar tahmin ufku uzunluğunda ardışık bloklarla yeniden örneklenir. Eşlenmiş %95
  bootstrap güven aralığı sıfırı içeriyorsa kazanım kanıtlanmış sayılmaz.
- Boosted tree modellerinde klasik AIC/BIC parametre sayısı iyi tanımlı olmadığından BIC-benzeri
  skor yalnızca muhafazakâr karmaşıklık stres testi olarak raporlanır; promotion kararı tek başına
  bu skora dayanmaz.
- Çapraz-kesit ve varlık kimliği grubu risk MAE'sini bozduğu için V2 üretim şemasından çıkarılmış,
  yalnızca challenger datasetinde tutulmuştur.

## Güven kapısı

Yön sinyali için en yüksek sınıf olasılığı en az 0,55, ilk iki sınıf arasındaki fark en az 0,15 olmalıdır. Quantile medyanının yönü sınıflandırıcıyla çelişirse, veri 26 saatten eskiyse veya özellik seti eksikse sinyal durdurulur. Eşikler ileride yalnızca validation döneminde seçilerek yeni model sürümüyle değiştirilebilir.

## Açıklamalar

Her özellik sıfır referansına çekilip ONNX tahmini yeniden çalıştırılır. Temel tahmin skorundaki fark yerel katkı yaklaşımı olarak saklanır. Bu değerler nedensellik, kesin fiyat etkisi veya yatırım tavsiyesi olarak sunulmaz.
