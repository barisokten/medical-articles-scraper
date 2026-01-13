# Medical Articles Scraper (Dentway & Florence)

Bu proje, belirli sağlık sitelerindeki makalelerin **başlık**, **URL** ve **yayınlanma tarihi (varsa)** bilgilerini otomatik olarak toplayarak **Supabase (PostgreSQL)** veritabanına kaydetmek için geliştirilmiştir.

Amaç, içerik metnini çekmeden yalnızca **makale meta verilerini** düzenli ve tekrarsız (duplicate’siz) şekilde saklamaktır.

---

## 🎯 Proje Amacı

- Sağlık sitelerindeki tüm makaleleri otomatik olarak tespit etmek
- Her makale için:
  - Site adı
  - Makale başlığı
  - Makale URL’si
  - Yayınlanma tarihi (sayfada varsa)
- Aynı makalenin birden fazla kez eklenmesini **tamamen engellemek**
- Tek komutla **full otomatik** çalışan bir veri toplama pipeline oluşturmak

---

## 🧩 Desteklenen Siteler

- **Dentway** (dentway.com.tr)
- **Florence Nightingale Hastanesi** (florence.com.tr)

Yeni siteler aynı mimariyle kolayca eklenebilir.

---

## 🗄️ Veritabanı Yapısı (Supabase)

Tablo adı: `articles`

| Kolon Adı      | Açıklama |
|---------------|----------|
| `id`          | Otomatik ID |
| `created_at`  | Kayıt eklenme zamanı |
| `site_adi`    | Makalenin ait olduğu site |
| `baslik`      | Makale başlığı |
| `url`         | Makale URL’si |
| `yayin_tarihi`| Yayın tarihi (varsa) |

> Not: Makale **içeriği çekilmemektedir**, bu bilinçli bir tercihtir.

### Duplicate Engelleme
```sql
ALTER TABLE public.articles
ADD CONSTRAINT articles_url_unique UNIQUE (url);
