# Probora domainsiz VPS kurulumu

Bu kurulum Probora'yi internete acmaz. Gateway yalnizca VPS loopback adresindeki
`127.0.0.1:8090` portuna baglanir. Arayuze sifreli SSH tuneliyle erisilir.

VPS'te MLflow, MinIO ve egitim dataset'leri calistirilmaz. Model egitimi yerel
RTX 3050 Ti bilgisayarda yapilir; yalnizca ONNX bundle'lari VPS'e kopyalanir.

## 1. Dosyalari VPS'e yerlestirme

Projeyi `/opt/probora` altina kopyalayin. En az su dosya ve klasorler gereklidir:

- `docker-compose.vps.yml`
- `Directory.Build.props`, `Directory.Packages.props`, `global.json`
- `src`, `web`, `infra`
- `artifacts/models`

Buyuk `data`, `mlruns`, `.venv`, `bin`, `obj` ve `node_modules` klasorlerini
VPS'e kopyalamayin.

Hazir deployment paketini ve veritabani dump'ini yerel bilgisayarda olusturmak
icin:

```powershell
.\infra\vps\New-ProboraVpsBundle.ps1
```

Olusan iki dosyayi VPS'e aktarip acin:

```powershell
scp .\dist-vps\probora-vps.tar.gz root@VPS_IP:/tmp/
scp .\dist-vps\probora.dump root@VPS_IP:/tmp/
```

```bash
mkdir -p /opt/probora
tar -xzf /tmp/probora-vps.tar.gz -C /opt/probora
mv /tmp/probora.dump /opt/probora/probora.dump
cd /opt/probora
```

## 2. Ortam dosyasi

VPS'te:

```bash
cd /opt/probora
cp .env.vps.example .env.vps
openssl rand -hex 32
nano .env.vps
```

Uretilen parolayi `POSTGRES_PASSWORD` olarak, Twelve Data anahtarini da
`TWELVE_DATA_API_KEY` olarak kaydedin. `.env.vps` dosyasini kaynak kontrolune
eklemeyin veya mesajlarda paylasmayin.

## 3. PostgreSQL'i baslatma

```bash
cd /opt/probora
docker compose --env-file .env.vps -f docker-compose.vps.yml up -d postgres
```

## 4. Yerel veritabanini tasima

Mevcut 90 gunluk turev snapshot'lari ve ABD hisse backfill'ini kaybetmemek icin
yerel PostgreSQL veritabani ilk kurulumda VPS'e tasinmalidir.

Paketleme script'i kullanilmadiysa yerel bilgisayarda PowerShell:

```powershell
docker compose exec -T postgres pg_dump -U probora -d probora -Fc -f /tmp/probora.dump
docker cp probora-postgres-1:/tmp/probora.dump .\probora.dump
scp .\probora.dump root@VPS_IP:/opt/probora/probora.dump
```

VPS'te:

```bash
cd /opt/probora
docker cp probora.dump probora-postgres-1:/tmp/probora.dump
docker compose --env-file .env.vps -f docker-compose.vps.yml exec -T postgres \
  pg_restore -U probora -d probora --clean --if-exists /tmp/probora.dump
docker compose --env-file .env.vps -f docker-compose.vps.yml up -d --build
docker compose --env-file .env.vps -f docker-compose.vps.yml ps
curl --fail http://127.0.0.1:8090/health/ready
```

Build tamamlandiktan sonra cache temizlenebilir:

```bash
docker builder prune -af
```

Dump dogrulandiktan sonra hem VPS'teki hem yerel bilgisayardaki gecici dump
kopyalari silinebilir.

## 5. Windows'tan arayuze baglanma

PowerShell penceresinde su oturumu acik tutun:

```powershell
ssh -L 8090:127.0.0.1:8090 root@VPS_IP
```

Ardindan tarayicida `http://localhost:8090` adresini acin. SSH oturumu kapansa
bile worker, collector ve zamanlanmis isler VPS'te calismaya devam eder; yalnizca
arayuze ait tunel kapanir.

## 6. Operasyon komutlari

```bash
cd /opt/probora
docker compose --env-file .env.vps -f docker-compose.vps.yml ps
docker compose --env-file .env.vps -f docker-compose.vps.yml logs --tail 100 worker
docker compose --env-file .env.vps -f docker-compose.vps.yml restart worker
docker compose --env-file .env.vps -f docker-compose.vps.yml pull
df -h /
```

Kalici veriyi korumak icin `docker compose down -v`, `docker volume prune` veya
`docker system prune --volumes` kullanmayin.

## 7. Mevcut VPS'i kod ve model bundle'i ile guncelleme

Veritabani zaten VPS'te calisiyorsa yeni dump geri yuklemeyin. Yerelde paket olusturun:

```powershell
.\infra\vps\New-ProboraVpsBundle.ps1 -SkipDatabase
scp .\dist-vps\probora-vps.tar.gz root@VPS_IP:/tmp/
```

VPS'te mevcut `.env.vps` ve PostgreSQL volume'una dokunmadan kodu acip image'lari yeniden kurun:

```bash
cd /opt/probora
tar -xzf /tmp/probora-vps.tar.gz -C /opt/probora
docker compose --env-file .env.vps -f docker-compose.vps.yml up -d --build
docker compose --env-file .env.vps -f docker-compose.vps.yml ps
curl --fail http://127.0.0.1:8090/health/ready
docker compose --env-file .env.vps -f docker-compose.vps.yml logs --tail 150 worker
```

Eski Parai kurulumunu yerinde Probora'ya yükseltiyorsanız mevcut PostgreSQL volume'unu korumak
için `.env.vps` dosyasına aşağıdaki uyumluluk değerlerini ekleyin ve komutlara `-p parai` verin:

```bash
POSTGRES_DB=parai
POSTGRES_USER=parai

docker compose -p parai --env-file .env.vps -f docker-compose.vps.yml up -d --build
```

Bu yalnızca fiziksel veritabanı ve Docker project kimliğini korur. Uygulama bağlantı anahtarı,
kod adları ve veritabanı şeması migration sonrasında Probora olur.

Worker baslangicta migration'i uygular, model registry taramasini calistirir ve startup tahmin
tetikleyicisini bes dakikada bir tekrarlar. Beklenen yeni shadow kayitlari:

- `probora-us-equity-v1-30d-20260715120509`: direction=false, scenario=true
- `probora-us-equity-v1-90d-20260715120200`: direction=false, scenario=true

Bayraklari dogrulamak icin:

```bash
docker compose --env-file .env.vps -f docker-compose.vps.yml exec -T postgres \
  psql -U probora -d probora -c \
  'SELECT "Version", "DirectionEligible", "ScenarioEligible", "IsShadowCandidate" FROM probora.model_versions ORDER BY "TrainedAt" DESC LIMIT 6;'
```

Bu iki bundle senaryo kapisini gecmistir; yon sinyali otomatik bastirilir. Shadow sonuclari
olgunlasmadan production bayragi verilmez.
