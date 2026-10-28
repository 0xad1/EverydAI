from html import unescape
import json
import hashlib
import logging
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import feedparser


# Project paths
ROOT = Path(__file__).resolve().parent.parent
FEEDS_FILE = ROOT / "scripts" / "feeds.json"
OUTPUT_FILE = ROOT / "src" / "_data" / "articles.json"

# Keep the first version focused on recent stories.
MAX_AGE_DAYS = 7
MAX_ARTICLES_PER_FEED = 30

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s"
)


def load_feeds():
    """Load configured RSS/Atom feeds."""
    with FEEDS_FILE.open("r", encoding="utf-8") as file:
        feeds = json.load(file)

    if not isinstance(feeds, list):
        raise ValueError("feeds.json must contain a list of feeds.")

    return feeds


def clean_text(value):
    """Remove HTML markup and decode HTML entities."""
    value = unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def clean_url(url):
    """Remove common tracking parameters from an article URL."""
    if not url:
        return ""

    parts = urlsplit(url.strip())
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
        and key.lower() not in {
            "fbclid", "gclid", "mc_cid", "mc_eid"
        }
    ]

    return urlunsplit((
        parts.scheme.lower(),
        parts.netloc.lower(),
        parts.path.rstrip("/") or "/",
        urlencode(query),
        ""
    ))


def parse_published(entry):
    """Return a normalised UTC timestamp, or None."""
    parsed = entry.get("published_parsed") or entry.get(
        "updated_parsed"
    )

    if parsed:
        from calendar import timegm
        timestamp = timegm(parsed)
        return datetime.fromtimestamp(
            timestamp, tz=timezone.utc
        )

    for field in ("published", "updated", "created"):
        raw = entry.get(field)

        if not raw:
            continue

        try:
            dt = parsedate_to_datetime(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except (TypeError, ValueError, OverflowError):
            continue

    return None


def make_article(entry, feed):
    """Convert a feed entry into our standard article format."""
    title = clean_text(entry.get("title", ""))
    url = clean_url(entry.get("link", ""))

    if not title or not url:
        return None

    summary = clean_text(
        entry.get("summary", "")
        or entry.get("description", "")
    )

    published = parse_published(entry)

    # Prefer stable feed IDs; fall back to the canonical URL.
    identity = (
        entry.get("id")
        or entry.get("guid")
        or url
    )

    article_id = hashlib.sha256(
        str(identity).encode("utf-8")
    ).hexdigest()[:16]

    return {
        "id": article_id,
        "title": title,
        "url": url,
        "source": feed["name"],
        "category": feed["category"],
        "published": published.isoformat()
        if published else None,
        "summary": summary[:1200],
        "collected_at": datetime.now(
            timezone.utc
        ).isoformat()
    }


def collect_articles():
    feeds = load_feeds()
    articles_by_url = {}
    now = datetime.now(timezone.utc)
    cutoff = now.timestamp() - MAX_AGE_DAYS * 86400

    for feed in feeds:
        logging.info("Fetching %s", feed["name"])

        try:
            parsed = feedparser.parse(
                feed["url"],
                request_headers={
                    "User-Agent": "EverydAI/1.0 personal-news-reader"
                }
            )

            if parsed.bozo:
                logging.warning(
                    "Feed warning for %s: %s",
                    feed["name"],
                    parsed.get("bozo_exception", "Unknown issue")
                )

            if parsed.get("status", 0) >= 400:
                logging.warning(
                    "HTTP %s from %s",
                    parsed.status,
                    feed["name"]
                )
                continue

            if not parsed.entries:
                logging.warning(
                    "No entries returned by %s",
                    feed["name"]
                )
                continue

            count = 0

            for entry in parsed.entries:
                article = make_article(entry, feed)

                if not article:
                    continue

                published = parse_published(entry)

                # Retain undated stories, since some feeds omit dates.
                if published and published.timestamp() < cutoff:
                    continue

                if article["url"] not in articles_by_url:
                    articles_by_url[article["url"]] = article
                    count += 1

                if count >= MAX_ARTICLES_PER_FEED:
                    break

            logging.info(
                "Collected %s candidate articles from %s",
                count,
                feed["name"]
            )

        except Exception as exc:
            logging.exception(
                "Could not process %s: %s",
                feed["name"],
                exc
            )

    articles = list(articles_by_url.values())

    # Newest dated stories first; undated stories go last.
    articles.sort(
        key=lambda article: article["published"] or "",
        reverse=True
    )

    return articles


def main():
    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    articles = collect_articles()

    with OUTPUT_FILE.open("w", encoding="utf-8") as file:
        json.dump(
            articles,
            file,
            indent=2,
            ensure_ascii=False
        )
        file.write("\n")

    logging.info(
        "Saved %s articles to %s",
        len(articles),
        OUTPUT_FILE.relative_to(ROOT)
    )


if __name__ == "__main__":
    main()
