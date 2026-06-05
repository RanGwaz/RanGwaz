#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Development-only vector reset: clear MySQL vector state and Milvus collections."""

from __future__ import annotations

from typing import List


MYSQL_HOST = "127.0.0.1"
MYSQL_PORT = 3306
MYSQL_DATABASE = "rangwaz_image_dev"
MYSQL_USER = "rangwaz"
MYSQL_PASSWORD = "rangwaz123"

MILVUS_HOST = "127.0.0.1"
MILVUS_PORT = "19530"
MILVUS_COLLECTIONS_TO_DROP: List[str] = [
    "vibelo_image_vectors_clip_b32",
    "vibelo_image_vectors_siglip2_giant_p384",
    "vibelo_image_vectors_siglip2_giant_p384_old",
    "vibelo_image_vectors_siglip2_giant_p384_tmp",
    "vibelo_image_vectors_siglip2_giant_p384_v1",
    "vibelo_image_vectors_siglip2_giant_p384_v2",
]


def require_dependencies():
    try:
        import pymysql
        from pymilvus import connections, utility
    except Exception as exc:
        raise SystemExit(
            "缺少依赖，请先执行：python -m pip install pymysql pymilvus\n"
            "原始错误：{}".format(exc)
        ) from exc
    return pymysql, connections, utility


def connect_mysql():
    pymysql, _, _ = require_dependencies()
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
        charset="utf8mb4",
        autocommit=False,
        cursorclass=pymysql.cursors.DictCursor,
    )


def clear_mysql_vector_state() -> None:
    with connect_mysql() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM recommendation_candidates")
            candidates = cursor.rowcount
            cursor.execute("DELETE FROM user_interest_snapshots")
            snapshots = cursor.rowcount
            cursor.execute("DELETE FROM image_embeddings")
            embeddings = cursor.rowcount
        conn.commit()
    print("MySQL 已清理：image_embeddings={}，recommendation_candidates={}，user_interest_snapshots={}。".format(
        embeddings,
        candidates,
        snapshots,
    ))


def clear_milvus_collections() -> None:
    _, connections, utility = require_dependencies()
    connections.connect(alias="default", host=MILVUS_HOST, port=MILVUS_PORT)
    dropped = []
    missing = []
    for name in MILVUS_COLLECTIONS_TO_DROP:
        if utility.has_collection(name):
            utility.drop_collection(name)
            dropped.append(name)
        else:
            missing.append(name)
    print("Milvus 已删除 collection：{}。".format(", ".join(dropped) if dropped else "无"))
    print("Milvus 未找到 collection：{}。".format(", ".join(missing) if missing else "无"))


def run() -> None:
    clear_mysql_vector_state()
    clear_milvus_collections()
    print("向量数据已清空。下一步运行 tools/vectorize_images.py 生成新模型向量。")


if __name__ == "__main__":
    run()
