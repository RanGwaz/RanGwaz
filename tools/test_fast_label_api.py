#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Smoke test for the OpenAI-compatible vision label API. Does not write MySQL."""

from __future__ import annotations

import json

from fast_label_images_openai_compatible import API_BASE_URL, MODEL_NAME, call_model, jobs_from_results, normalize_annotation


def run() -> None:
    jobs = jobs_from_results()
    if not jobs:
        raise SystemExit("没有可测试的图片，请先运行 tools/import_images.py")
    job = jobs[0]
    print("API:", API_BASE_URL)
    print("MODEL:", MODEL_NAME)
    print("IMAGE:", job.image_path)
    annotation = normalize_annotation(call_model(job.image_path))
    print(json.dumps(annotation, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run()
