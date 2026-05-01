from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from app.application.document_classifier import classify_document
from app.application.normalizer import normalize_transactions
from app.application.pdf_parser import parse_pdf_transactions
from app.application.reconciliation import reconcile_transactions


@dataclass(frozen=True)
class BenchmarkRun:
    file_name: str
    success: bool
    elapsed_ms: float
    tx_count: int
    parser: str
    parse_ms: float
    classify_ms: float
    normalize_ms: float
    reconcile_ms: float
    message: str = ""


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percentile
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    frac = rank - low
    return ordered[low] * (1 - frac) + ordered[high] * frac


def _run_single(sample: Path) -> BenchmarkRun:
    raw = sample.read_bytes()
    started = perf_counter()
    try:
        parse_started = perf_counter()
        parse_result = parse_pdf_transactions(raw)
        parse_ms = round((perf_counter() - parse_started) * 1000, 3)

        classify_started = perf_counter()
        classify_document(
            filename=sample.name,
            raw_bytes=raw,
            extracted_text=parse_result.extracted_text,
            layout_inference_name=parse_result.layout.layout_name,
            layout_inference_confidence=parse_result.layout.confidence,
        )
        classify_ms = round((perf_counter() - classify_started) * 1000, 3)

        normalize_started = perf_counter()
        normalized = normalize_transactions(parse_result.transactions)
        normalize_ms = round((perf_counter() - normalize_started) * 1000, 3)

        reconcile_started = perf_counter()
        reconcile_transactions(normalized)
        reconcile_ms = round((perf_counter() - reconcile_started) * 1000, 3)
    except Exception as exc:  # pragma: no cover - benchmark resilience
        elapsed_ms = round((perf_counter() - started) * 1000, 3)
        return BenchmarkRun(
            file_name=sample.name,
            success=False,
            elapsed_ms=elapsed_ms,
            tx_count=0,
            parser="error",
            parse_ms=0.0,
            classify_ms=0.0,
            normalize_ms=0.0,
            reconcile_ms=0.0,
            message=f"{type(exc).__name__}: {exc}",
        )
    elapsed_ms = round((perf_counter() - started) * 1000, 3)
    return BenchmarkRun(
        file_name=sample.name,
        success=True,
        elapsed_ms=elapsed_ms,
        tx_count=len(normalized),
        parser=str(parse_result.parse_metrics.get("selected_parser", "unknown")),
        parse_ms=parse_ms,
        classify_ms=classify_ms,
        normalize_ms=normalize_ms,
        reconcile_ms=reconcile_ms,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run baseline benchmark for PDF parse pipeline.")
    parser.add_argument("--samples-dir", default="backend/samples", help="Directory containing PDF samples.")
    parser.add_argument("--glob", default="*.pdf", help="Glob pattern for sample selection.")
    parser.add_argument("--repeat", type=int, default=1, help="Number of runs per file.")
    parser.add_argument("--max-files", type=int, default=0, help="Limit number of files (0 = no limit).")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    samples_dir = Path(args.samples_dir)
    if not samples_dir.exists():
        print(f"ERROR samples dir not found: {samples_dir}")
        return 1

    pdf_files = sorted(samples_dir.glob(args.glob))
    if args.max_files > 0:
        pdf_files = pdf_files[: args.max_files]
    if not pdf_files:
        print("ERROR no PDF files matched")
        return 1

    runs: list[BenchmarkRun] = []
    for sample in pdf_files:
        for _ in range(max(1, args.repeat)):
            runs.append(_run_single(sample))

    success_runs = [item for item in runs if item.success]
    failed_runs = [item for item in runs if not item.success]

    total_ms = [item.elapsed_ms for item in success_runs]
    parse_ms = [item.parse_ms for item in success_runs]
    classify_ms = [item.classify_ms for item in success_runs]
    normalize_ms = [item.normalize_ms for item in success_runs]
    reconcile_ms = [item.reconcile_ms for item in success_runs]
    parser_mix = Counter(item.parser for item in success_runs)

    print("PDF Baseline Benchmark")
    print(f"samples={len(pdf_files)} runs={len(runs)} success={len(success_runs)} failed={len(failed_runs)}")
    success_rate = (len(success_runs) / len(runs) * 100.0) if runs else 0.0
    print(f"success_rate={success_rate:.2f}%")
    if success_runs:
        print(f"latency_p50_ms={_percentile(total_ms, 0.5):.3f}")
        print(f"latency_p95_ms={_percentile(total_ms, 0.95):.3f}")
        print(f"parse_p50_ms={_percentile(parse_ms, 0.5):.3f}")
        print(f"classify_p50_ms={_percentile(classify_ms, 0.5):.3f}")
        print(f"normalize_p50_ms={_percentile(normalize_ms, 0.5):.3f}")
        print(f"reconcile_p50_ms={_percentile(reconcile_ms, 0.5):.3f}")
        print("parser_mix=" + ", ".join(f"{name}:{count}" for name, count in sorted(parser_mix.items())))

    print("")
    print("Per-file runs:")
    for item in runs:
        status = "OK" if item.success else "ERR"
        line = (
            f"{status} file={item.file_name} elapsed_ms={item.elapsed_ms:.3f} tx={item.tx_count} "
            f"parser={item.parser} parse_ms={item.parse_ms:.3f} classify_ms={item.classify_ms:.3f}"
        )
        if item.message:
            line += f" msg={item.message}"
        print(line)

    return 0 if not failed_runs else 2


if __name__ == "__main__":
    raise SystemExit(main())
