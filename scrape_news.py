#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

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

KEYWORDS = [
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
]

# Компилируем регулярки один раз
KEYWORD_RE = re.compile("|".join(KEYWORDS), re.IGNORECASE | re.UNICODE)

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)
TIMEOUT = 25


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
    except Exception:
        return []


def save_news(items: list):
    # Удаляем старше KEEP_DAYS
    cutoff = datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)
    filtered = []
    seen = set()

    for item in items:
        link = item.get("link", "").strip()
        if not link or link in seen:
            continue
        seen.add(link)

        # дата
        try:
            dt = datetime.fromisoformat(item["date"].replace("Z", "+00:00"))
        except Exception:
            dt = datetime.now(timezone.utc)

        if dt < cutoff:
            continue

        item["date"] = dt.isoformat()
        filtered.append(item)

    # Сортируем новые сверху
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
    print(f"Сохранено {len(filtered)} новостей")


def fetch(url: str) -> str | None:
    try:
        r = SESSION.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        return r.text
    except Exception as e:
        print(f"[ERROR] {url}: {e}")
        return None


# ================== ПАРСЕРЫ САЙТОВ ==================

def parse_interfax(html: str, base: str = "https://www.interfax.ru") -> list:
    soup = BeautifulSoup(html, "lxml")
    items = []

    # Основные блоки новостей на главной
    for a in soup.select("a"):
        title = normalize_text(a.get_text())
        href = a.get("href") or ""
        if not title or len(title) < 25:
            continue
        if not matches_keywords(title):
            continue

        link = urljoin(base, href)
        if "interfax.ru" not in urlparse(link).netloc:
            continue
        # отсекаем служебные ссылки
        if any(x in link for x in ["/rss", "/photo", "/video", "javascript:"]):
            continue

        items.append({
            "title": title,
            "link": link,
            "source": "Интерфакс",
            "date": datetime.now(timezone.utc).isoformat(),
        })
    return items


def parse_kommersant(html: str, base: str = "https://www.kommersant.ru") -> list:
    soup = BeautifulSoup(html, "lxml")
    items = []

    # Заголовки в ленте финансов / главной
    for a in soup.select("a.u-link, a[href*='/doc/'], h2 a, h3 a, .rubric_lenta a"):
        title = normalize_text(a.get_text())
        href = a.get("href") or ""
        if not title or len(title) < 20:
            continue
        if not matches_keywords(title):
            continue

        link = urljoin(base, href)
        if "kommersant.ru" not in urlparse(link).netloc:
            continue

        items.append({
            "title": title,
            "link": link,
            "source": "Коммерсантъ",
            "date": datetime.now(timezone.utc).isoformat(),
        })
    return items


def parse_finam(html: str, base: str = "https://www.finam.ru") -> list:
    soup = BeautifulSoup(html, "lxml")
    items = []

    for a in soup.select("a"):
        title = normalize_text(a.get_text())
        href = a.get("href") or ""
        if not title or len(title) < 20:
            continue
        if not matches_keywords(title):
            continue

        link = urljoin(base, href)
        if "finam.ru" not in urlparse(link).netloc:
            continue
        # новости обычно лежат в /publications/ или /analysis/ и т.п.
        if not any(x in link for x in ["/publications/", "/analysis/", "/news/", "/outlook/"]):
            continue

        items.append({
            "title": title,
            "link": link,
            "source": "Финам",
            "date": datetime.now(timezone.utc).isoformat(),
        })
    return items


def parse_bloomberg(html: str, base: str = "https://www.bloomberg.com") -> list:
    soup = BeautifulSoup(html, "lxml")
    items = []

    for a in soup.select("a"):
        title = normalize_text(a.get_text())
        href = a.get("href") or ""
        if not title or len(title) < 25:
            continue
        if not matches_keywords(title):
            continue

        link = urljoin(base, href)
        if "bloomberg.com" not in urlparse(link).netloc:
            continue
        if "/news/" not in link and "/articles/" not in link:
            continue

        items.append({
            "title": title,
            "link": link,
            "source": "Bloomberg",
            "date": datetime.now(timezone.utc).isoformat(),
        })
    return items


# ================== ОСНОВНОЙ ПРОЦЕСС ==================

def main():
    print("Старт сканирования...")
    existing = load_existing()
    new_items = []

    sources = [
        ("https://www.interfax.ru/", parse_interfax),
        ("https://www.interfax.ru/business", parse_interfax),
        ("https://www.kommersant.ru/finance", parse_kommersant),
        ("https://www.kommersant.ru/finance?page=2", parse_kommersant),
        ("https://www.kommersant.ru/finance?page=3", parse_kommersant),
        ("https://www.finam.ru/", parse_finam),
        ("https://www.finam.ru/analysis/newsitem/", parse_finam),
        ("https://www.bloomberg.com/europe", parse_bloomberg),
        ("https://www.bloomberg.com/markets", parse_bloomberg),
    ]

    for url, parser in sources:
        print(f"→ {url}")
        html = fetch(url)
        if not html:
            continue
        try:
            found = parser(html)
            print(f"  найдено подходящих: {len(found)}")
            new_items.extend(found)
        except Exception as e:
            print(f"  ошибка парсера: {e}")
        time.sleep(1.5)  # вежливая задержка

    # Объединяем со старыми
    all_items = existing + new_items
    save_news(all_items)
    print("Готово.")


if __name__ == "__main__":
    main()
