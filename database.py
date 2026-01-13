import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("https://luvasrgohxomdnvjlurq.supabase.co")
SUPABASE_KEY = os.getenv("sb_publishable_HMjAf8LEe5XWMfOntj7jZA_ioiQVu7J")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL veya SUPABASE_KEY .env içinde yok/boş.")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def insert_blog(data):
    try:
        # data: dict veya list[dict] olabilir
        return supabase.table("articles").insert(data).execute()
    except Exception as e:
        print(f"Supabase Hatası: {e}")
        return None

def upsert_articles(data):
    try:
        # url unique ise on_conflict='url' kullan
        return supabase.table("articles").upsert(data, on_conflict="url").execute()
    except Exception as e:
        print(f"Supabase Upsert Hatası: {e}")
        return None
