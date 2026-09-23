import fcntl
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse
from database import record_first_visit

import pika
import requests
from bs4 import BeautifulSoup


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)

RABBITMQ_URL = os.getenv(
    "RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/%2F"
)
QUEUE_NAME = os.getenv("RABBITMQ_QUEUE", "crawler")
OUTPUT_FILE = Path(os.getenv("OUTPUT_FILE", "/data/articles.jsonl"))
VISITED_DB = Path(os.getenv("VISITED_DB", "/data/visited.sqlite3"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))
ALLOWED_DOMAIN = os.getenv("ALLOWED_DOMAIN", "idnes.cz").lower()

IDNES_COOKIES = {
    "dCMP": (
        "mafra=1111,all=1,reklama=1,part=0,cpex=1,google=1,gemius=1,id5=1,"
        "next=0000,onlajny=0000,jenzeny=0000,databazeknih=0000,"
        "autojournal=0000,skodahome=0000,skodaklasik=0000,groupm=1,piano=1,"
        "seznam=1,geozo=0,czaid=1,click=1,verze=2,"
    )
}


def decode_message_url(body: bytes) -> str:
    text = body.decode("utf-8").strip()
    try:
        message = json.loads(text)
    except json.JSONDecodeError:
        return text
    if not isinstance(message, dict) or not isinstance(message.get("url"), str):
        raise ValueError('JSON message must contain a string field named "url"')
    return message["url"]


def clean_url(url: str) -> str:
    return urldefrag(url.strip())[0]


# User-agent: * rules from https://www.idnes.cz/robots.txt (2026-09-05).
# Keep wildcard and end-anchor semantics; longest matching rule wins.
ROBOTS_DISALLOW = (
    "/*/diskuse*reakce=", "/*/diskuse*vlakno=", "/*/diskuse*strana=",
    "/*/diskuse/", "/*/diskuse*razeni=", "/*/tisk$", "/*/ankety/",
    "/ankety.aspx*hlasuj", "/export/", "/data.aspx", "/*/undefined",
    "/_servix/*", "*/redir.aspx", "*/Redir.aspx", "*?setver=", "*&setver=",
)
ROBOTS_ALLOW = ("/*/diskuse$",)


def is_robots_allowed(url: str) -> bool:
    parsed = urlparse(url)
    target = parsed.path or "/"
    if parsed.query:
        target += "?" + parsed.query
    matches = []
    for allowed, rules in ((False, ROBOTS_DISALLOW), (True, ROBOTS_ALLOW)):
        for rule in rules:
            anchored = rule.endswith("$")
            pattern = rule[:-1] if anchored else rule
            regex = "^" + re.escape(pattern).replace(r"\*", ".*")
            if anchored:
                regex += "$"
            if re.search(regex, target):
                matches.append((len(pattern.replace("*", "")), allowed))
    return max(matches)[1] if matches else True


def is_crawlable_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    # Restrict the article crawl to the main site, not TV schedules or other apps.
    if host not in {ALLOWED_DOMAIN, f"www.{ALLOWED_DOMAIN}"}:
        return False
    if parsed.username or parsed.password or parsed.port not in (None, 80, 443):
        return False
    path = parsed.path.lower()
    if path == "/ucet" or path.startswith("/ucet/"):
        return False
    # Discussions are outside the article crawl even when robots.txt allows them.
    if re.search(r"/(?:diskuse|ankety)(?:/|$)", path):
        return False
    return (
        parsed.scheme in {"http", "https"}
        and is_robots_allowed(url)
        and not re.search(
            r"\.(?:jpg|jpeg|png|gif|webp|svg|css|js|pdf|zip|mp4|mp3)$",
            path,
            re.IGNORECASE,
        )
    )


# `record_first_visit` is provided by database.py (Postgres or SQLite fallback)


def read_meta_content(soup: BeautifulSoup, *names: str) -> str | None:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find(
            "meta", attrs={"name": name}
        )
        if tag and tag.get("content"):
            return tag["content"].strip()
    return None


def extract_article(soup: BeautifulSoup, url: str) -> dict | None:
    article_node = soup.find("article")
    article_type = read_meta_content(soup, "og:type")
    if article_node is None and article_type != "article":
        return None

    content_root = article_node or soup
    paragraphs = [
        paragraph.get_text(" ", strip=True)
        for paragraph in content_root.find_all("p")
        if paragraph.get_text(" ", strip=True)
    ]
    if not paragraphs:
        return None

    title = read_meta_content(soup, "og:title")
    if not title:
        heading = content_root.find("h1")
        title = heading.get_text(" ", strip=True) if heading else None

    page_text = content_root.get_text(" ", strip=True)
    comment_match = re.search(r"(\d+)\s*(?:komentář|komentáře|komentářů)", page_text, re.I)

    return {
        "url": url,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "title": title,
        "category": read_meta_content(soup, "article:section"),
        "comment_count": int(comment_match.group(1)) if comment_match else None,
        "photo_count": len(content_root.find_all("img")),
        "content": "\n\n".join(paragraphs),
        "created_at": read_meta_content(
            soup, "article:published_time", "datePublished", "date"
        ),
    }


def fetch_page(url: str) -> tuple[dict | None, list[str]]:
    # Check every redirect before requesting it, so blocked destinations are not fetched.
    for _ in range(10):
        if not is_crawlable_url(url):
            return None, []
        response = requests.get(
            url,
            cookies=IDNES_COOKIES,
            headers={"User-Agent": "crawler-school/1.0"},
            timeout=REQUEST_TIMEOUT,
            allow_redirects=False,
        )
        if response.is_redirect:
            url = clean_url(urljoin(url, response.headers["Location"]))
            continue
        response.raise_for_status()
        break
    else:
        raise requests.TooManyRedirects("Too many redirects")
    final_url = clean_url(response.url)
    soup = BeautifulSoup(response.text, "html.parser")

    links = {
        clean_url(urljoin(final_url, anchor["href"]))
        for anchor in soup.find_all("a", href=True)
    }
    return extract_article(soup, final_url), sorted(filter(is_crawlable_url, links))


def write_article(article: dict) -> None:
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_FILE.open("a", encoding="utf-8") as output:
        fcntl.flock(output, fcntl.LOCK_EX)
        try:
            output.write(json.dumps(article, ensure_ascii=False) + "\n")
            output.flush()
        finally:
            fcntl.flock(output, fcntl.LOCK_UN)


def enqueue_links(channel, links: list[str]) -> None:
    properties = pika.BasicProperties(
        delivery_mode=pika.DeliveryMode.Persistent,
        content_type="application/json",
    )
    for link in links:
        channel.basic_publish(
            exchange="",
            routing_key=QUEUE_NAME,
            body=json.dumps({"url": link}),
            properties=properties,
        )


def handle_message(channel, method, properties, body):
    try:
        url = clean_url(decode_message_url(body))
        if not is_crawlable_url(url) or not record_first_visit(url):
            channel.basic_ack(delivery_tag=method.delivery_tag)
            return

        logging.info("Scraping %s", url)
        article, links = fetch_page(url)
        enqueue_links(channel, links)
        if article:
            write_article(article)
            logging.info("Saved article %s", article["url"])
        logging.info("Published %d discovered links", len(links))
        channel.basic_ack(delivery_tag=method.delivery_tag)
    except (ValueError, requests.RequestException, OSError) as error:
        logging.error("Message failed: %s", error)
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def run_worker():
    while True:
        try:
            connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
            channel = connection.channel()
            channel.queue_declare(queue=QUEUE_NAME, durable=True)
            channel.basic_qos(prefetch_count=1)
            channel.basic_consume(queue=QUEUE_NAME, on_message_callback=handle_message)
            logging.info("Waiting for messages on queue %s", QUEUE_NAME)
            channel.start_consuming()
        except (pika.exceptions.AMQPError, OSError) as error:
            logging.warning("RabbitMQ unavailable (%s); retrying in 5 seconds", error)
            time.sleep(5)


if __name__ == "__main__":
    run_worker()
