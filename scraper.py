from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
import time
import re
from urllib.parse import urlparse, unquote


TR_STOPWORDS = {
    "ve","ile","icin","için","da","de","ta","te","mi","mı","mu","mü",
    "bir","bu","şu","o","en","cok","çok","gibi","nedir","nasil","nasıl",
    "ne","kadar","var","yok"
}

def _clean_text(s: str) -> str:
    s = unquote(s or "").strip().lower()
    s = re.sub(r"[^\w\sçğıöşü-]", " ", s, flags=re.UNICODE)
    s = s.replace("-", " ").replace("_", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _slug_from_url(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    slug = path.split("/")[-1] if path else ""
    return _clean_text(slug)

def generate_keyword(baslik: str, url: str) -> str:
    # 1) Başlık varsa onu kullan (kısa/temiz)
    t = _clean_text(baslik)
    if t:
        words = [w for w in t.split() if w not in TR_STOPWORDS and len(w) > 2]
        if not words:
            words = t.split()
        return " ".join(words[:4]).title()

    # 2) Başlık yoksa URL slug fallback
    slug = _slug_from_url(url)
    if slug:
        words = [w for w in slug.split() if w not in TR_STOPWORDS and len(w) > 2]
        return " ".join(words[:4]).title() if words else slug.title()

    return "Genel"

def make_driver(headless: bool = False):
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1400,900")
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

def get_dentway_blog_items(headless: bool = False):
    """
    Dentway blog sayfasından:
      - url
      - baslik (sayfada görünen)
      - keyword (baslik+slug fallback)
    döndürür.

    return: List[dict] -> [{"baslik":..., "url":..., "keyword":...}, ...]
    """
    driver = make_driver(headless=headless)
    wait = WebDriverWait(driver, 15)

    driver.get("https://www.dentway.com.tr/blog/")
    wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
    time.sleep(1)

    items = {}
    anchors = driver.find_elements(By.CSS_SELECTOR, "a[href]")

    for a in anchors:
        href = a.get_attribute("href")
        if not href:
            continue

        # blog post linklerini filtrele
        if "dentway.com.tr/blog/" not in href:
            continue
        if "/blog/page/" in href:
            continue

        clean_url = href.split("?")[0].split("#")[0].rstrip("/")

        # anchor text bazen başlık olur
        txt = (a.text or "").strip()
        if txt:
            # çok kısa metinler (örn "Devamını oku") olmasın
            if len(txt) < 6:
                txt = ""

        # aynı URL için en iyi başlığı tut
        if clean_url not in items:
            items[clean_url] = {"url": clean_url, "baslik": txt}
        else:
            # önceki boşsa yeni doluysa güncelle
            if not items[clean_url].get("baslik") and txt:
                items[clean_url]["baslik"] = txt

    driver.quit()

    result = []
    for url, obj in items.items():
        baslik = obj.get("baslik") or ""
        # başlık boşsa slug'dan başlık türetelim (daha düzgün görünür)
        if not baslik:
            baslik = _slug_from_url(url).replace(" ", " ").title()

        keyword = generate_keyword(baslik, url)
        result.append({"baslik": baslik, "url": url, "keyword": keyword})

    # stabil sıralama
    result.sort(key=lambda x: x["url"])
    return result
