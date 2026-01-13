from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time

def get_dentway_blog_links():
    options = webdriver.ChromeOptions()
    # options.add_argument("--headless=new")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    wait = WebDriverWait(driver, 15)

    driver.get("https://www.dentway.com.tr/blog/")
    wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
    time.sleep(1)

    # Sayfadaki tüm linkleri çek
    anchors = driver.find_elements(By.CSS_SELECTOR, "a[href]")
    links = set()

    for a in anchors:
        href = a.get_attribute("href")
        if href and "dentway.com.tr/blog/" in href and "/blog/page/" not in href:
            links.add(href.split("?")[0].split("#")[0])

    driver.quit()
    return sorted(list(links))
