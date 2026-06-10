import feedparser
import google.generativeai as genai
import requests
import json
import os
import hashlib
from datetime import datetime

# ============================================================
#  CONFIG — GitHub Secrets থেকে নেবে, এখানে কিছু বদলাবেন না
# ============================================================
GEMINI_API_KEY     = os.environ["GEMINI_API_KEY"]
BLOGGER_BLOG_ID    = os.environ["BLOGGER_BLOG_ID"]
REFRESH_TOKEN      = os.environ["BLOGGER_REFRESH_TOKEN"]
CLIENT_ID          = os.environ["BLOGGER_CLIENT_ID"]
CLIENT_SECRET      = os.environ["BLOGGER_CLIENT_SECRET"]
PIXABAY_API_KEY    = os.environ.get("PIXABAY_API_KEY", "")
POSTS_PER_RUN      = int(os.environ.get("POSTS_PER_RUN", "3"))
POSTED_FILE        = "posted_urls.json"  # duplicate tracking file

SOCIAL_LINKS = {
    "facebook":  "https://www.facebook.com/profile.php?id=61584860372732",
    "youtube":   "https://www.youtube.com/havanews",
    "telegram":  "https://t.me/+mH1JDPAp9Ng5YTE1",
    "website":   "https://hawanewshawa.blogspot.com/",
    "instagram": "https://www.instagram.com/havanews",
    "threads":   "https://www.threads.com/@hawanewsbd?hl=en",
}

RSS_FEEDS = [
    {"url": "https://feeds.bbci.co.uk/sport/rss.xml",         "category": "Sports", "label": "⚽ Sports"},
    {"url": "https://www.espn.com/espn/rss/news",             "category": "Sports", "label": "⚽ Sports"},
    {"url": "https://www.skysports.com/rss/12040",            "category": "Sports", "label": "⚽ Sports"},
    {"url": "https://cointelegraph.com/rss",                  "category": "Crypto", "label": "₿ Crypto"},
    {"url": "https://coindesk.com/arc/outboundfeeds/rss/",    "category": "Crypto", "label": "₿ Crypto"},
    {"url": "https://decrypt.co/feed",                        "category": "Crypto", "label": "₿ Crypto"},
    {"url": "https://cryptonews.com/news/feed/",              "category": "Crypto", "label": "₿ Crypto"},
]

GEMINI_PROMPT = """You are an expert news writer. Rewrite the following English news into an engaging, high-quality, and SEO-friendly English blog post.

Rules:
1. Title: Create an attractive, catchy, and SEO-friendly English title.
2. Content: Write the content in clean HTML format using <h2>, <p>, <strong>, and <ul> tags.
3. Word Count: Write at least 400 words.
4. Conclusion: Include a nice concluding paragraph at the end.
5. Language: Strictly write everything in ENGLISH. No Bengali words at all.
6. Output: Provide the response ONLY in valid JSON format, nothing else — no markdown, no backticks:
{"title": "English title here", "content": "HTML content here", "tags": ["tag1","tag2","tag3"]}"""


# ============================================================
#  DUPLICATE TRACKING
# ============================================================
def load_posted():
    if os.path.exists(POSTED_FILE):
        with open(POSTED_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_posted(posted):
    with open(POSTED_FILE, "w") as f:
        json.dump(list(posted), f)


# ============================================================
#  RSS FETCH
# ============================================================
def fetch_all_items():
    items = []
    for feed in RSS_FEEDS:
        try:
            d = feedparser.parse(feed["url"])
            for entry in d.entries[:5]:
                link  = entry.get("link", "")
                title = entry.get("title", "")
                desc  = entry.get("summary", "")
                if not link or not title:
                    continue
                # image খোঁজো
                image = None
                if "media_content" in entry:
                    image = entry.media_content[0].get("url")
                elif "enclosures" in entry and entry.enclosures:
                    image = entry.enclosures[0].get("href")
                items.append({
                    "title": title,
                    "link": link,
                    "description": desc[:500],
                    "image": image,
                    "category": feed["category"],
                    "label": feed["label"],
                })
        except Exception as e:
            print(f"⚠️ Feed error ({feed['url']}): {e}")
    import random
    random.shuffle(items)
    return items


# ============================================================
#  GEMINI REWRITE
# ============================================================
def rewrite_with_gemini(item):
    import time
    genai.configure(api_key=GEMINI_API_KEY)

    models = [
        "gemini-2.0-flash-lite",
        "gemini-2.0-flash",
        "gemini-1.5-flash-8b",
        "gemini-2.5-flash",
    ]

    prompt = GEMINI_PROMPT + f"\n\nOriginal News:\nTitle: {item['title']}\nContent: {item['description']}"

    for model_name in models:
        for attempt in range(1, 4):
            try:
                print(f"🤖 Trying: {model_name} (attempt {attempt}/3)")
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(prompt)
                text = response.text.strip()

                # JSON extract
                import re
                text_clean = re.sub(r"```json|```", "", text).strip()
                match = re.search(r"\{[\s\S]*\}", text_clean)
                if match:
                    parsed = json.loads(match.group())
                    if parsed.get("title") and parsed.get("content"):
                        print(f"✅ Gemini OK: {model_name}")
                        return parsed

                # fallback
                return {"title": item["title"], "content": f"<p>{text}</p>", "tags": [item["category"]]}

            except Exception as e:
                err = str(e)
                if "429" in err or "quota" in err.lower() or "rate" in err.lower():
                    print(f"⚡ {model_name} rate limit, পরের model এ যাচ্ছি...")
                    break  # পরের model
                elif "503" in err:
                    wait = attempt * 10
                    print(f"⏳ {model_name} busy, {wait}s অপেক্ষা...")
                    time.sleep(wait)
                else:
                    print(f"⚠️ {model_name} error: {err}")
                    break

    print("❌ সব Gemini model fail হয়েছে।")
    return None


# ============================================================
#  IMAGE FINDER
# ============================================================
def find_image(item, tags):
    url = item.get("image")
    if url and re.search(r"\.(jpg|jpeg|png|webp|gif)", url, re.I):
        return url

    if PIXABAY_API_KEY:
        kw = " ".join((tags or [])[:2]) or item["category"]
        try:
            r = requests.get(
                "https://pixabay.com/api/",
                params={"key": PIXABAY_API_KEY, "q": kw, "image_type": "photo",
                        "orientation": "horizontal", "per_page": 5, "safesearch": "true"},
                timeout=10
            )
            hits = r.json().get("hits", [])
            if hits:
                return hits[0]["webformatURL"]
        except Exception as e:
            print(f"⚠️ Pixabay error: {e}")

    color = "f59e0b" if item["category"] == "Crypto" else "3b82f6"
    return f"https://placehold.co/800x400/{color}/ffffff?text={item['category']}+News"


# ============================================================
#  BLOGGER ACCESS TOKEN
# ============================================================
def get_access_token():
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": REFRESH_TOKEN,
        "grant_type":    "refresh_token",
    })
    return r.json()["access_token"]


# ============================================================
#  BLOGGER POST
# ============================================================
def create_blogger_post(rewritten, image_url, category, label):
    token = get_access_token()

    badge_color = "#f59e0b" if category == "Crypto" else "#3b82f6"
    badge_html  = f'<div style="margin-bottom:16px"><span style="background:{badge_color};color:#fff;padding:4px 12px;border-radius:20px;font-size:13px;font-weight:500">{label}</span></div>'

    img_html = f'<div style="text-align:center;margin-bottom:20px"><img src="{image_url}" alt="{rewritten["title"]}" style="max-width:100%;border-radius:8px;height:auto" /></div>' if image_url else ""

    social_html = f"""
    <hr style="border:0;border-top:1px solid #eee;margin:40px 0 20px" />
    <div style="font-family:sans-serif;font-size:15px;color:#555;">
      <strong>🔗 Follow Hawa News:</strong><br/><br/>
      📘 <a href="{SOCIAL_LINKS['facebook']}"  target="_blank" style="color:#3b82f6;font-weight:bold;text-decoration:none;">Facebook</a> |
      🎬 <a href="{SOCIAL_LINKS['youtube']}"   target="_blank" style="color:#ef4444;font-weight:bold;text-decoration:none;">YouTube</a> |
      📱 <a href="{SOCIAL_LINKS['telegram']}"  target="_blank" style="color:#0088cc;font-weight:bold;text-decoration:none;">Telegram</a> |
      🌐 <a href="{SOCIAL_LINKS['website']}"   target="_blank" style="color:#10b981;font-weight:bold;text-decoration:none;">Website</a> |
      📷 <a href="{SOCIAL_LINKS['instagram']}" target="_blank" style="color:#e1306c;font-weight:bold;text-decoration:none;">Instagram</a> |
      🧵 <a href="{SOCIAL_LINKS['threads']}"   target="_blank" style="color:#000;font-weight:bold;text-decoration:none;">Threads</a>
    </div>"""

    full_content = badge_html + img_html + rewritten["content"] + social_html

    labels = [category, label.replace("⚽ ", "").replace("₿ ", "")] + (rewritten.get("tags") or [])
    labels = list(dict.fromkeys(labels))[:10]

    body = {
        "title":   rewritten["title"],
        "content": full_content,
        "labels":  labels,
        "status":  "LIVE",
    }

    r = requests.post(
        f"https://www.googleapis.com/blogger/v3/blogs/{BLOGGER_BLOG_ID}/posts/",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=body
    )

    if r.status_code in (200, 201):
        url = r.json().get("url", "")
        print(f"✅ Blogger post হয়েছে: {url}")
        return url
    else:
        print(f"❌ Blogger error: {r.text}")
        return None


# ============================================================
#  MAIN
# ============================================================
import re

def main():
    print("🚀 Auto Blogger শুরু হয়েছে...")
    posted = load_posted()
    items  = fetch_all_items()
    print(f"📰 মোট {len(items)}টি news পাওয়া গেছে")

    count = 0
    for item in items:
        if count >= POSTS_PER_RUN:
            break
        if item["link"] in posted:
            print(f"⏭️ Skip (duplicate): {item['title']}")
            continue

        print(f"✍️ Processing: {item['title']}")
        rewritten = rewrite_with_gemini(item)
        if not rewritten:
            continue

        image_url = find_image(item, rewritten.get("tags"))
        post_url  = create_blogger_post(rewritten, image_url, item["category"], item["label"])
        if not post_url:
            continue

        posted.add(item["link"])
        save_posted(posted)
        count += 1
        print(f"✅ Posted ({count}/{POSTS_PER_RUN}): {rewritten['title']}")

    print(f"🏁 সম্পন্ন! এই run এ {count}টি post হয়েছে।")

if __name__ == "__main__":
    main()
