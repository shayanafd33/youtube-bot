"""Collect today's trending topics from Google Trends (UK) and BBC News RSS."""
import feedparser

FEEDS = {
    "Google Trends UK": "https://trends.google.com/trending/rss?geo=GB",
    "BBC News": "https://feeds.bbci.co.uk/news/rss.xml",
    "BBC Science": "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
}


def _clean(text):
    return " ".join((text or "").replace("\n", " ").split())


def fetch_candidates(limit_per_feed=12):
    """Return a list of {source, title, summary} dicts. Never raises on a bad feed."""
    items = []
    for source, url in FEEDS.items():
        try:
            feed = feedparser.parse(url)
        except Exception as e:  # network or parse problem: skip this feed
            print(f"  feed failed: {source} ({e})")
            continue
        for entry in feed.entries[:limit_per_feed]:
            summary = _clean(entry.get("summary", ""))
            # Google Trends entries carry related news headlines in extra fields
            extra = [
                _clean(entry.get(k, ""))
                for k in ("ht_news_item_title", "ht_news_item_snippet")
                if entry.get(k)
            ]
            if extra:
                summary = (summary + " " + " | ".join(extra)).strip()
            items.append({
                "source": source,
                "title": _clean(entry.get("title", "")),
                "summary": summary[:400],
            })
    print(f"  collected {len(items)} trending items")
    return items
