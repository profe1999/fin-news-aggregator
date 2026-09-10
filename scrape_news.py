#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

# ================== НАСТРОЙКИ ==================
NEWS_FILE = Path("news.json")
KEEP_DAYS = 7

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}

# Ключевые слова (русский + английский)
KEYWORDS = [
    # русские
    r"мсфо", r"отчетност", r"отчётност", r"отчет\b", r"отчёт\b",
    r"отчитался", r"отчиталась", r"отчитались",
    r"денежн\w*\s+масс", r"\bм2\b", r"\bм2х\b", r"ипц",
    r"индекс\s+потребительских\s+цен",
    r"\bввп\b", r"инфляц", r"нефть", r"brent", r"\bгаз\b",
    r"ключев\w*\s+ставк", r"кредитован",
    r"зерно", r"пшениц", r"медь", r"алюминий", r"металл", r"золото",
    r"резервы\s+цб", r"золотовалютн\w*\s+резерв", r"международн\w*\s+резерв",
    r"валютн\w*\s+резерв",
    r"санкци", r"экспорт", r"опек", r"опек\+",
    r"делистинг", r"\bipo\b", r"\bspo\b", r"допэмисси",
    r"инвестиц", r"частн\w*\s+инвестор",
    r"дивиденд", r"чистая\s+прибыль", r"\bприбыль\b",

    # английские (для Bloomberg)
    r"\binflation\b", r"\bcpi\b", r"\bgdp\b", r"\boil\b", r"\bbrent\b",
    r"\bgas\b", r"\bgold\b", r"\bcopper\b", r"\baluminum\b", r"\bmetal",
    r"\bsanction", r"\bexport", r"\bopec", r"\bipo\b", r"\bspo\b",
    r"\bdividend", r"\bprofit", r"\bearnings", r"\brevenue",
    r"\breserve", r"\binterest rate", r"\bfed\b", r"\becb\b", r"\russia\b",
    r"\binvestment", r"\bdelisting", r"\brate cut", r"\brate hike",
]

KEYWORD_RE = re.compile("|".join(KEYWORDS), re.IGNORECASE | re.UNICODE)

SESSION = requests.Session()
SESSION.headers.update(HEADERS)
TIMEOUT = 30


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def matches_keywords(title: str) -> bool:
    return bool(KEYWORD_RE.search(title or ""))


def load_existing() -> list:
    if not NEWS_FILE.exists():
        return []
    try:
        data = json.loads(NEWS_FILE.read_text(encoding="utf-8"))
        return data.get("items", [])
    except Exception as e:
        print(f"[WARN] Не удалось прочитать news.json: {e}")
        return []


def save_news(items: list):
    cutoff = datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)
    filtered = []
    seen = set()

    for item in items:
        link = (item.get("link") or "").strip()
        if not link or link in seen:
            continue
        seen.add(link)

        try:
            dt = datetime.fromisoformat(item["date"].replace("Z", "+00:00"))
        except Exception:
            dt = datetime.now(timezone.utc)

        if dt < cutoff:
            continue

        item["date"] = dt.isoformat()
        filtered.append(item)

    filtered.sort(key=lambda x: x.get("date", ""), reverse=True)

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(filtered),
        "items": filtered,
    }
    NEWS_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n=== Сохранено {len(filtered)} новостей (за последние {KEEP_DAYS} дней) ===")


def parse_rss(url: str, source_name: str) -> list:
    """Парсинг RSS с подробными логами"""
    items = []
    print(f"\n→ RSS: {source_name}")
    print(f"  URL: {url}")

    try:
        # Сначала пробуем через requests (лучше контролируем заголовки)
        resp = SESSION.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
        content = resp.content

        feed = feedparser.parse(content)

        if feed.bozo:
            print(f"  [WARN] feedparser bozo: {feed.bozo_exception}")

        total = len(feed.entries)
        print(f"  Всего записей в ленте: {total}")

        matched = 0
        for entry in feed.entries:
            title = normalize_text(entry.get("title", ""))
            link = (entry.get("link") or "").strip()

            if not title or not link:
                continue

            if not matches_keywords(title):
                continue

            matched += 1

            published = entry.get("published_parsed") or entry.get("updated_parsed")
            if published:
                dt = datetime(*published[:6], tzinfo=timezone.utc)
            else:
                dt = datetime.now(timezone.utc)

            items.append({
                "title": title,
                "link": link,
                "source": source_name,
                "date": dt.isoformat(),
            })

        print(f"  Прошло фильтр ключевых слов: {matched}")

    except Exception as e:
        print(f"  [ERROR] {source_name}: {type(e).__name__}: {e}")

    return items


def main():
    print("=" * 60)
    print("Старт сканирования новостей")
    print("=" * 60)

    existing = load_existing()
    print(f"Уже было в news.json: {len(existing)} записей")

    new_items = []

    # ========== FINAM (RSS) ==========
    new_items.extend(parse_rss(
        "https://www.finam.ru/analysis/conews/rsspoint/",
        "Финам"
    ))
    new_items.extend(parse_rss(
        "https://www.finam.ru/international/advanced/rsspoint/",
        "Финам"
    ))

    # ========== BLOOMBERG (RSS) ==========
    new_items.extend(parse_rss(
        "https://feeds.bloomberg.com/markets/news.rss",
        "Bloomberg"
    ))
    new_items.extend(parse_rss(
        "https://feeds.bloomberg.com/economics/news.rss",
        "Bloomberg"
    ))

    # ========== INTERFAX (RSS — для надёжности) ==========
    new_items.extend(parse_rss(
        "https://www.interfax.ru/rss.asp",
        "Интерфакс"
    ))

    # ========== КОММЕРСАНТЪ (RSS) ==========
    new_items.extend(parse_rss(
        "https://www.kommersant.ru/RSS/news.xml",
        "Коммерсантъ"
    ))

    print("\n" + "=" * 60)
    print(f"Новых подходящих новостей собрано: {len(new_items)}")
    print("=" * 60)

    # Показываем примеры, что именно нашлось
    for src in ["Финам", "Bloomberg", "Интерфакс", "Коммерсантъ"]:
        count = sum(1 for x in new_items if x["source"] == src)
        print(f"  {src}: {count}")

    all_items = existing + new_items
    save_news(all_items)


if __name__ == "__main__":
    main()
