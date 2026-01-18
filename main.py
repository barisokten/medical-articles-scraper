# main.py
import os
import time
import random
import re
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
from datetime import datetime,timezone
from urllib.parse import urlparse


datetime.now(timezone.utc).isoformat()

# ========= LINKIFY DOMAIN MAP =========
DOMAIN_MAP = {
    "ClinicWise": "clinic-wise.com",
    "Florence": "www.florence.com.tr",
    "Dentway": "www.dentway.com.tr",
}


# -------------------------
# BOOTSTRAP
# -------------------------
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")  # mümkünse service_role

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL / SUPABASE_KEY .env içinde yok veya boş. Kontrol et.")

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# -------------------------
# CONFIG
# -------------------------
MODE = os.getenv("MODE", "auto").lower()               # auto | links | details | keywords
AUTO_DETAILS = os.getenv("AUTO_DETAILS", "1") == "1"   # auto modda details çalışsın mı
DETAIL_BATCH_LIMIT = int(os.getenv("DETAIL_BATCH_LIMIT", "25"))
DETAIL_ROUNDS = int(os.getenv("DETAIL_ROUNDS", "2"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "8"))
CHUNK_IN_LIMIT = int(os.getenv("CHUNK_IN_LIMIT", "200"))
HEADLESS = os.getenv("HEADLESS", "1") == "1"
CHROMEDRIVER_PATH = os.getenv("CHROMEDRIVER_PATH")     # opsiyonel

# Dentway: sadece blog mu?
DENTWAY_ONLY_BLOG = os.getenv("DENTWAY_ONLY_BLOG", "0") == "1"


# -------------------------
# URL HELPERS
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

    # sadece blog istiyorsan /tedavi devre dışı
    if DENTWAY_ONLY_BLOG:
        allowed_prefixes = ("/blog/",)
    else:
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


def is_valid_clinicwise_article_url(url: str) -> bool:
    bad = [
        "whatsapp.com", "goo.gl/maps", "tel:", "mailto:",
        "facebook.com", "instagram.com"
    ]
    if any(x in url for x in bad):
        return False

    if not same_domain(url, "clinic-wise.com"):
        return False

    path = (urlparse(url).path or "").rstrip("/")

    # boş, ana sayfa, blog listesi
    if path in ("", "/", "/blog"):
        return False

    # ❌ BLOG OLMAYAN KESİN SAYFALAR
    blocked_exact = {
        "/about",
        "/contact",
        "/privacy-policy",
        "/patient-stories",
        "/patient-journey-guide",
        "/medical-library",
        "/become-a-partner",
        "/become-an-influencer",
        "/before-after-photos-in-turkey",
        "/start-your-treatment-plan-easily",
    }
    if path in blocked_exact:
        return False

    # ❌ kategori / sayfalama / wp içeriği
    blocked_prefixes = (
        "/blog/page/",
        "/category/",
        "/tag/",
        "/author/",
        "/wp-json/",
        "/wp-content/",
        "/wp-admin/",
    )
    if any((path + "/").startswith(bp) for bp in blocked_prefixes):
        return False

    # ✅ URL uzunluğu: landing page’leri elemek için
    if len(path) < 25:
        return False

    return True


# -------------------------
# KEYWORD
# -------------------------
TR_STOPWORDS = {
    "ve", "ile", "icin", "için", "da", "de", "ta", "te", "mi", "mı", "mu", "mü",
    "bir", "bu", "şu", "o", "en", "cok", "çok", "gibi", "nedir", "nasil", "nasıl", "ne"
}


def keyword_from_title_or_slug(baslik: str | None, url: str) -> str:
    # 1) Başlıktan üret
    if baslik:
        t = baslik.strip()
        for sep in [" | ", " - ", " • ", " — ", " – "]:
            if sep in t:
                t = t.split(sep)[0].strip()
                break

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


def build_linkify_payload(row: dict) -> dict | None:
    """
    Scraper DB kaydını alır
    linkify_with_images endpointine %100 uyumlu payload üretir
    """

    # 1️⃣ ZORUNLU: TEXT
    text = (row.get("icerik") or row.get("content") or "").strip()
    if len(text) < 200:
        return None

    # 2️⃣ DOMAIN
    site = row.get("site_adi")
    domain = DOMAIN_MAP.get(site)
    if not domain:
        return None

    # 3️⃣ TOPIC
    topic = (
        row.get("baslik")
        or row.get("keyword")
        or text.split(".")[0][:120]
    )

    return {
        "text": text,
        "topic": topic.strip(),
        "domain": domain,
    }

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

        if CHROMEDRIVER_PATH and os.path.exists(CHROMEDRIVER_PATH):
            service = Service(CHROMEDRIVER_PATH)
        else:
            service = Service(ChromeDriverManager().install())

        self.driver = webdriver.Chrome(service=service, options=opts)
        self.wait = WebDriverWait(self.driver, 15)

        self.http = requests.Session()
        self.http.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        })

    def _wait_ready(self, timeout=15) -> bool:
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

    # ---------- LIST PAGES ----------
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
    def collect_clinicwise_blog_links(self, scroll_steps=10):
        self._smart_scroll(steps=scroll_steps, pause=0.7)

        selectors = [
            "article a[href]",
            ".elementor-post a[href]",
            ".elementor-post__title a[href]",
            ".post a[href]",
            ".post-card a[href]",
            ".blog a[href]",
            ".entry-title a[href]",
        ]

        hrefs = []
        for sel in selectors:
            try:
                anchors = self.driver.find_elements(By.CSS_SELECTOR, sel)
                for a in anchors:
                    try:
                        href = a.get_attribute("href")
                        if href:
                            hrefs.append(normalize_url(href))
                    except Exception:
                        pass
            except Exception:
                pass

        # fallback: hiçbir şey yakalayamazsak tüm linkleri al ama filtrele
        if not hrefs:
            anchors = self.driver.find_elements(By.CSS_SELECTOR, "a[href]")
            for a in anchors:
                try:
                    href = a.get_attribute("href")
                    if href:
                        hrefs.append(normalize_url(href))
                except Exception:
                    pass

        out = []
        for u in hrefs:
            if is_valid_clinicwise_article_url(u):
                out.append(u)

        return list(dict.fromkeys(out))
    def collect_links_with_pagination(self, target: dict, max_pages=8) -> list[str]:
        site = target["site"]
        list_url = target["list_url"]
        all_links = []

        # ---------------- Dentway ----------------
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

        # ---------------- ClinicWise ----------------
        elif site == "ClinicWise":
            self.driver.get(list_url)
            self._wait_ready()
            time.sleep(0.6)
            self._try_accept_cookies()
            all_links = self.collect_clinicwise_blog_links(scroll_steps=12)

        # ---------------- Florence ----------------
        elif site == "Florence":
            seed_pages = [
                "https://www.florence.com.tr/",
                "https://www.florence.com.tr/guncel-saglik",
                "https://www.florence.com.tr/iletisim",
                "https://www.florence.com.tr/insan-kaynaklari",
            ]

            # 🔹 Normal Florence sayfaları
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

            # 🔹 Florence Life (INFINITE SCROLL – TEK DOĞRU YÖNTEM)
            print("   🌱 Florence Life infinite scroll")
            life_links = self.collect_florence_life_links_scroll()
            before = len(all_links)

            all_links.extend(life_links)
            all_links = list(dict.fromkeys(all_links))

            print(f"      +{len(all_links) - before} Florence Life makale linki")

        # ---------------- Default ----------------
        else:
            all_links = self.collect_links_basic(list_url, scroll_steps=6)

        return all_links
    
    def collect_florence_life_links_scroll(self, max_rounds=15) -> list[str]:
        url = "https://www.florence.com.tr/florence-life"
        self.driver.get(url)
        self._wait_ready()
        time.sleep(1)
        self._try_accept_cookies()

        all_links = set()
        stable_rounds = 0
        last_count = 0

        for i in range(max_rounds):
            # 🔽 scroll tetikleyici
            self.driver.execute_script(
                "window.scrollBy(0, window.innerHeight * 1.8);"
            )
            time.sleep(1.5)

            links = self.collect_florence_article_links()
            for l in links:
                all_links.add(l)

            print(f"      🔁 Scroll {i + 1}: toplam {len(all_links)}")

            if len(all_links) == last_count:
                stable_rounds += 1
            else:
                stable_rounds = 0

            last_count = len(all_links)

            if stable_rounds >= 3:
                print("      ⛔ Florence Life: yeni içerik yok")
                break

        return list(all_links)


        # # elif site == "Florence":
        # #     seed_pages = [
        # #         "https://www.florence.com.tr/",
        # #         "https://www.florence.com.tr/guncel-saglik",
        # #         "https://www.florence.com.tr/iletisim",
        # #         "https://www.florence.com.tr/insan-kaynaklari",
        # #     ]

        # #     # 🔹 Normal seed sayfaları
        # #     for seed in seed_pages:
        # #         print(f"   🌱 Florence seed: {seed}")
        # #         self.driver.get(seed)
        # #         self._wait_ready()
        # #         time.sleep(0.6)
        # #         self._try_accept_cookies()

        # #         before = len(all_links)
        # #         links = self.collect_florence_article_links()
        # #         all_links.extend(links)
        # #         all_links = list(dict.fromkeys(all_links))
        # #         print(f"      +{len(all_links) - before} makale linki")

            # # 🔹 Florence Life pagination (ASIL EKSİK OLAN KISIM)
            # for page in range(1, max_pages + 1):
            #     page_url = f"https://www.florence.com.tr/florence-life?page={page}"
            #     print(f"   🌱 Florence Life page: {page_url}")

            #     self.driver.get(page_url)
            #     self._wait_ready()
            #     time.sleep(0.6)
            #     self._try_accept_cookies()

            #       # 🔽 JS render edilen kartlar için scroll
            #     for _ in range(4):
            #         self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            #         time.sleep(0.7)

            #     before = len(all_links)
            #     links = self.collect_florence_article_links()
            #     all_links.extend(links)
            #     all_links = list(dict.fromkeys(all_links))

            #     added = len(all_links) - before
            #     print(f"      +{added} makale linki")

            #     if added == 0 and page > 1:
            #         break

            # 🔹 Florence Life – INFINITE SCROLL (KALICI ÇÖZÜM)
            # print("   🌱 Florence Life infinite scroll")
            # self.driver.get("https://www.florence.com.tr/florence-life")
            # self._wait_ready()
            # time.sleep(1)
            # self._try_accept_cookies()

            # stable_rounds = 0
            # max_stable_rounds = 3

            # while True:
            #     self.driver.execute_script(
            #         "window.scrollBy(0, window.innerHeight * 2);"
            #     )
            #     time.sleep(1.2)

            #     before = len(all_links)
            #     links = self.collect_florence_article_links()
            #     all_links.extend(links)
            #     all_links = list(dict.fromkeys(all_links))

            #     added = len(all_links) - before
            #     print(f"      +{added} Florence Life makale linki")

            #     if added == 0:
            #         stable_rounds += 1
            #     else:
            #         stable_rounds = 0

            #     if stable_rounds >= max_stable_rounds:
            #         print("   ⛔ Florence Life: yeni içerik yok, duruldu")
            #         break
           

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
            time.sleep(random.uniform(0.10, 0.25))
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

        if site == "ClinicWise":
            title = self._pick_first_text(
                soup,
                ["article h1", ".blog-title", "h1"]
            )

            # ❌ title yoksa veya çok kısa ise → içerik değildir
            if not title or len(title) < 10:
                return None, None

            date = self._pick_first_text(
                soup,
                ["time", ".post-date", ".published-date"]
            )
            return title, date   # 🔥 EN ÖNEMLİ SATIR

        # fallback (diğer siteler için)
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
        title, date = self.scrape_detail_fast(site, url)
        if title or date:
            return title, date

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

    # ---------- DB HELPERS ----------
    def get_existing_urls_for_candidates(self, site_adi: str, candidate_urls: list[str]) -> set[str]:
        existing = set()
        if not candidate_urls:
            return existing

        for i in range(0, len(candidate_urls), CHUNK_IN_LIMIT):
            chunk = candidate_urls[i:i + CHUNK_IN_LIMIT]
            try:
                res = (
                    sb.table("articles")
                    .select("url")
                    .eq("site_adi", site_adi)
                    .in_("url", chunk)
                    .execute()
                )
                for r in (res.data or []):
                    u = r.get("url")
                    if u:
                        existing.add(u)
            except Exception:
                print(f"⚠️ DB in_ chunk sorgusu hata verdi (site={site_adi}, chunk={i}//{len(candidate_urls)})")

        return existing

    # ---------- LINKS ONLY ----------
    def scrape_site_links_only(self, target: dict) -> list[dict]:
        print(f"\n🔍 {target['site']} -> {target['list_url']}")
        all_links = self.collect_links_with_pagination(target, max_pages=MAX_PAGES)
        print(f"🔗 Toplanan toplam link: {len(all_links)}")

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
            elif target["site"] == "ClinicWise":
                if not is_valid_clinicwise_article_url(url):
                    continue


            candidate.append(url)

        candidate = list(dict.fromkeys(candidate))
        print(f"🧹 Filtre sonrası aday link: {len(candidate)}")

        t0 = time.time()
        existing = self.get_existing_urls_for_candidates(target["site"], candidate)
        print(f"⏱️ DB var-yok kontrol süresi: {time.time() - t0:.2f}s")

        new_links = [u for u in candidate if u not in existing]
        print(f"🧠 DB’de var: {len(existing)} | 🆕 Yeni makale: {len(new_links)}")

        results = [{
            "site_adi": target["site"],
            "baslik": None,
            "url": u,
            "yayin_tarihi": None,
            "keyword": keyword_from_title_or_slug(None, u),
            "detail_checked": False,  # ✅ yeni kayıt -> detay denenmemiş,
            "updated_at": datetime.utcnow().isoformat(),

        } for u in new_links]
        
        print(f"✅ DB’ye yazılacak yeni URL: {len(results)}")
        return results

    # ✅ GEREKSİZ TEKRAR YOK:
    # sadece detail_checked=false olanları dene, sonra true yap.
    def fill_missing_details(self, target: dict, batch_limit: int = 25) -> int:
        site_adi = target["site"]

        res = (
            sb.table("articles")
            .select("url,site_adi,baslik,yayin_tarihi,detail_checked")
            .eq("site_adi", site_adi)
            .eq("detail_checked", False)
            .limit(batch_limit)
            .execute()
        )
        rows = res.data or []
        if not rows:
            print(f"✅ {site_adi}: detay denenecek kayıt yok (detail_checked=false yok).")
            return 0

        print(f"🛠️ {site_adi}: detay denenecek kayıt: {len(rows)} (batch={batch_limit})")

        updates = []
        for idx, r in enumerate(rows, start=1):
            url = r["url"]
            old_title = r.get("baslik")
            old_date = r.get("yayin_tarihi")

            title, date = self.scrape_detail(site_adi, url)

            # tarih varsa yaz, yoksa NULL/eskisi kalsın
            final_title = title if title else old_title
            final_date = date if date else old_date

            kw = keyword_from_title_or_slug(final_title, url)

            updates.append({
                "site_adi": site_adi,
                "url": url,
                "baslik": final_title,
                "yayin_tarihi": final_date,
                "keyword": kw,
                "detail_checked": True,   # ✅ denendi -> bir daha deneme,
                "updated_at": datetime.utcnow().isoformat(),

            })
            print(f"➡️ ({idx}/{len(rows)}) Detay denendi: {url}")

        sb.table("articles").upsert(updates, on_conflict="url").execute()
        print(f"✅ {site_adi}: detay güncellendi (denendi): {len(updates)}")
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
       # updates.append({"site_adi": site_adi, "url": url, "keyword": kw})
        updates.append({
            "site_adi": site_adi,
            "url": url,
            "keyword": kw,
            "updated_at": datetime.utcnow().isoformat(),
        })


    sb.table("articles").upsert(updates, on_conflict="url").execute()
    print(f"✅ {site_adi}: keyword güncellendi: {len(updates)}")
    return len(updates)


def run():
    targets = [
        {"site": "Dentway", "domain": "dentway.com.tr", "list_url": "https://www.dentway.com.tr/blog/"},
        {"site": "Florence", "domain": "florence.com.tr", "list_url": "https://www.florence.com.tr/guncel-saglik"},
        {"site": "ClinicWise", "domain": "clinic-wise.com", "list_url": "https://clinic-wise.com/blog/"}
    ]

    scraper = BlogScraper(headless=HEADLESS)

    try:
        for t in targets:
            # MODE=keywords -> sadece keyword işi
            if MODE == "keywords":
                for _ in range(DETAIL_ROUNDS):
                    k = backfill_missing_keywords(t["site"], batch_limit=200)
                    if k == 0:
                        break
                continue

            # links
            if MODE in ("auto", "links"):
                rows = scraper.scrape_site_links_only(t)
                scraper.save_to_supabase(rows)

            # details
            if MODE in ("auto", "details"):
                if MODE == "auto" and not AUTO_DETAILS:
                    continue

                for _ in range(DETAIL_ROUNDS):
                    filled = scraper.fill_missing_details(t, batch_limit=DETAIL_BATCH_LIMIT)
                    if filled == 0:
                        break

    finally:
        print("\n⌛ Bitti. Tarayıcı kapanıyor...")
        scraper.close()


if __name__ == "__main__":
    run()
