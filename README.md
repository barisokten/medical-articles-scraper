# Medical Articles Scraper

Bu proje, belirli sağlık sitelerinde yayınlanan makalelerin **başlık**, **URL**, **yayınlanma tarihi (varsa)** ve **keyword (anahtar kelime)** bilgilerini otomatik olarak toplayarak **Supabase (PostgreSQL)** veritabanına kaydetmek amacıyla geliştirilmiştir.

Proje, **makale içeriğini çekmez**. Yalnızca makale **meta verileri** toplanır.  
Amaç; temiz, tekrarsız (duplicate’siz) ve API’ler tarafından kolayca kullanılabilir bir veri seti oluşturmaktır.

---

## 🎯 Proje Amacı

- Sağlık sitelerindeki tüm makaleleri otomatik olarak tespit etmek
- Her makale için:
  - Site adı
  - Makale başlığı
  - Makale URL’si
  - Yayınlanma tarihi (sayfada varsa)
  - Otomatik üretilmiş keyword
- Aynı makalenin birden fazla kez eklenmesini **tamamen engellemek**
- Tek komutla çalışan, **full otomatik ve güvenli** bir scraping pipeline oluşturmak

---

## 🧩 Desteklenen Siteler

- **Dentway** (`dentway.com.tr`)
- **Florence Nightingale Hastanesi** (`florence.com.tr`)

Yeni siteler, mevcut mimari korunarak kolayca eklenebilir.

---

## ⚙️ Kullanılan Teknolojiler

- Python
- Selenium (dinamik sayfalar için)
- Requests + BeautifulSoup (hızlı HTML parse)
- Supabase (PostgreSQL)
- dotenv (ortam değişkenleri)

---

## 🗄️ Veritabanı Yapısı (Supabase)

Tablo adı: `articles`

| Kolon Adı       | Açıklama |
|-----------------|----------|
| `id`            | Otomatik ID |
| `created_at`    | Kayıt eklenme zamanı |
| `site_adi`      | Makalenin ait olduğu site |
| `baslik`        | Makale başlığı |
| `url`           | Makale URL’si |
| `yayin_tarihi`  | Yayın tarihi (varsa) |
| `keyword`       | Otomatik üretilen anahtar kelime |

### Duplicate Engelleme

```sql
ALTER TABLE public.articles
ADD CONSTRAINT articles_url_unique UNIQUE (url);
