import os
import time
import random
from urllib.parse import urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service

from supabase import create_client
from dotenv import load_dotenv
import re



load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")  # mümkünse service_role

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL / SUPABASE_KEY .env içinde yok veya boş. Kontrol et.")

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# ✅ FIX: Tek yerde config
MODE = os.getenv("MODE", "auto").lower()               # auto | links | details
AUTO_DETAILS = os.getenv("AUTO_DETAILS", "1") == "1"   # auto modda details çalışsın mı
DETAIL_BATCH_LIMIT = int(os.getenv("DETAIL_BATCH_LIMIT", "25"))
DETAIL_ROUNDS = int(os.getenv("DETAIL_ROUNDS", "3"))  # tek run'da kaç batch

# -------------------------
# URL TEMİZLEME / FİLTRELER
# -------------------------

def normalize_url(url: str) -> str:
    """utm vb. query/fragment sil, normalize et."""
    try:
        u = urlparse(url)
        clean = u._replace(query="", fragment="")
        return urlunparse(clean)
    except Exception:
        return url


def same_domain(url: str, domain: str) -> bool:
    """domain kontrolünü netloc üzerinden yap."""
    try:
        netloc = urlparse(url).netloc.lower()
        domain = domain.lower()
        return netloc == domain or netloc.endswith("." + domain)
    except Exception:
        return False


def is_valid_dentway_article_url(url: str) -> bool:
    bad = ["whatsapp.com", "goo.gl/maps", "tel:", "mailto:", "facebook.com", "instagram.com"]
    if any(x in url for x in bad):
        return False
    if not same_domain(url, "dentway.com.tr"):
        return False

    path = (urlparse(url).path or "").rstrip("/")
    if path == "/blog":
        return False

    allowed_prefixes = ("/blog/", "/tedavi/")
    if not (path + "/").startswith(allowed_prefixes):
        return False

    blocked_prefixes = ("/blog/page/", "/kategori/", "/doktor/", "/hekimlerimiz/", "/hakkimizda/", "/kvkk")
    if any((path + "/").startswith(bp) for bp in blocked_prefixes):
        return False

    return True


def is_valid_florence_article_url(url: str) -> bool:
    bad = ["whatsapp.com", "goo.gl/maps", "tel:", "mailto:", "facebook.com", "instagram.com"]
    if any(x in url for x in bad):
        return False
    if not same_domain(url, "florence.com.tr"):
        return False

    path = (urlparse(url).path or "").rstrip("/")
    if not (path + "/").startswith("/guncel-saglik/"):
        return False
    if path == "/guncel-saglik":
        return False
    return True
# KEYWORD İŞLEMİ
TR_STOPWORDS = {
    "ve","ile","icin","için","da","de","ta","te","mi","mı","mu","mü",
    "bir","bu","şu","o","en","cok","çok","gibi","nedir","nasil","nasıl","ne"
}

def keyword_from_title_or_slug(baslik: str | None, url: str) -> str:
    # 1) Başlıktan üret
    if baslik:
        t = baslik.strip()
        # "Başlık | Site" gibi son ekleri kırp
        for sep in [" | ", " - ", " • ", " — ", " – "]:
            if sep in t:
                t = t.split(sep)[0].strip()
                break
        # temizle
        t = t.lower()
        t = re.sub(r"[^\w\sçğıöşü-]", " ", t, flags=re.UNICODE)
        t = t.replace("-", " ")
        t = re.sub(r"\s+", " ", t).strip()
        words = [w for w in t.split() if w not in TR_STOPWORDS and len(w) > 2]
        if words:
            return " ".join(words[:4]).title()
        return t.title() if t else "Genel"

    # 2) URL slug fallback
    path = (urlparse(url).path or "").rstrip("/")
    slug = path.split("/")[-1] if path else ""
    slug = slug.replace("-", " ").replace("_", " ").strip().lower()
    slug = re.sub(r"[^\w\sçğıöşü]", " ", slug, flags=re.UNICODE)
    slug = re.sub(r"\s+", " ", slug).strip()
    words = [w for w in slug.split() if w not in TR_STOPWORDS and len(w) > 2]
    return (" ".join(words[:4]).title()) if words else (slug.title() if slug else "Genel")


# -------------------------
# SCRAPER
# -------------------------

class BlogScraper:
    def __init__(self, headless: bool = True):
        opts = Options()
        if headless:
            opts.add_argument("--headless=new")

        opts.add_argument("--window-size=1400,900")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--lang=tr-TR")
        opts.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )

        self.driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=opts
        )
        self.wait = WebDriverWait(self.driver, 15)

        # ✅ HIZ: requests session
        self.http = requests.Session()
        self.http.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        })

    def _wait_ready(self, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            try:
                state = self.driver.execute_script("return document.readyState")
                if state == "complete":
                    return True
            except Exception:
                pass
            time.sleep(0.15)
        return False

    def _smart_scroll(self, steps=4, pause=0.8):
        for _ in range(steps):
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(pause)

    def _try_accept_cookies(self):
        try:
            btn = self.driver.find_elements(By.CSS_SELECTOR, "button#onetrust-accept-btn-handler")
            if btn:
                btn[0].click()
                time.sleep(0.2)
                return
        except Exception:
            pass

        try:
            buttons = self.driver.find_elements(By.TAG_NAME, "button")
            for b in buttons[:50]:
                txt = (b.text or "").strip().lower()
                if txt in ("kabul et", "kabul", "accept", "i agree", "tamam", "ok", "tümünü kabul et"):
                    try:
                        b.click()
                        time.sleep(0.2)
                        return
                    except Exception:
                        continue
        except Exception:
            pass

    def collect_links_basic(self, list_url: str, scroll_steps=6) -> list[str]:
        self.driver.get(list_url)
        self._wait_ready()
        time.sleep(0.6)
        self._try_accept_cookies()
        self._smart_scroll(steps=scroll_steps, pause=0.7)

        anchors = self.driver.find_elements(By.CSS_SELECTOR, "a[href]")
        hrefs = []
        for a in anchors:
            try:
                href = a.get_attribute("href")
                if href:
                    hrefs.append(normalize_url(href))
            except Exception:
                pass

        return list(dict.fromkeys(hrefs))

    def get_existing_urls(self, site_adi: str) -> set[str]:
        existing = set()
        start = 0
        step = 1000
        while True:
            res = (
                sb.table("articles")
                .select("url")
                .eq("site_adi", site_adi)
                .range(start, start + step - 1)
                .execute()
            )
            data = res.data or []
            if not data:
                break
            for r in data:
                u = r.get("url")
                if u:
                    existing.add(u)
            start += step
        return existing

    def collect_florence_article_links(self) -> list[str]:
        anchors = self.driver.find_elements(By.CSS_SELECTOR, "a[href]")
        out = []
        for a in anchors:
            href = a.get_attribute("href")
            if not href:
                continue
            href = normalize_url(href)

            if "florence.com.tr/guncel-saglik/" in href:
                path = (urlparse(href).path or "").rstrip("/")
                if path != "/guncel-saglik":
                    out.append(href)
        return list(dict.fromkeys(out))

    def collect_links_with_pagination(self, target: dict, max_pages=8) -> list[str]:
        site = target["site"]
        list_url = target["list_url"]
        all_links = []

        if site == "Dentway":
            for i in range(1, max_pages + 1):
                page_url = list_url if i == 1 else list_url.rstrip("/") + f"/page/{i}/"
                links = self.collect_links_basic(page_url, scroll_steps=5)
                before = len(all_links)
                all_links.extend(links)
                all_links = list(dict.fromkeys(all_links))
                print(f"   📄 Sayfa {i}: +{len(all_links) - before} yeni link")
                if len(all_links) - before == 0 and i > 1:
                    break

        elif site == "Florence":
            seed_pages = [
                "https://www.florence.com.tr/",
                "https://www.florence.com.tr/guncel-saglik",
                "https://www.florence.com.tr/iletisim",
                "https://www.florence.com.tr/insan-kaynaklari",
            ]
            for seed in seed_pages:
                print(f"   🌱 Florence seed: {seed}")
                self.driver.get(seed)
                self._wait_ready()
                time.sleep(0.6)
                self._try_accept_cookies()

                before = len(all_links)
                links = self.collect_florence_article_links()
                all_links.extend(links)
                all_links = list(dict.fromkeys(all_links))
                print(f"      +{len(all_links) - before} makale linki")
        else:
            all_links = self.collect_links_basic(list_url, scroll_steps=6)

        return all_links

    # ---------- FAST HTML PARSE ----------
    def _pick_first_text(self, soup: BeautifulSoup, selectors: list[str]) -> str | None:
        for sel in selectors:
            el = soup.select_one(sel)
            if el:
                txt = el.get_text(" ", strip=True)
                if txt:
                    return txt
        return None

    def _http_get_soup(self, url: str, timeout=12) -> BeautifulSoup | None:
        try:
            time.sleep(random.uniform(0.10, 0.30))
            r = self.http.get(url, timeout=timeout)
            if r.status_code != 200:
                return None
            return BeautifulSoup(r.text, "html.parser")
        except Exception:
            return None

    def scrape_detail_fast(self, site: str, url: str) -> tuple[str | None, str | None]:
        soup = self._http_get_soup(url)
        if not soup:
            return None, None

        if site == "Dentway":
            title = self._pick_first_text(soup, ["h1", ".entry-title", "article h1"])
            date = self._pick_first_text(soup, ["time", ".date", ".post-date", "article time"])
            return title, date

        if site == "Florence":
            title = self._pick_first_text(soup, ["h1", ".page-title", ".news-detail h1", "article h1"])
            date = self._pick_first_text(soup, ["time", ".date", ".publish-date", "article time"])
            return title, date

        title = self._pick_first_text(soup, ["h1", "article h1"])
        date = self._pick_first_text(soup, ["time", ".date"])
        return title, date

    # ---------- SELENIUM FALLBACK ----------
    def _safe_text(self, css_list: list[str]) -> str | None:
        for css in css_list:
            try:
                el = self.driver.find_element(By.CSS_SELECTOR, css)
                txt = (el.text or "").strip()
                if txt:
                    return txt
            except Exception:
                continue
        return None

    def scrape_detail(self, site: str, url: str) -> tuple[str | None, str | None]:
        # 1) FAST
        title, date = self.scrape_detail_fast(site, url)
        kw = keyword_from_title_or_slug(title, url)

        if title or date:
            return title, date

        # 2) FALLBACK
        try:
            self.driver.get(url)
            self._wait_ready()
            time.sleep(0.25)
            self._try_accept_cookies()

            if site == "Dentway":
                title = self._safe_text(["h1", ".blog-detail h1", ".entry-title", "article h1"])
                date = self._safe_text(["time", ".date", ".post-date", "article time"])
                return title, date

            if site == "Florence":
                title = self._safe_text(["h1", ".page-title", ".news-detail h1", "article h1"])
                date = self._safe_text(["time", ".date", ".publish-date", "article time"])
                return title, date

            title = self._safe_text(["h1", "article h1"])
            date = self._safe_text(["time", ".date"])
            return title, date
        except Exception:
            return None, None

    # ---------- LINKS ONLY ----------
    def scrape_site_links_only(self, target: dict) -> list[dict]:
        print(f"\n🔍 {target['site']} -> {target['list_url']}")
        all_links = self.collect_links_with_pagination(target, max_pages=8)
        print(f"🔗 Toplanan toplam link: {len(all_links)}")

        # ✅ FIX: Önce filtrele, sonra DB kıyasla (loglar doğru olsun)
        candidate = []
        for url in all_links:
            if not same_domain(url, target["domain"]):
                continue
            if target["site"] == "Dentway":
                if not is_valid_dentway_article_url(url):
                    continue
            elif target["site"] == "Florence":
                if not is_valid_florence_article_url(url):
                    continue
            candidate.append(url)

        candidate = list(dict.fromkeys(candidate))

        existing = self.get_existing_urls(target["site"])
        new_links = [u for u in candidate if u not in existing]
        print(f"🧠 DB’de var: {len(existing)} | 🆕 Yeni makale: {len(new_links)}")

        results = [{
            "site_adi": target["site"],
            "baslik": None,
            "url": u,
            "yayin_tarihi": None,
            "keyword": keyword_from_title_or_slug(None, u)   # ✅ links aşamasında slug’dan
        } for u in new_links]

        print(f"✅ DB’ye yazılacak yeni URL: {len(results)}")
        return results

    # ✅ FIX: parametre uyumu + return count
    def fill_missing_details(self, target: dict, batch_limit: int = 25) -> int:
        site_adi = target["site"]

        res = (
            sb.table("articles")
            .select("url,site_adi")
            .eq("site_adi", site_adi)
            .is_("baslik", "null")
            .limit(batch_limit)
            .execute()
        )
        rows = res.data or []
        if not rows:
            print(f"✅ {site_adi}: doldurulacak boş kayıt yok.")
            return 0

        print(f"🛠️ {site_adi}: detay doldurulacak kayıt: {len(rows)} (batch={batch_limit})")

        updates = []
        for idx, r in enumerate(rows, start=1):
            url = r["url"]
            title, date = self.scrape_detail(site_adi, url)

            updates.append({
                "site_adi": site_adi,
                "url": url,
                "baslik": title,
                "yayin_tarihi": date,
                "keyword": kw  # ✅ details aşamasında başlığa göre güncellenir
            })
            print(f"➡️ ({idx}/{len(rows)}) Detay alındı: {url}")

        sb.table("articles").upsert(updates, on_conflict="url").execute()
        print(f"✅ {site_adi}: detaylar güncellendi: {len(updates)}")
        return len(updates)

    def save_to_supabase(self, rows: list[dict]):
        if not rows:
            return

        cleaned = [r for r in rows if r.get("url") and r.get("site_adi")]
        if not cleaned:
            return

        try:
            sb.table("articles").upsert(cleaned, on_conflict="url").execute()
            print(f"✅ Supabase'e yazıldı: {len(cleaned)}")
        except Exception as e:
            print(f"❌ Supabase Hatası: {e}")

    def close(self):
        try:
            self.driver.quit()
        except Exception:
            pass

def backfill_missing_keywords(site_adi: str, batch_limit: int = 200) -> int:
    res = (
        sb.table("articles")
        .select("url,site_adi,baslik,keyword")
        .eq("site_adi", site_adi)
        .is_("keyword", "null")
        .limit(batch_limit)
        .execute()
    )
    rows = res.data or []
    if not rows:
        print(f"✅ {site_adi}: keyword doldurulacak kayıt yok.")
        return 0

    updates = []
    for r in rows:
        url = r["url"]
        baslik = r.get("baslik")
        kw = keyword_from_title_or_slug(baslik, url)
        updates.append({"site_adi": site_adi, "url": url, "keyword": kw})

    sb.table("articles").upsert(updates, on_conflict="url").execute()
    print(f"✅ {site_adi}: keyword güncellendi: {len(updates)}")
    return len(updates)

def run():
    targets = [
        {"site": "Dentway", "domain": "dentway.com.tr", "list_url": "https://www.dentway.com.tr/blog/"},
        {"site": "Florence", "domain": "florence.com.tr", "list_url": "https://www.florence.com.tr/guncel-saglik"},
    ]

    scraper = BlogScraper(headless=True)

    try:
        for t in targets:
            if MODE in ("auto", "links"):
                rows = scraper.scrape_site_links_only(t)
                scraper.save_to_supabase(rows)

            if MODE in ("auto", "details"):
                if not AUTO_DETAILS and MODE == "auto":
                    continue

                # batch batch detay doldur
                for _ in range(DETAIL_ROUNDS):
                    filled = scraper.fill_missing_details(t, batch_limit=DETAIL_BATCH_LIMIT)
                    if filled == 0:
                        break

            # ✅ NEW: keyword backfill (title + url slug, GPT yok)
            for _ in range(DETAIL_ROUNDS):
                k = backfill_missing_keywords(t["site"], batch_limit=200)
                if k == 0:
                    break

    finally:
        print("\n⌛ Bitti. Tarayıcı kapanıyor...")
        scraper.close()



if __name__ == "__main__":
    run()
