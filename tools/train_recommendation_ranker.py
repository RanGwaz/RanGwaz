#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Train the Vibelo home-feed ranking model from impressions or bootstrap item data."""

from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import pymysql

from recommendation_model_service import FEATURE_NAMES

BASE_DIR = Path(__file__).resolve().parent
MODEL_DIR = Path(os.environ.get("VIBELO_RECOMMENDATION_MODEL_DIR", BASE_DIR / "models" / "recommendation"))


def connect() -> pymysql.connections.Connection:
    return pymysql.connect(
        host=os.environ.get("VIBELO_DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("VIBELO_DB_PORT", "3306")),
        user=os.environ.get("VIBELO_DB_USER", "rangwaz"),
        password=os.environ.get("VIBELO_DB_PASSWORD", "rangwaz123"),
        database=os.environ.get("VIBELO_DB_NAME", "rangwaz_image_dev"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def clamp(value: float, low: float, high: float) -> float:
    if value is None or not math.isfinite(float(value)):
        return low
    return min(high, max(low, float(value)))


def freshness_score(published_at: Any) -> float:
    if not published_at:
        return 0.0
    age_hours = max(0.0, (datetime.now() - published_at).total_seconds() / 3600.0)
    return 24.0 / (age_hours + 24.0)


def engagement_score(row: Dict[str, Any]) -> float:
    hot = float(row.get("hot_score") or 0)
    interactions = (
        int(row.get("like_count") or 0) * 1.2
        + int(row.get("favorite_count") or 0) * 1.6
        + int(row.get("comment_count") or 0) * 1.1
        + int(row.get("share_count") or 0) * 1.3
        + int(row.get("view_count") or 0) * 0.08
    )
    return math.log1p(max(0.0, hot + interactions)) / 10.0


def metadata_quality_score(row: Dict[str, Any]) -> float:
    score = 0.0
    if row.get("description"):
        score += 0.4
    if row.get("main_category_id"):
        score += 0.25
    if row.get("ratio"):
        score += 0.15
    if row.get("thumbnail_url"):
        score += 0.2
    return score


def source_flags(source: str) -> Dict[str, float]:
    source = (source or "").lower()
    return {
        "source_vector": 1.0 if source == "vector" else 0.0,
        "source_tag": 1.0 if source == "tag" else 0.0,
        "source_topic": 1.0 if source == "topic" else 0.0,
        "source_category": 1.0 if source == "category" else 0.0,
        "source_follow": 1.0 if source == "follow" else 0.0,
        "source_global": 1.0 if source in {"global", "kafka", "mysql", ""} else 0.0,
    }


def feature_row(row: Dict[str, Any], source: str, recall_score: float, route_count: int, recently_seen: bool) -> Dict[str, float]:
    position = max(0, int(row.get("position_no") or 0))
    features = {
        "recall_score": clamp(recall_score, 0, 4),
        "route_count": float(max(0, min(route_count, 8))),
        "engagement_score": clamp(engagement_score(row), 0, 4),
        "freshness_score": clamp(freshness_score(row.get("published_at")), 0, 1),
        "metadata_quality_score": clamp(metadata_quality_score(row), 0, 2),
        "recently_seen": 1.0 if recently_seen else 0.0,
        "position_decay": 1.0 / math.sqrt(position + 1.0),
    }
    features.update(source_flags(source))
    return features


def behavior_samples(limit: int, days: int) -> Tuple[List[List[float]], List[float]]:
    sql = """
        SELECT
          fi.user_id,
          fi.visitor_id,
          fi.image_id,
          fi.position_no,
          fi.source,
          COALESCE(fi.score,0) AS recall_score,
          i.like_count,
          i.favorite_count,
          i.comment_count,
          i.share_count,
          i.view_count,
          i.hot_score,
          i.published_at,
          i.description,
          i.main_category_id,
          i.ratio,
          i.thumbnail_url,
          COALESCE(MAX(
            CASE ub.behavior_type
              WHEN 'favorite' THEN 1.0
              WHEN 'like' THEN 0.85
              WHEN 'comment' THEN 0.8
              WHEN 'share' THEN 0.8
              WHEN 'click' THEN 0.55
              WHEN 'view' THEN 0.35
              ELSE 0
            END
          ),0) AS label
        FROM feed_impressions fi
        JOIN images i ON i.id=fi.image_id
        LEFT JOIN user_behaviors ub
          ON ub.image_id=fi.image_id
         AND (
           (fi.user_id IS NOT NULL AND ub.user_id=fi.user_id)
           OR (fi.user_id IS NULL AND fi.visitor_id IS NOT NULL
               AND ub.user_id IS NULL AND ub.visitor_id=fi.visitor_id)
         )
         AND ub.created_at >= COALESCE(fi.occurred_at,fi.created_at)
         AND ub.created_at < DATE_ADD(COALESCE(fi.occurred_at,fi.created_at), INTERVAL 24 HOUR)
         AND ub.behavior_type IN ('favorite','like','comment','share','click','view')
        WHERE COALESCE(fi.occurred_at,fi.created_at) >= DATE_SUB(NOW(), INTERVAL %s DAY)
          AND COALESCE(fi.occurred_at,fi.created_at) < DATE_SUB(NOW(), INTERVAL 24 HOUR)
          AND i.status='PUBLISHED'
        GROUP BY fi.id
        ORDER BY COALESCE(fi.occurred_at,fi.created_at) ASC,fi.id ASC
        LIMIT %s
    """
    with connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, (days, limit))
            rows = cursor.fetchall()
    x: List[List[float]] = []
    y: List[float] = []
    for row in rows:
        features = feature_row(
            row,
            source=str(row.get("source") or "global"),
            recall_score=float(row.get("recall_score") or 0),
            route_count=1,
            recently_seen=False,
        )
        x.append([features[name] for name in FEATURE_NAMES])
        y.append(float(row.get("label") or 0))
    return x, y


def bootstrap_samples(limit: int) -> Tuple[List[List[float]], List[float]]:
    sql = """
        SELECT
          id AS image_id,
          0 AS position_no,
          like_count,
          favorite_count,
          comment_count,
          share_count,
          view_count,
          hot_score,
          published_at,
          description,
          main_category_id,
          ratio,
          thumbnail_url
        FROM images
        WHERE status='PUBLISHED'
        ORDER BY hot_score DESC,published_at DESC,id DESC
        LIMIT %s
    """
    with connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, (limit,))
            rows = cursor.fetchall()
    x: List[List[float]] = []
    y: List[float] = []
    for row in rows:
        features = feature_row(row, source="global", recall_score=0.1, route_count=1, recently_seen=False)
        pseudo_label = (
            features["engagement_score"] * 0.55
            + features["freshness_score"] * 0.25
            + features["metadata_quality_score"] * 0.12
            + features["position_decay"] * 0.08
        )
        x.append([features[name] for name in FEATURE_NAMES])
        y.append(float(pseudo_label))
    return x, y


def train(x: List[List[float]], y: List[float], mode: str) -> Dict[str, Any]:
    if len(x) < 10:
        raise SystemExit("Not enough rows to train a ranker.")
    try:
        import joblib
        from sklearn.ensemble import HistGradientBoostingRegressor
        from sklearn.metrics import mean_absolute_error
        from sklearn.model_selection import train_test_split
    except ImportError as exc:
        raise SystemExit("Install recommendation requirements first: pip install -r tools/requirements_recommendation.txt") from exc

    x_train, x_valid, y_train, y_valid = train_test_split(x, y, test_size=0.15, shuffle=False)
    model = HistGradientBoostingRegressor(
        max_iter=220,
        learning_rate=0.045,
        max_leaf_nodes=31,
        l2_regularization=0.02,
        random_state=42,
    )
    model.fit(x_train, y_train)
    predictions = model.predict(x_valid)
    validation_mae = float(mean_absolute_error(y_valid, predictions))
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model_path = MODEL_DIR / "ranker.joblib"
    metadata_path = MODEL_DIR / "ranker_metadata.json"
    joblib.dump(model, model_path)
    metadata = {
        "model_name": "vibelo-home-ranker",
        "model_version": datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
        "mode": mode,
        "feature_names": FEATURE_NAMES,
        "sample_count": len(x),
        "validation_mae": validation_mae,
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata


def positive_count(values: Iterable[float]) -> int:
    return sum(1 for value in values if value > 0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Train Vibelo home-feed ranker.")
    parser.add_argument("--mode", choices=["auto", "behavior", "bootstrap"], default="auto")
    parser.add_argument("--limit", type=int, default=80000)
    parser.add_argument("--days", type=int, default=45)
    parser.add_argument("--min-behavior-positives", type=int, default=200)
    args = parser.parse_args()

    mode = args.mode
    if mode in {"auto", "behavior"}:
        x, y = behavior_samples(args.limit, args.days)
        positives = positive_count(y)
        if mode == "behavior" and positives < args.min_behavior_positives:
            raise SystemExit(f"Only {positives} positive behavior labels found; collect more traffic first.")
        if mode == "auto" and positives < args.min_behavior_positives:
            x, y = bootstrap_samples(args.limit)
            mode = "bootstrap"
    else:
        x, y = bootstrap_samples(args.limit)
    metadata = train(x, y, mode)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
