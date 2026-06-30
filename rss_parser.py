import feedparser
import json
import os
from datetime import datetime, timedelta

RSS_FEEDS = [
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://venturebeat.com/category/ai/feed/",
    "https://feeds.feedburner.com/mit-technology-review/",
    "https://www.theverge.com/ai-artificial-intelligence/rss/index.xml",
]

from paths import dpath
SEEN_FILE = dpath("seen_articles.json")


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)


def mark_seen(link):
    """Помечает одну статью как использованную (вызывается после выбора лучшей из пула)."""
    seen = load_seen()
    seen.add(link)
    save_seen(seen)


def fetch_latest_news(max_articles=3, persist=True):
    """
    Собирает свежие AI-новости. При persist=False (режим пула для выбора лучшей)
    статьи НЕ помечаются использованными — это делает вызывающий код через mark_seen()
    только для реально выбранной новости, чтобы не «сжигать» остальные.
    """
    seen = load_seen()
    articles = []
    cutoff = datetime.now() - timedelta(hours=48)

    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                if entry.link in seen:
                    continue
                # Check if recent enough
                published = entry.get("published_parsed")
                if published:
                    pub_dt = datetime(*published[:6])
                    if pub_dt < cutoff:
                        continue

                title = entry.get("title", "")
                summary = entry.get("summary", entry.get("description", ""))

                # Basic AI keyword filter
                keywords = ["ai", "artificial intelligence", "gpt", "llm",
                            "machine learning", "openai", "anthropic", "gemini",
                            "neural", "robot", "automation", "chatbot"]
                text_lower = (title + " " + summary).lower()
                if not any(kw in text_lower for kw in keywords):
                    continue

                articles.append({
                    "title": title,
                    "summary": summary[:1500],
                    "link": entry.link,
                    "source": feed.feed.get("title", url),
                })

                seen.add(entry.link)  # локальная защита от дублей в этом проходе

                if len(articles) >= max_articles:
                    if persist:
                        save_seen(seen)
                    return articles

        except Exception as e:
            print(f"[RSS] Error parsing {url}: {e}")

    if persist:
        save_seen(seen)
    return articles


if __name__ == "__main__":
    news = fetch_latest_news()
    for n in news:
        print(f"\n=== {n['title']} ===\n{n['summary'][:200]}...")
