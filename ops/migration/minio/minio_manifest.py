#!/usr/bin/env python3
"""Build and compare MinIO inventories and verify sampled object content."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Iterable, Iterator, TextIO


STRATA = (
    ("empty", 0, 0),
    ("tiny_1_to_64KiB", 1, 64 * 1024 - 1),
    ("small_64KiB_to_1MiB", 64 * 1024, 1024 * 1024 - 1),
    ("medium_1MiB_to_16MiB", 1024 * 1024, 16 * 1024 * 1024 - 1),
    ("large_16MiB_plus", 16 * 1024 * 1024, None),
)


class ManifestError(RuntimeError):
    """Raised when an inventory or object stream is invalid."""


def json_line(value: dict[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def atomic_write_lines(path: Path, lines: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
    )
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            descriptor = -1
            for line in lines:
                stream.write(line)
                stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
        os.chmod(path, 0o600)
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def parse_mc_listing(stream: TextIO) -> list[tuple[str, int]]:
    objects: dict[str, int] = {}
    for line_number, raw_line in enumerate(stream, start=1):
        stripped = raw_line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ManifestError(
                f"mc 第 {line_number} 行不是合法 JSON：{exc}"
            ) from exc

        status = record.get("status")
        if status not in (None, "success"):
            message = record.get("error") or record.get("message") or record
            raise ManifestError(f"mc 列举失败：{message}")

        record_type = record.get("type")
        if record_type in ("folder", "directory"):
            continue
        if record_type not in ("file", "object"):
            if "key" not in record and "size" not in record:
                continue
            raise ManifestError(f"未知 mc 记录类型：{record_type!r}")

        key = record.get("key")
        size = record.get("size")
        if not isinstance(key, str) or isinstance(size, bool) or not isinstance(size, int):
            raise ManifestError(
                f"mc 第 {line_number} 行缺少合法的 key/size"
            )
        if size < 0:
            raise ManifestError(f"对象大小不能为负数：{key!r}")
        if key in objects:
            raise ManifestError(f"清单中出现重复 key：{key!r}")
        objects[key] = size

    return sorted(objects.items(), key=lambda item: item[0])


def iter_manifest(path: Path) -> Iterator[tuple[str, int]]:
    previous_key: str | None = None
    with path.open("r", encoding="utf-8") as stream:
        for line_number, raw_line in enumerate(stream, start=1):
            if not raw_line.strip():
                raise ManifestError(f"{path} 第 {line_number} 行为空")
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise ManifestError(
                    f"{path} 第 {line_number} 行不是合法 JSON：{exc}"
                ) from exc
            key = record.get("key")
            size = record.get("size")
            if (
                not isinstance(key, str)
                or isinstance(size, bool)
                or not isinstance(size, int)
                or size < 0
            ):
                raise ManifestError(
                    f"{path} 第 {line_number} 行缺少合法的 key/size"
                )
            if previous_key is not None and key <= previous_key:
                raise ManifestError(
                    f"{path} 未按 key 严格排序或包含重复 key：{key!r}"
                )
            previous_key = key
            yield key, size


def manifest_summary(path: Path) -> tuple[int, int]:
    count = 0
    total_bytes = 0
    for _, size in iter_manifest(path):
        count += 1
        total_bytes += size
    return count, total_bytes


def command_build(args: argparse.Namespace) -> int:
    output = Path(args.output).resolve()
    objects = parse_mc_listing(sys.stdin)
    atomic_write_lines(
        output,
        (json_line({"key": key, "size": size}) for key, size in objects),
    )
    print(
        json_line(
            {
                "bytes": sum(size for _, size in objects),
                "manifest": str(output),
                "objects": len(objects),
            }
        )
    )
    return 0


def command_summary(args: argparse.Namespace) -> int:
    manifest = Path(args.manifest).resolve()
    count, total_bytes = manifest_summary(manifest)
    print(
        json_line(
            {
                "bytes": total_bytes,
                "manifest": str(manifest),
                "objects": count,
            }
        )
    )
    return 0


def next_or_none(iterator: Iterator[tuple[str, int]]) -> tuple[str, int] | None:
    try:
        return next(iterator)
    except StopIteration:
        return None


def compare_manifests(
    source_path: Path,
    target_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    source_iterator = iter_manifest(source_path)
    target_iterator = iter_manifest(target_path)
    source_item = next_or_none(source_iterator)
    target_item = next_or_none(target_iterator)
    differences: list[dict[str, Any]] = []
    counters = {
        "missing_in_source": 0,
        "missing_in_target": 0,
        "size_mismatch": 0,
    }

    while source_item is not None or target_item is not None:
        if source_item is None:
            assert target_item is not None
            differences.append(
                {
                    "key": target_item[0],
                    "kind": "missing_in_source",
                    "target_size": target_item[1],
                }
            )
            counters["missing_in_source"] += 1
            target_item = next_or_none(target_iterator)
            continue

        if target_item is None:
            differences.append(
                {
                    "key": source_item[0],
                    "kind": "missing_in_target",
                    "source_size": source_item[1],
                }
            )
            counters["missing_in_target"] += 1
            source_item = next_or_none(source_iterator)
            continue

        if source_item[0] < target_item[0]:
            differences.append(
                {
                    "key": source_item[0],
                    "kind": "missing_in_target",
                    "source_size": source_item[1],
                }
            )
            counters["missing_in_target"] += 1
            source_item = next_or_none(source_iterator)
        elif source_item[0] > target_item[0]:
            differences.append(
                {
                    "key": target_item[0],
                    "kind": "missing_in_source",
                    "target_size": target_item[1],
                }
            )
            counters["missing_in_source"] += 1
            target_item = next_or_none(target_iterator)
        else:
            if source_item[1] != target_item[1]:
                differences.append(
                    {
                        "key": source_item[0],
                        "kind": "size_mismatch",
                        "source_size": source_item[1],
                        "target_size": target_item[1],
                    }
                )
                counters["size_mismatch"] += 1
            source_item = next_or_none(source_iterator)
            target_item = next_or_none(target_iterator)

    return differences, counters


def command_compare(args: argparse.Namespace) -> int:
    source = Path(args.source).resolve()
    target = Path(args.target).resolve()
    differences_path = Path(args.differences).resolve()
    differences, counters = compare_manifests(source, target)
    source_count, source_bytes = manifest_summary(source)
    target_count, target_bytes = manifest_summary(target)
    atomic_write_lines(
        differences_path,
        (json_line(difference) for difference in differences),
    )
    print(
        json_line(
            {
                **counters,
                "differences": len(differences),
                "differences_file": str(differences_path),
                "match": not differences,
                "source_bytes": source_bytes,
                "source_objects": source_count,
                "target_bytes": target_bytes,
                "target_objects": target_count,
            }
        )
    )
    return 0 if not differences else 2


def size_stratum(size: int) -> str:
    for name, lower, upper in STRATA:
        if size >= lower and (upper is None or size <= upper):
            return name
    raise AssertionError(f"unhandled object size: {size}")


def allocate_quotas(group_sizes: dict[str, int], requested: int) -> dict[str, int]:
    available = sum(group_sizes.values())
    target = min(requested, available)
    nonempty = [name for name, size in group_sizes.items() if size > 0]
    quotas = {name: 0 for name in group_sizes}
    if target == 0:
        return quotas

    if target < len(nonempty):
        ranked = sorted(nonempty, key=lambda name: (-group_sizes[name], name))
        for name in ranked[:target]:
            quotas[name] = 1
        return quotas

    for name in nonempty:
        quotas[name] = 1

    remaining = target - len(nonempty)
    while remaining > 0:
        candidates = [
            name for name in nonempty if quotas[name] < group_sizes[name]
        ]
        if not candidates:
            break
        capacity_total = sum(group_sizes[name] - quotas[name] for name in candidates)
        allocations: dict[str, int] = {}
        remainders: list[tuple[float, str]] = []
        allocated = 0
        for name in candidates:
            capacity = group_sizes[name] - quotas[name]
            ideal = remaining * capacity / capacity_total
            extra = min(capacity, int(ideal))
            allocations[name] = extra
            allocated += extra
            remainders.append((ideal - int(ideal), name))
        for name, extra in allocations.items():
            quotas[name] += extra
        remaining -= allocated
        if remaining == 0:
            break
        for _, name in sorted(remainders, key=lambda item: (-item[0], item[1])):
            if remaining == 0:
                break
            if quotas[name] < group_sizes[name]:
                quotas[name] += 1
                remaining -= 1

    return quotas


def command_sample(args: argparse.Namespace) -> int:
    manifest = Path(args.manifest).resolve()
    output = Path(args.output).resolve()
    groups: dict[str, list[tuple[str, int, bytes]]] = {
        name: [] for name, _, _ in STRATA
    }
    for key, size in iter_manifest(manifest):
        stratum = size_stratum(size)
        score = hashlib.sha256(
            stratum.encode("ascii") + b"\0" + key.encode("utf-8")
        ).digest()
        groups[stratum].append((key, size, score))

    quotas = allocate_quotas(
        {name: len(items) for name, items in groups.items()},
        args.count,
    )
    selected: list[dict[str, Any]] = []
    for name, _, _ in STRATA:
        ranked = sorted(groups[name], key=lambda item: (item[2], item[0]))
        for key, size, _ in ranked[: quotas[name]]:
            selected.append({"key": key, "size": size, "stratum": name})

    selected.sort(key=lambda item: (item["stratum"], item["key"]))
    atomic_write_lines(output, (json_line(item) for item in selected))
    print(
        json_line(
            {
                "available_objects": sum(len(items) for items in groups.values()),
                "requested_samples": args.count,
                "sample_file": str(output),
                "selected_samples": len(selected),
                "strata_available": {
                    name: len(items) for name, items in groups.items()
                },
                "strata_selected": quotas,
            }
        )
    )
    return 0


def load_sample(path: Path) -> list[dict[str, Any]]:
    sample: list[dict[str, Any]] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8") as stream:
        for line_number, raw_line in enumerate(stream, start=1):
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise ManifestError(
                    f"{path} 第 {line_number} 行不是合法 JSON：{exc}"
                ) from exc
            key = record.get("key")
            size = record.get("size")
            stratum = record.get("stratum")
            if (
                not isinstance(key, str)
                or isinstance(size, bool)
                or not isinstance(size, int)
                or size < 0
                or not isinstance(stratum, str)
            ):
                raise ManifestError(f"{path} 第 {line_number} 行格式错误")
            if key in seen:
                raise ManifestError(f"{path} 包含重复抽样 key：{key!r}")
            seen.add(key)
            sample.append({"key": key, "size": size, "stratum": stratum})
    return sample


def stream_object_hash(
    mc_binary: str,
    config_dir: Path,
    alias_name: str,
    bucket: str,
    key: str,
) -> tuple[str, int]:
    object_path = f"{alias_name}/{bucket}/{key}"
    digest = hashlib.sha256()
    byte_count = 0
    with tempfile.TemporaryFile(mode="w+b") as error_stream:
        process = subprocess.Popen(
            [
                mc_binary,
                "--config-dir",
                str(config_dir),
                "cat",
                object_path,
            ],
            stdout=subprocess.PIPE,
            stderr=error_stream,
        )
        assert process.stdout is not None
        while True:
            chunk = process.stdout.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            byte_count += len(chunk)
        return_code = process.wait()
        if return_code != 0:
            error_stream.seek(0)
            error_message = error_stream.read().decode("utf-8", errors="replace")
            raise ManifestError(
                f"mc cat 失败（alias={alias_name}, key={key!r}）："
                f"{error_message.strip() or f'exit {return_code}'}"
            )
    return digest.hexdigest(), byte_count


def load_cached_results(
    paths: Iterable[Path],
    sample_digest: str,
) -> dict[str, dict[str, Any]]:
    cached: dict[str, dict[str, Any]] = {}
    for path in paths:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as stream:
            for raw_line in stream:
                try:
                    record = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                key = record.get("key")
                if (
                    isinstance(key, str)
                    and record.get("match") is True
                    and record.get("sample_digest") == sample_digest
                ):
                    cached[key] = record
    return cached


def command_verify(args: argparse.Namespace) -> int:
    sample_path = Path(args.sample).resolve()
    report_path = Path(args.report).resolve()
    partial_path = report_path.with_name(report_path.name + ".partial")
    config_dir = Path(args.config_dir).resolve()
    sample = load_sample(sample_path)
    sample_digest = hashlib.sha256(sample_path.read_bytes()).hexdigest()
    cached = load_cached_results((report_path, partial_path), sample_digest)
    results: dict[str, dict[str, Any]] = {}

    report_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    partial_stream = partial_path.open("a", encoding="utf-8", newline="\n")
    os.chmod(partial_path, 0o600)
    try:
        for index, item in enumerate(sample, start=1):
            key = item["key"]
            cached_result = cached.get(key)
            if (
                cached_result is not None
                and cached_result.get("expected_size") == item["size"]
            ):
                results[key] = cached_result
                continue

            source_hash, source_bytes = stream_object_hash(
                args.mc,
                config_dir,
                args.source_alias,
                args.bucket,
                key,
            )
            target_hash, target_bytes = stream_object_hash(
                args.mc,
                config_dir,
                args.target_alias,
                args.bucket,
                key,
            )
            result = {
                "expected_size": item["size"],
                "key": key,
                "match": (
                    source_hash == target_hash
                    and source_bytes == item["size"]
                    and target_bytes == item["size"]
                ),
                "sample_digest": sample_digest,
                "source_bytes": source_bytes,
                "source_sha256": source_hash,
                "stratum": item["stratum"],
                "target_bytes": target_bytes,
                "target_sha256": target_hash,
            }
            results[key] = result
            partial_stream.write(json_line(result) + "\n")
            partial_stream.flush()
            if index % 25 == 0:
                os.fsync(partial_stream.fileno())
                print(
                    f"SHA256 抽样进度：{index}/{len(sample)}",
                    file=sys.stderr,
                )
        os.fsync(partial_stream.fileno())
    finally:
        partial_stream.close()

    ordered_results = [results[item["key"]] for item in sample if item["key"] in results]
    atomic_write_lines(report_path, (json_line(item) for item in ordered_results))
    failures = [item for item in ordered_results if item.get("match") is not True]
    complete = len(ordered_results) == len(sample)
    if complete and not failures:
        try:
            partial_path.unlink()
        except FileNotFoundError:
            pass

    print(
        json_line(
            {
                "complete": complete,
                "failed": len(failures),
                "matched": len(ordered_results) - len(failures),
                "report": str(report_path),
                "sample_digest": sample_digest,
                "sampled": len(sample),
            }
        )
    )
    return 0 if complete and not failures else 2


def positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser_command = subparsers.add_parser("build")
    build_parser_command.add_argument("--output", required=True)
    build_parser_command.set_defaults(handler=command_build)

    summary_parser = subparsers.add_parser("summary")
    summary_parser.add_argument("--manifest", required=True)
    summary_parser.set_defaults(handler=command_summary)

    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("--source", required=True)
    compare_parser.add_argument("--target", required=True)
    compare_parser.add_argument("--differences", required=True)
    compare_parser.set_defaults(handler=command_compare)

    sample_parser = subparsers.add_parser("sample")
    sample_parser.add_argument("--manifest", required=True)
    sample_parser.add_argument("--output", required=True)
    sample_parser.add_argument("--count", type=positive_integer, default=1000)
    sample_parser.set_defaults(handler=command_sample)

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--mc", default="mc")
    verify_parser.add_argument("--config-dir", required=True)
    verify_parser.add_argument("--source-alias", default="source")
    verify_parser.add_argument("--target-alias", default="target")
    verify_parser.add_argument("--bucket", required=True)
    verify_parser.add_argument("--sample", required=True)
    verify_parser.add_argument("--report", required=True)
    verify_parser.set_defaults(handler=command_verify)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.handler(args))
    except (ManifestError, OSError, subprocess.SubprocessError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
