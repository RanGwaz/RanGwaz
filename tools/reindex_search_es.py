#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Rebuild the Elasticsearch image search index from MySQL.

This is an operator script for existing data. New published images are indexed
incrementally by the backend after a successful publish transaction.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import time
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _env_value(primary: str, fallback: str, default: str) -> str:
    return os.environ.get(primary) or os.environ.get(fallback) or default


DEFAULT_MYSQL_HOST = _env_value("VIBELO_MYSQL_HOST", "VIBELO_DB_HOST", "127.0.0.1")
DEFAULT_MYSQL_PORT = int(_env_value("VIBELO_MYSQL_PORT", "VIBELO_DB_PORT", "3306"))
DEFAULT_MYSQL_DATABASE = _env_value("VIBELO_MYSQL_DATABASE", "VIBELO_DB_NAME", "rangwaz_image_dev")
DEFAULT_MYSQL_USER = _env_value("VIBELO_MYSQL_USER", "VIBELO_DB_USER", "vibelo_app")
DEFAULT_MYSQL_PASSWORD = _env_value("VIBELO_MYSQL_PASSWORD", "VIBELO_DB_PASSWORD", "")

DEFAULT_ES_URL = os.environ.get("VIBELO_ES_URL", "http://127.0.0.1:9200")
DEFAULT_ES_INDEX = os.environ.get("VIBELO_ES_INDEX", "rangwaz-images")
DEFAULT_BATCH_SIZE = int(os.environ.get("VIBELO_SEARCH_BATCH_SIZE", "500") or "500")
DEFAULT_TIMEOUT_SECONDS = int(os.environ.get("VIBELO_ES_TIMEOUT_SECONDS", "30") or "30")

CERTIFICATE_META_KEY = "vibelo_reindex_certificate"
CERTIFICATE_SCHEMA = "v1"
CERTIFICATE_STATUS = "verified"


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


@dataclass(frozen=True)
class DatasetFingerprint:
    document_count: int
    collection_fingerprint: str
    content_fingerprint: str


class DatasetFingerprintBuilder:
    def __init__(self) -> None:
        self._collection = hashlib.sha256()
        self._content = hashlib.sha256()
        self._document_count = 0

    @staticmethod
    def _add_frame(digest: Any, payload: bytes) -> None:
        digest.update(str(len(payload)).encode("ascii"))
        digest.update(b":")
        digest.update(payload)
        digest.update(b"\n")

    def add(self, document_id: str, source: Dict[str, Any]) -> None:
        encoded_id = str(document_id).encode("utf-8")
        encoded_document = json.dumps(
            {"_id": str(document_id), "_source": source},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=json_value,
        ).encode("utf-8")
        self._add_frame(self._collection, encoded_id)
        self._add_frame(self._content, encoded_document)
        self._document_count += 1

    def finish(self) -> DatasetFingerprint:
        return DatasetFingerprint(
            document_count=self._document_count,
            collection_fingerprint=self._collection.hexdigest(),
            content_fingerprint=self._content.hexdigest(),
        )


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
    parser.add_argument("--no-recreate", action="store_true", help="Deprecated unsafe mode; only accepted together with --dry-run.")
    parser.add_argument("--replace-conflicting-index", action="store_true", help="Atomically remove a concrete index that conflicts with the target alias during promotion.")
    parser.add_argument("--dry-run", action="store_true", help="Read data and print progress without writing to Elasticsearch.")
    parser.add_argument(
        "--confirm-promote",
        action="store_true",
        help="Required acknowledgement that a complete candidate index may replace the search alias.",
    )
    parser.add_argument(
        "--lock-name",
        default="vibelo-search-reindex",
        help="MySQL advisory lock used to prevent concurrent search reindex jobs.",
    )
    return parser.parse_args()


def require_pymysql():
    try:
        import pymysql
    except Exception as exc:
        raise SystemExit(
            "Missing fixed PyMySQL dependency; prepare and install it with the scripts under ops/public "
            "instead of using an online pip install.\nOriginal error: {0}".format(exc)
        ) from exc
    return pymysql


def connect_mysql(args: argparse.Namespace, autocommit: bool = True):
    pymysql = require_pymysql()
    return pymysql.connect(
        host=args.mysql_host,
        port=args.mysql_port,
        user=args.mysql_user,
        password=args.mysql_password,
        database=args.mysql_database,
        charset="utf8mb4",
        autocommit=autocommit,
        cursorclass=pymysql.cursors.DictCursor,
    )


def begin_consistent_snapshot(conn) -> None:
    with conn.cursor() as cursor:
        cursor.execute("SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")


@contextmanager
def consistent_snapshot(args: argparse.Namespace) -> Iterator[Any]:
    conn = connect_mysql(args, autocommit=False)
    try:
        begin_consistent_snapshot(conn)
        yield conn
    finally:
        try:
            conn.rollback()
        finally:
            conn.close()


def acquire_reindex_lock(conn, lock_name: str) -> None:
    if not lock_name or len(lock_name.encode("utf-8")) > 64:
        raise SystemExit("--lock-name must contain between 1 and 64 UTF-8 bytes")
    with conn.cursor() as cursor:
        cursor.execute("SELECT GET_LOCK(%s, 0) AS acquired", (lock_name,))
        row = cursor.fetchone()
    acquired = row.get("acquired") if isinstance(row, dict) else row[0]
    if int(acquired or 0) != 1:
        raise SystemExit("Another Elasticsearch reindex job holds MySQL lock: {0}".format(lock_name))


def release_reindex_lock(conn, lock_name: str) -> None:
    with conn.cursor() as cursor:
        cursor.execute("SELECT RELEASE_LOCK(%s) AS released", (lock_name,))
        cursor.fetchone()


def count_published(conn) -> int:
    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) AS published_count FROM images WHERE status='PUBLISHED'")
        row = cursor.fetchone()
    value = row.get("published_count") if isinstance(row, dict) else row[0]
    return int(value or 0)


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

    def fingerprint(self, index_name: str, batch_size: int) -> DatasetFingerprint:
        builder = DatasetFingerprintBuilder()
        search_after: Optional[List[Any]] = None
        page_size = max(50, min(batch_size, 1000))
        while True:
            body: Dict[str, Any] = {
                "size": page_size,
                "query": {"match_all": {}},
                "sort": [{"id": {"order": "asc", "unmapped_type": "long"}}],
                "_source": True,
                "track_total_hits": False,
            }
            if search_after is not None:
                body["search_after"] = search_after
            response = self.json_request("POST", "/" + index_name + "/_search", body)
            hits = response.get("hits", {}).get("hits", [])
            if not isinstance(hits, list):
                raise SystemExit("Elasticsearch fingerprint response does not contain a hit list")
            if not hits:
                break
            for hit in hits:
                document_id = hit.get("_id")
                source = hit.get("_source")
                if document_id is None or not isinstance(source, dict):
                    raise SystemExit("Elasticsearch fingerprint response contains an invalid document")
                builder.add(str(document_id), source)
            last_sort = hits[-1].get("sort")
            if not isinstance(last_sort, list) or not last_sort:
                raise SystemExit("Elasticsearch fingerprint response is missing search_after values")
            search_after = last_sort
        return builder.finish()

    def write_certificate(self, index_name: str, certificate: Dict[str, Any]) -> None:
        self.json_request(
            "PUT",
            "/" + index_name + "/_mapping",
            {"_meta": {CERTIFICATE_META_KEY: certificate}},
        )

    def certificates(self, index_or_alias: str) -> Dict[str, Dict[str, Any]]:
        response = self.json_request("GET", "/" + index_or_alias + "/_mapping")
        certificates: Dict[str, Dict[str, Any]] = {}
        for index_name, definition in response.items():
            mappings = definition.get("mappings", {}) if isinstance(definition, dict) else {}
            metadata = mappings.get("_meta", {}) if isinstance(mappings, dict) else {}
            certificate = metadata.get(CERTIFICATE_META_KEY) if isinstance(metadata, dict) else None
            if isinstance(certificate, dict):
                certificates[index_name] = certificate
        return certificates

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
        actions = [{"remove": {"index": old_index, "alias": alias}} for old_index in old_indices]
        if not old_indices and alias != new_index and self.status("HEAD", "/" + alias) == 200:
            if not replace_conflicting_index:
                raise SystemExit(
                    "Cannot create alias '{0}' because a concrete index with the same name exists. "
                    "Run again with --replace-conflicting-index to replace it atomically.".format(alias)
                )
            actions.append({"remove_index": {"index": alias}})
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


PreparedDocument = Tuple[str, Dict[str, Any]]


def prepare_documents(rows: List[Dict[str, Any]]) -> List[PreparedDocument]:
    return [(str(row["id"]), to_document(row)) for row in rows]


def bulk_index(es: Elasticsearch, documents: List[PreparedDocument], target_index: str) -> None:
    lines: List[str] = []
    for image_id, document in documents:
        lines.append(json.dumps({"index": {"_index": target_index, "_id": image_id}}, ensure_ascii=False))
        lines.append(json.dumps(document, ensure_ascii=False, default=json_value))
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


def scan_snapshot(
    conn,
    batch_size: int,
    limit: int = 0,
    consumer: Optional[Callable[[List[PreparedDocument]], None]] = None,
) -> DatasetFingerprint:
    builder = DatasetFingerprintBuilder()
    total = 0
    after_id = 0
    while True:
        current_batch_size = batch_size
        if limit and total + current_batch_size > limit:
            current_batch_size = limit - total
        if current_batch_size <= 0:
            break
        rows = fetch_batch(conn, after_id, current_batch_size)
        if not rows:
            break
        documents = prepare_documents(rows)
        for document_id, document in documents:
            builder.add(document_id, document)
        if consumer is not None:
            consumer(documents)
        total += len(documents)
        after_id = int(rows[-1]["id"])
        print("Read {0} documents, last image id {1}".format(total, after_id))
        if limit and total >= limit:
            break
    return builder.finish()


def verify_fingerprint(label: str, expected: DatasetFingerprint, actual: DatasetFingerprint) -> None:
    differences = []
    if actual.document_count != expected.document_count:
        differences.append("count {0} != {1}".format(actual.document_count, expected.document_count))
    if actual.collection_fingerprint != expected.collection_fingerprint:
        differences.append("collection SHA256 differs")
    if actual.content_fingerprint != expected.content_fingerprint:
        differences.append("content SHA256 differs")
    if differences:
        raise SystemExit("{0} verification failed: {1}".format(label, "; ".join(differences)))


def build_certificate(
    args: argparse.Namespace,
    target_index: str,
    source: DatasetFingerprint,
    candidate: DatasetFingerprint,
) -> Dict[str, Any]:
    return {
        "schema": CERTIFICATE_SCHEMA,
        "status": CERTIFICATE_STATUS,
        "published_count": source.document_count,
        "source_fingerprint": source.content_fingerprint,
        "collection_fingerprint": source.collection_fingerprint,
        "candidate_fingerprint": candidate.content_fingerprint,
        "target_alias": args.es_index,
        "target_index": target_index,
        "created_at_utc": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    }


def verify_certificate(
    es: Elasticsearch,
    index_or_alias: str,
    expected_index: str,
    expected_certificate: Dict[str, Any],
) -> None:
    certificates = es.certificates(index_or_alias)
    if certificates != {expected_index: expected_certificate}:
        raise SystemExit(
            "Elasticsearch certificate verification failed for {0}".format(index_or_alias)
        )


def verify_promoted_alias(
    es: Elasticsearch,
    alias: str,
    target_index: str,
    expected: DatasetFingerprint,
    certificate: Dict[str, Any],
    batch_size: int,
) -> None:
    indices = es.alias_indices(alias)
    if indices != [target_index]:
        raise SystemExit(
            "Promoted alias verification failed: {0} points to {1}, expected only {2}".format(
                alias,
                ",".join(indices) if indices else "nothing",
                target_index,
            )
        )
    if es.count(alias) != expected.document_count:
        raise SystemExit("Promoted alias count verification failed")
    verify_fingerprint("Promoted alias", expected, es.fingerprint(alias, batch_size))
    verify_certificate(es, alias, target_index, certificate)


def run_reindex(args: argparse.Namespace) -> int:
    if args.limit < 0:
        raise SystemExit("--limit must not be negative")
    if args.limit and not args.dry_run:
        raise SystemExit("--limit is only allowed with --dry-run; a partial candidate can never be promoted")
    if args.no_recreate and not args.dry_run:
        raise SystemExit("--no-recreate is disabled for writes; build and promote an isolated candidate index")
    if not args.dry_run and not args.confirm_promote:
        raise SystemExit("Promotion is disabled; rerun with --confirm-promote after reviewing the target settings")

    batch_size = max(50, args.batch_size)
    limit = max(0, args.limit)
    es = Elasticsearch(args.es_url, args.es_index, args.timeout_seconds)

    print("MySQL: {0}:{1}/{2}".format(args.mysql_host, args.mysql_port, args.mysql_database))
    print("Elasticsearch: {0}/{1}".format(args.es_url.rstrip("/"), args.es_index))

    target_index = "{0}-candidate-{1}".format(
        args.es_index,
        datetime.utcnow().strftime("%Y%m%d%H%M%S%f"),
    )
    if args.dry_run:
        print("Dry run: Elasticsearch writes are disabled.")
    else:
        print("Building candidate Elasticsearch index: {0}".format(target_index))

    started_at = time.time()
    total = 0
    with closing(connect_mysql(args, autocommit=True)) as lock_conn:
        lock_acquired = False
        try:
            acquire_reindex_lock(lock_conn, args.lock_name)
            lock_acquired = True
            with consistent_snapshot(args) as snapshot_conn:
                published_before = count_published(snapshot_conn)
                if not args.dry_run and published_before <= 0:
                    raise SystemExit("Refusing to promote an empty search index")
                if not args.dry_run:
                    es.create_index(target_index)
                    source_fingerprint = scan_snapshot(
                        snapshot_conn,
                        batch_size,
                        consumer=lambda documents: bulk_index(es, documents, target_index),
                    )
                else:
                    source_fingerprint = scan_snapshot(snapshot_conn, batch_size, limit=limit)

            total = source_fingerprint.document_count
            if (not args.dry_run or not limit) and total != published_before:
                raise SystemExit(
                    "Consistent RDS snapshot count mismatch: expected {0}, read {1}; candidate was not promoted".format(
                        published_before,
                        total,
                    )
                )

            if args.dry_run:
                print(
                    "Dry-run fingerprint: count={0}, collection_sha256={1}, content_sha256={2}".format(
                        source_fingerprint.document_count,
                        source_fingerprint.collection_fingerprint,
                        source_fingerprint.content_fingerprint,
                    )
                )
            else:
                es.refresh(target_index)
                indexed_count = es.count(target_index)
                if indexed_count != published_before:
                    raise SystemExit(
                        "Candidate Elasticsearch count mismatch: expected {0}, indexed {1}; candidate was not promoted".format(
                            published_before,
                            indexed_count,
                        )
                    )
                candidate_fingerprint = es.fingerprint(target_index, batch_size)
                verify_fingerprint("Candidate Elasticsearch index", source_fingerprint, candidate_fingerprint)

                with consistent_snapshot(args) as verification_conn:
                    published_after = count_published(verification_conn)
                    live_fingerprint = scan_snapshot(verification_conn, batch_size)
                if live_fingerprint.document_count != published_after:
                    raise SystemExit(
                        "Live RDS snapshot count mismatch: expected {0}, read {1}; candidate was not promoted".format(
                            published_after,
                            live_fingerprint.document_count,
                        )
                    )
                verify_fingerprint("RDS before-promotion snapshot", source_fingerprint, live_fingerprint)

                certificate = build_certificate(args, target_index, source_fingerprint, candidate_fingerprint)
                es.write_certificate(target_index, certificate)
                verify_certificate(es, target_index, target_index, certificate)
                print(
                    "Pre-promotion gates passed: count={0}, collection_sha256={1}, content_sha256={2}".format(
                        published_before,
                        source_fingerprint.collection_fingerprint,
                        source_fingerprint.content_fingerprint,
                    )
                )

                old_indices = es.swap_alias(args.es_index, target_index, args.replace_conflicting_index)
                verify_promoted_alias(
                    es,
                    args.es_index,
                    target_index,
                    source_fingerprint,
                    certificate,
                    batch_size,
                )
                print("Alias {0} now points only to verified index {1}".format(args.es_index, target_index))
                if old_indices:
                    print("Old index versions kept: {0}".format(", ".join(old_indices)))
        finally:
            if lock_acquired:
                release_reindex_lock(lock_conn, args.lock_name)

    elapsed = time.time() - started_at
    print("Done. Reindexed {0} published images in {1:.1f}s.".format(total, elapsed))
    return 0


def main() -> int:
    return run_reindex(parse_args())


if __name__ == "__main__":
    sys.exit(main())
