#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Rebuild the Elasticsearch image search index from MySQL.

This is an operator script for existing data. New published images are indexed
incrementally by the backend after a successful publish transaction.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_MYSQL_HOST = os.environ.get("VIBELO_MYSQL_HOST", "127.0.0.1")
DEFAULT_MYSQL_PORT = int(os.environ.get("VIBELO_MYSQL_PORT", "3306") or "3306")
DEFAULT_MYSQL_DATABASE = os.environ.get("VIBELO_MYSQL_DATABASE", "rangwaz_image_dev")
DEFAULT_MYSQL_USER = os.environ.get("VIBELO_MYSQL_USER", "rangwaz")
DEFAULT_MYSQL_PASSWORD = os.environ.get("VIBELO_MYSQL_PASSWORD", "rangwaz123")

DEFAULT_ES_URL = os.environ.get("VIBELO_ES_URL", "http://127.0.0.1:9200")
DEFAULT_ES_INDEX = os.environ.get("VIBELO_ES_INDEX", "rangwaz-images")
DEFAULT_BATCH_SIZE = int(os.environ.get("VIBELO_SEARCH_BATCH_SIZE", "500") or "500")
DEFAULT_TIMEOUT_SECONDS = int(os.environ.get("VIBELO_ES_TIMEOUT_SECONDS", "30") or "30")


INDEX_DEFINITION: Dict[str, Any] = {
    "settings": {
        "index": {"max_ngram_diff": 4},
        "analysis": {
            "tokenizer": {
                "cjk_ngram_tokenizer": {
                    "type": "ngram",
                    "min_gram": 1,
                    "max_gram": 3,
                    "token_chars": ["letter", "digit"],
                }
            },
            "analyzer": {
                "cjk_ngram": {
                    "tokenizer": "cjk_ngram_tokenizer",
                    "filter": ["lowercase"],
                }
            },
        },
    },
    "mappings": {
        "properties": {
            "id": {"type": "long"},
            "authorId": {"type": "long"},
            "status": {"type": "keyword"},
            "title": {"type": "text", "analyzer": "cjk_ngram", "search_analyzer": "standard"},
            "content": {"type": "text", "analyzer": "cjk_ngram", "search_analyzer": "standard"},
            "description": {"type": "text", "analyzer": "cjk_ngram", "search_analyzer": "standard"},
            "authorUsername": {"type": "keyword"},
            "authorNickname": {"type": "text", "analyzer": "cjk_ngram", "search_analyzer": "standard"},
            "width": {"type": "integer"},
            "height": {"type": "integer"},
            "ratio": {"type": "keyword"},
            "orientation": {"type": "keyword"},
            "categories": {"type": "text", "analyzer": "cjk_ngram", "search_analyzer": "standard"},
            "tags": {"type": "text", "analyzer": "cjk_ngram", "search_analyzer": "standard"},
            "topics": {"type": "text", "analyzer": "cjk_ngram", "search_analyzer": "standard"},
            "intentKeywords": {"type": "keyword"},
            "suggestKeywords": {"type": "keyword"},
            "suggestText": {"type": "text", "analyzer": "cjk_ngram", "search_analyzer": "standard"},
            "fileUrl": {"type": "keyword", "index": False},
            "thumbnailUrl": {"type": "keyword", "index": False},
            "hotScore": {"type": "double"},
            "publishedAt": {"type": "date"},
            "createdAt": {"type": "date"},
        }
    },
}


SEARCH_DOCUMENT_SQL = """
SELECT i.id,
       i.author_id,
       i.title,
       i.content,
       i.description,
       i.status,
       i.file_url,
       i.thumbnail_url,
       i.width,
       i.height,
       i.ratio,
       u.username AS author_username,
       u.nickname AS author_nickname,
       c.name AS category_name,
       GROUP_CONCAT(DISTINCT t.name ORDER BY it.confidence DESC,t.name SEPARATOR ',') AS tags_csv,
       GROUP_CONCAT(DISTINCT tp.name ORDER BY tp.hot_score DESC,tp.name SEPARATOR ',') AS topics_csv,
       i.hot_score,
       i.published_at,
       i.created_at
FROM images i
LEFT JOIN app_users u ON u.id=i.author_id
LEFT JOIN categories c ON c.id=i.main_category_id
LEFT JOIN image_tags it ON it.image_id=i.id
LEFT JOIN tags t ON t.id=it.tag_id
LEFT JOIN image_topics ixt ON ixt.image_id=i.id
LEFT JOIN topics tp ON tp.id=ixt.topic_id
WHERE i.status='PUBLISHED' AND i.id>%s
GROUP BY i.id,i.author_id,i.title,i.content,i.description,i.status,i.file_url,i.thumbnail_url,
         i.width,i.height,i.ratio,
         u.username,u.nickname,c.name,i.hot_score,i.published_at,i.created_at
ORDER BY i.id
LIMIT %s
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild the Vibelo/RanGwaz Elasticsearch search index from MySQL.")
    parser.add_argument("--mysql-host", default=DEFAULT_MYSQL_HOST)
    parser.add_argument("--mysql-port", type=int, default=DEFAULT_MYSQL_PORT)
    parser.add_argument("--mysql-database", default=DEFAULT_MYSQL_DATABASE)
    parser.add_argument("--mysql-user", default=DEFAULT_MYSQL_USER)
    parser.add_argument("--mysql-password", default=DEFAULT_MYSQL_PASSWORD)
    parser.add_argument("--es-url", default=DEFAULT_ES_URL)
    parser.add_argument("--es-index", default=DEFAULT_ES_INDEX, help="Search alias/index used by the backend.")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--limit", type=int, default=0, help="Only index the first N rows; useful for smoke tests.")
    parser.add_argument("--no-recreate", action="store_true", help="Upsert into --es-index directly instead of building a versioned index and swapping the alias.")
    parser.add_argument("--replace-conflicting-index", action="store_true", help="Delete a concrete index that has the same name as the target alias before swapping.")
    parser.add_argument("--dry-run", action="store_true", help="Read data and print progress without writing to Elasticsearch.")
    return parser.parse_args()


def require_pymysql():
    try:
        import pymysql
    except Exception as exc:
        raise SystemExit("Missing dependency: python -m pip install pymysql\nOriginal error: {0}".format(exc)) from exc
    return pymysql


def connect_mysql(args: argparse.Namespace):
    pymysql = require_pymysql()
    return pymysql.connect(
        host=args.mysql_host,
        port=args.mysql_port,
        user=args.mysql_user,
        password=args.mysql_password,
        database=args.mysql_database,
        charset="utf8mb4",
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )


class Elasticsearch:
    def __init__(self, base_url: str, index: str, timeout_seconds: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.index = index
        self.timeout_seconds = timeout_seconds
        self.auth_header = self._auth_header()

    def _auth_header(self) -> Optional[str]:
        username = os.environ.get("VIBELO_ES_USERNAME", "")
        password = os.environ.get("VIBELO_ES_PASSWORD", "")
        if not username:
            return None
        token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        return "Basic " + token

    def status(self, method: str, path: str) -> int:
        try:
            with urlopen(self._request(method, path), timeout=self.timeout_seconds) as response:
                return int(response.status)
        except HTTPError as exc:
            return int(exc.code)
        except URLError as exc:
            raise SystemExit("Elasticsearch unavailable: {0}".format(exc)) from exc

    def json_request(self, method: str, path: str, body: Optional[Any] = None) -> Dict[str, Any]:
        payload = None
        headers = {"Accept": "application/json"}
        if body is not None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        return self._send(method, path, payload, headers)

    def ndjson_request(self, path: str, body: str) -> Dict[str, Any]:
        return self._send(
            "POST",
            path,
            body.encode("utf-8"),
            {"Accept": "application/json", "Content-Type": "application/x-ndjson"},
        )

    def ensure_index(self) -> None:
        status = self.status("HEAD", "/" + self.index)
        if status == 200:
            return
        if status != 404:
            raise SystemExit("Failed to check Elasticsearch index: HTTP {0}".format(status))
        self.create_index(self.index)

    def create_index(self, index_name: str) -> None:
        status = self.status("HEAD", "/" + index_name)
        if status == 200:
            raise SystemExit("Elasticsearch index already exists: {0}".format(index_name))
        if status != 404:
            raise SystemExit("Failed to check Elasticsearch index: HTTP {0}".format(status))
        self.json_request("PUT", "/" + index_name, INDEX_DEFINITION)

    def refresh(self, index_name: str) -> None:
        self.json_request("POST", "/" + index_name + "/_refresh")

    def count(self, index_name: str) -> int:
        response = self.json_request("GET", "/" + index_name + "/_count")
        return int(response.get("count", 0))

    def alias_indices(self, alias: str) -> List[str]:
        status = self.status("HEAD", "/_alias/" + alias)
        if status == 404:
            return []
        if status != 200:
            raise SystemExit("Failed to check Elasticsearch alias: HTTP {0}".format(status))
        response = self.json_request("GET", "/_alias/" + alias)
        return sorted(response.keys())

    def swap_alias(self, alias: str, new_index: str, replace_conflicting_index: bool) -> List[str]:
        old_indices = self.alias_indices(alias)
        if not old_indices and alias != new_index and self.status("HEAD", "/" + alias) == 200:
            if not replace_conflicting_index:
                raise SystemExit(
                    "Cannot create alias '{0}' because a concrete index with the same name exists. "
                    "Run again with --replace-conflicting-index, or use --no-recreate to write into it directly.".format(alias)
                )
            self.json_request("DELETE", "/" + alias)
        actions = [{"remove": {"index": old_index, "alias": alias}} for old_index in old_indices]
        actions.append({"add": {"index": new_index, "alias": alias}})
        self.json_request("POST", "/_aliases", {"actions": actions})
        return old_indices

    def _request(self, method: str, path: str, payload: Optional[bytes] = None, headers: Optional[Dict[str, str]] = None) -> Request:
        final_headers = dict(headers or {})
        if self.auth_header:
            final_headers["Authorization"] = self.auth_header
        return Request(self.base_url + path, data=payload, method=method, headers=final_headers)

    def _send(self, method: str, path: str, payload: Optional[bytes], headers: Dict[str, str]) -> Dict[str, Any]:
        try:
            with urlopen(self._request(method, path, payload, headers), timeout=self.timeout_seconds) as response:
                data = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise SystemExit("Elasticsearch request failed: {0} {1} -> HTTP {2}\n{3}".format(method, path, exc.code, detail)) from exc
        except URLError as exc:
            raise SystemExit("Elasticsearch unavailable: {0}".format(exc)) from exc
        return json.loads(data) if data else {}


def fetch_batch(conn, after_id: int, batch_size: int) -> List[Dict[str, Any]]:
    with conn.cursor() as cursor:
        cursor.execute("SET SESSION group_concat_max_len=65535")
        cursor.execute(SEARCH_DOCUMENT_SQL, (after_id, batch_size))
        return list(cursor.fetchall())


def split_csv(value: Optional[str]) -> List[str]:
    if not value:
        return []
    result: List[str] = []
    seen = set()
    for part in value.split(","):
        item = part.strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def compact(values: Iterable[Optional[str]]) -> str:
    result: List[str] = []
    seen = set()
    for value in values:
        if value is None:
            continue
        item = str(value).strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return " ".join(result)


def unique(values: Iterable[str]) -> List[str]:
    result: List[str] = []
    seen = set()
    for value in values:
        item = value.strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def orientation(width: Any, height: Any) -> str:
    try:
        w = float(width or 0)
        h = float(height or 0)
    except (TypeError, ValueError):
        return "unknown"
    if w <= 0 or h <= 0:
        return "unknown"
    ratio = w / h
    if 0.88 <= ratio <= 1.12:
        return "square"
    return "portrait" if ratio < 1 else "landscape"


def contains_any(text: str, values: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(value.lower() in lowered for value in values if value)


def derive_intent_keywords(row: Dict[str, Any], tags: List[str], topics: List[str], categories: List[str]) -> List[str]:
    text = compact(
        [
            row.get("title"),
            row.get("description"),
            row.get("content"),
            row.get("author_nickname"),
            row.get("category_name"),
            *tags,
            *topics,
            *categories,
        ]
    )
    orient = orientation(row.get("width"), row.get("height"))
    square_like = orient == "square"
    portrait_like = orient in {"portrait", "square"}
    portrait_subject = contains_any(
        text,
        [
            "人像", "人物", "女生", "女孩", "女性", "男生", "男孩", "男性", "自拍", "脸", "面部", "肖像",
            "头像", "动漫", "卡通", "插画", "二次元", "猫", "狗", "宠物", "动物",
            "portrait", "avatar", "girl", "boy", "anime", "cartoon", "cat", "dog", "pet",
        ],
    )
    background_subject = contains_any(
        text,
        ["壁纸", "背景", "风景", "自然", "天空", "海", "山", "森林", "花", "城市", "夜景", "极简", "wallpaper", "background", "landscape", "sky", "aesthetic"],
    )
    fashion_subject = contains_any(text, ["穿搭", "穿着", "服装", "衣服", "时尚", "街拍", "模特", "裙", "外套", "牛仔", "outfit", "fashion", "streetwear"])
    room_subject = contains_any(text, ["房间", "卧室", "客厅", "家居", "室内", "装修", "interior", "room", "home decor"])
    values: List[str] = []
    if portrait_like and portrait_subject:
        values += ["头像", "头像素材", "人像头像", "profile picture", "avatar"]
        if contains_any(text, ["女生", "女孩", "女性", "girl"]):
            values.append("女生头像")
        if contains_any(text, ["男生", "男孩", "男性", "boy"]):
            values.append("男生头像")
        if contains_any(text, ["动漫", "卡通", "插画", "二次元", "anime", "cartoon"]):
            values.append("卡通头像")
    if background_subject or (orient == "portrait" and not fashion_subject):
        values += ["壁纸", "高清壁纸", "背景图"]
        if orient == "portrait":
            values.append("手机壁纸")
        if contains_any(text, ["动漫", "插画", "二次元", "anime"]):
            values.append("动漫壁纸")
        if contains_any(text, ["自然", "风景", "天空", "海", "山", "森林", "landscape", "sky"]):
            values.append("自然壁纸")
    if fashion_subject:
        values += ["穿搭", "穿搭灵感", "时尚穿搭", "outfit"]
    if room_subject:
        values += ["房间设计", "家居灵感", "室内设计"]
    values.append(orient)
    return unique(values)


def json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def to_document(row: Dict[str, Any]) -> Dict[str, Any]:
    tags = split_csv(row.get("tags_csv"))
    topics = split_csv(row.get("topics_csv"))
    categories = [row["category_name"]] if row.get("category_name") else []
    intent_keywords = derive_intent_keywords(row, tags, topics, categories)
    suggest_keywords = unique([*intent_keywords, *categories, *tags, *topics])
    suggest_text = compact(
        [
            row.get("title"),
            row.get("description"),
            row.get("content"),
            row.get("author_nickname"),
            row.get("category_name"),
            *tags,
            *topics,
            *intent_keywords,
        ]
    )
    return {
        "id": row.get("id"),
        "authorId": row.get("author_id"),
        "status": row.get("status"),
        "title": row.get("title") or "",
        "content": row.get("content") or "",
        "description": row.get("description") or "",
        "authorUsername": row.get("author_username") or "",
        "authorNickname": row.get("author_nickname") or "",
        "width": row.get("width"),
        "height": row.get("height"),
        "ratio": row.get("ratio") or "",
        "orientation": orientation(row.get("width"), row.get("height")),
        "categories": categories,
        "tags": tags,
        "topics": topics,
        "intentKeywords": intent_keywords,
        "suggestKeywords": suggest_keywords,
        "suggestText": suggest_text,
        "fileUrl": row.get("file_url"),
        "thumbnailUrl": row.get("thumbnail_url"),
        "hotScore": float(row.get("hot_score") or 0),
        "publishedAt": json_value(row.get("published_at")),
        "createdAt": json_value(row.get("created_at")),
    }


def bulk_index(es: Elasticsearch, rows: List[Dict[str, Any]], target_index: str) -> None:
    lines: List[str] = []
    for row in rows:
        image_id = str(row["id"])
        lines.append(json.dumps({"index": {"_index": target_index, "_id": image_id}}, ensure_ascii=False))
        lines.append(json.dumps(to_document(row), ensure_ascii=False, default=json_value))
    response = es.ndjson_request("/_bulk", "\n".join(lines) + "\n")
    if not response.get("errors"):
        return
    failures = []
    for item in response.get("items", []):
        error = item.get("index", {}).get("error")
        if error:
            failures.append(error)
        if len(failures) >= 3:
            break
    raise SystemExit("Elasticsearch bulk index failed:\n{0}".format(json.dumps(failures, ensure_ascii=False, indent=2)))


def main() -> int:
    args = parse_args()
    batch_size = max(50, args.batch_size)
    limit = max(0, args.limit)
    es = Elasticsearch(args.es_url, args.es_index, args.timeout_seconds)

    print("MySQL: {0}:{1}/{2}".format(args.mysql_host, args.mysql_port, args.mysql_database))
    print("Elasticsearch: {0}/{1}".format(args.es_url.rstrip("/"), args.es_index))

    target_index = args.es_index
    if args.dry_run:
        print("Dry run: Elasticsearch writes are disabled.")
    elif args.no_recreate:
        es.ensure_index()
    else:
        target_index = "{0}-v{1}".format(args.es_index, datetime.now().strftime("%Y%m%d%H%M%S"))
        print("Building versioned Elasticsearch index: {0}".format(target_index))
        es.create_index(target_index)

    started_at = time.time()
    total = 0
    after_id = 0
    with connect_mysql(args) as conn:
        while True:
            current_batch_size = batch_size
            if limit and total + current_batch_size > limit:
                current_batch_size = limit - total
            if current_batch_size <= 0:
                break
            rows = fetch_batch(conn, after_id, current_batch_size)
            if not rows:
                break
            if not args.dry_run:
                bulk_index(es, rows, target_index)
            total += len(rows)
            after_id = int(rows[-1]["id"])
            print("Indexed {0} documents, last image id {1}".format(total, after_id))
            if limit and total >= limit:
                break

    if not args.dry_run:
        es.refresh(target_index)
        print("ES document count in {0}: {1}".format(target_index, es.count(target_index)))
        if not args.no_recreate:
            old_indices = es.swap_alias(args.es_index, target_index, args.replace_conflicting_index)
            print("Alias {0} now points to {1}".format(args.es_index, target_index))
            if old_indices:
                print("Old index versions kept: {0}".format(", ".join(old_indices)))
    elapsed = time.time() - started_at
    print("Done. Reindexed {0} published images in {1:.1f}s.".format(total, elapsed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
