#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Download local GPU models into tools/models."""

from __future__ import annotations

import argparse
import json
import os
import inspect
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin
from urllib.request import ProxyHandler, Request, build_opener


ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = ROOT / "tools" / "models"
HF_HOME = MODELS_DIR / "huggingface"
TORCH_HOME = MODELS_DIR / "torch"
OLLAMA_MODELS = MODELS_DIR / "ollama"

DEFAULT_LABEL_MODEL = "qwen3-vl:8b"
DEFAULT_EMBED_MODEL = "google/siglip2-base-patch16-224"
DEFAULT_OLLAMA_URL = "http://localhost:11434"


def normalize_url(value: str) -> str:
    text = str(value or "").strip()
    if "://" not in text:
        text = "http://" + text
    return text.rstrip("/")


def ollama_host_env(value: str) -> str:
    text = str(value or "").strip().rstrip("/")
    if text.startswith("http://"):
        return text[len("http://") :]
    if text.startswith("https://"):
        return text[len("https://") :]
    return text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label-model", default=os.environ.get("VIBELO_LABEL_MODEL", DEFAULT_LABEL_MODEL))
    parser.add_argument("--embedding-model", default=os.environ.get("VIBELO_EMBED_MODEL", DEFAULT_EMBED_MODEL))
    parser.add_argument("--ollama-url", default=os.environ.get("OLLAMA_HOST", DEFAULT_OLLAMA_URL))
    parser.add_argument("--ollama-exe", default=os.environ.get("OLLAMA_EXE", ""))
    parser.add_argument("--hf-endpoint", default=os.environ.get("HF_ENDPOINT", ""))
    parser.add_argument("--hf-proxy-url", default=os.environ.get("VIBELO_HF_PROXY_URL", ""))
    parser.add_argument("--hf-max-workers", type=int, default=int(os.environ.get("VIBELO_HF_MAX_WORKERS", "1") or "1"))
    parser.add_argument(
        "--hf-download-timeout",
        type=float,
        default=float(os.environ.get("VIBELO_HF_DOWNLOAD_TIMEOUT", "120") or "120"),
    )
    parser.add_argument("--hf-retries", type=int, default=int(os.environ.get("VIBELO_HF_RETRIES", "3") or "3"))
    parser.add_argument(
        "--use-hf-proxy",
        action="store_true",
        default=os.environ.get("VIBELO_USE_HF_PROXY", "0") == "1",
    )
    parser.add_argument("--skip-label", action="store_true")
    parser.add_argument("--skip-embedding", action="store_true")
    return parser.parse_args()


def configure_env(args: argparse.Namespace) -> None:
    ollama_host = ollama_host_env(args.ollama_url)
    args.ollama_url = normalize_url(args.ollama_url)
    for path in (MODELS_DIR, HF_HOME, TORCH_HOME, OLLAMA_MODELS):
        path.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(HF_HOME))
    os.environ.setdefault("HF_HUB_CACHE", str(HF_HOME / "hub"))
    os.environ.setdefault("TRANSFORMERS_CACHE", str(HF_HOME / "transformers"))
    os.environ.setdefault("TORCH_HOME", str(TORCH_HOME))
    os.environ.setdefault("XDG_CACHE_HOME", str(MODELS_DIR / "cache"))
    os.environ.setdefault("OLLAMA_MODELS", str(OLLAMA_MODELS))
    os.environ["OLLAMA_HOST"] = ollama_host
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    if args.hf_endpoint:
        os.environ["HF_ENDPOINT"] = args.hf_endpoint
    if args.use_hf_proxy or args.hf_proxy_url:
        proxy_url = normalize_url(args.hf_proxy_url or "http://127.0.0.1:12000")
        os.environ["HTTP_PROXY"] = proxy_url
        os.environ["HTTPS_PROXY"] = proxy_url
        os.environ["http_proxy"] = proxy_url
        os.environ["https_proxy"] = proxy_url
        print("Hugging Face downloads will use proxy: {}".format(proxy_url))
    os.environ["NO_PROXY"] = "localhost,127.0.0.1,::1"
    os.environ["no_proxy"] = "localhost,127.0.0.1,::1"


def safe_model_dir(model_id: str) -> Path:
    return HF_HOME / model_id.replace("/", "__")


def hf_proxies(args: argparse.Namespace) -> Optional[dict]:
    if not (args.use_hf_proxy or args.hf_proxy_url):
        return None
    proxy_url = normalize_url(args.hf_proxy_url or "http://127.0.0.1:12000")
    return {"http": proxy_url, "https": proxy_url}


def configure_hf_download_timeout(timeout_seconds: float) -> None:
    try:
        import huggingface_hub.file_download as file_download
    except ImportError:
        return
    original_http_get = file_download.http_get
    parameters = inspect.signature(original_http_get).parameters

    def http_get_with_timeout(*args, **kwargs):
        if "timeout" in parameters:
            kwargs["timeout"] = timeout_seconds
        if "_nb_retries" in parameters:
            kwargs["_nb_retries"] = max(5, int(kwargs.get("_nb_retries") or 5))
        return original_http_get(*args, **kwargs)

    file_download.http_get = http_get_with_timeout


def find_ollama_exe(explicit_path: str) -> str | None:
    if explicit_path:
        candidate = Path(explicit_path)
        if candidate.exists():
            return str(candidate)
    found = shutil.which("ollama")
    if found:
        return found
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Ollama" / "ollama.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Ollama" / "ollama.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def read_ollama_tags(ollama_url: str, timeout: int = 10) -> dict[str, object]:
    opener = build_opener(ProxyHandler({}))
    request = Request(urljoin(ollama_url.rstrip("/") + "/", "/api/tags"), method="GET")
    with opener.open(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for_ollama(ollama_url: str, seconds: int = 30) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            read_ollama_tags(ollama_url, timeout=3)
            return True
        except Exception:
            time.sleep(1)
    return False


def ensure_ollama_server(ollama_exe: str, ollama_url: str) -> None:
    try:
        read_ollama_tags(ollama_url, timeout=3)
        print("Ollama is already running. If it was started before OLLAMA_MODELS was set, restart it to keep models under tools/models.")
        return
    except Exception:
        pass

    print("Starting Ollama with OLLAMA_MODELS={}".format(os.environ["OLLAMA_MODELS"]))
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        [ollama_exe, "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
        env=os.environ.copy(),
    )
    if not wait_for_ollama(ollama_url):
        raise SystemExit("Ollama did not become ready at {}".format(ollama_url))


def pull_ollama_model(args: argparse.Namespace) -> None:
    ollama_exe = find_ollama_exe(args.ollama_exe)
    if not ollama_exe:
        raise SystemExit(
            "ollama.exe was not found. Install Ollama outside C: if needed, then set OLLAMA_EXE to the full path."
        )
    ensure_ollama_server(ollama_exe, args.ollama_url)
    print("Pulling label model {} into {}".format(args.label_model, os.environ["OLLAMA_MODELS"]))
    process = subprocess.run([ollama_exe, "pull", args.label_model], env=os.environ.copy())
    if process.returncode != 0:
        raise SystemExit("Failed to pull Ollama model {}".format(args.label_model))


def download_hf_model(model_id: str, args: argparse.Namespace) -> Path:
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise SystemExit("Missing huggingface_hub. Run: python -m pip install huggingface_hub") from exc

    target_dir = safe_model_dir(model_id)
    configure_hf_download_timeout(args.hf_download_timeout)
    proxies = hf_proxies(args)
    attempts = max(1, int(args.hf_retries or 1))
    max_workers = max(1, int(args.hf_max_workers or 1))
    print("Downloading embedding model {} into {}".format(model_id, target_dir))
    print("Hugging Face max_workers={}, download_timeout={}s, retries={}".format(
        max_workers,
        args.hf_download_timeout,
        attempts,
    ))
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            snapshot_download(
                repo_id=model_id,
                local_dir=str(target_dir),
                resume_download=True,
                proxies=proxies,
                etag_timeout=30,
                max_workers=max_workers,
            )
            last_error = None
            break
        except Exception as exc:
            last_error = exc
            if attempt >= attempts:
                break
            wait_seconds = min(30, 5 * attempt)
            print("Hugging Face download failed on attempt {}/{}: {}".format(attempt, attempts, exc))
            print("Retrying with resume in {}s...".format(wait_seconds))
            time.sleep(wait_seconds)
    if last_error is not None:
        raise last_error
    return target_dir


def main() -> None:
    args = parse_args()
    configure_env(args)
    print("Model root: {}".format(MODELS_DIR))

    if not args.skip_label:
        pull_ollama_model(args)
    if not args.skip_embedding:
        local_dir = download_hf_model(args.embedding_model, args)
        print("Embedding model local path: {}".format(local_dir))

    print("Done.")
    print("Label script: python tools/auto_label_images.py")
    print("Vector script: python tools/vectorize_images.py")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
