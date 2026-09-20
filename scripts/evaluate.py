"""Reproducible baseline/graph evaluation; Mock never gets semantic quality scores."""

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from apps.api.novelatlas_api.config import Settings
from apps.api.novelatlas_api.main import create_app


def evaluate(live: bool):
    settings = (
        Settings()
        if live
        else Settings(
            _env_file=None, text_model_provider="mock", text_model_api_key=None
        )
    )
    if live and (
        settings.text_model_provider != "deepseek" or not settings.text_model_api_key
    ):
        raise SystemExit(
            "Live evaluation requires local .env: DeepSeek provider and API key; never pass the key on the command line."
        )
    cases = json.loads((ROOT / "tests/evaluation/cases.json").read_text())["cases"]
    results = []
    for case in cases:
        for engine in ["baseline", "langgraph"]:
            app = create_app(settings=settings)
            with TestClient(app) as client:
                text = (ROOT / case["file"]).read_bytes()
                tid = client.post(
                    "/api/uploads", files={"file": ("eval.txt", text, "text/plain")}
                ).json()["task_id"]
                client.post(f"/api/documents/{tid}/parse").raise_for_status()
                client.post(f"/api/analyses/{tid}/plan", json={}).raise_for_status()
                started = time.perf_counter()
                client.post(
                    f"/api/analyses/{tid}/run",
                    json={"engine": engine, "goal": case["goal"]},
                ).raise_for_status()
                while time.perf_counter() - started < (600 if live else 30):
                    status = client.get(f"/api/analyses/{tid}/run").json()
                    if status["status"] in ["completed", "failed", "interrupted"]:
                        break
                    time.sleep(0.02 if not live else 0.5)
                elapsed = time.perf_counter() - started
                trace = client.get(f"/api/analyses/{tid}/trace").json()
                measured = [
                    r.get("measured_usage") for r in trace if r["kind"] == "model"
                ]
                measured_tokens = (
                    sum(u["total_tokens"] for u in measured)
                    if measured
                    and all(u and u["total_tokens"] is not None for u in measured)
                    else None
                )
                report_response = client.get(f"/api/analyses/{tid}/knowledge")
                report = report_response.json() if report_response.is_success else None
                items = (
                    [i for d in report["domains"] for i in d["items"]] if report else []
                )
                verified = 0
                for item in items:
                    if item["evidence"] and all(
                        client.post(f"/api/analyses/{tid}/verify", json=e).json()[
                            "quote_valid"
                        ]
                        for e in item["evidence"]
                    ):
                        verified += 1
                hits = 0
                for query in case["retrieval"]:
                    rows = client.post(
                        f"/api/analyses/{tid}/search",
                        json={"query": query["query"], "limit": 4},
                    ).json()
                    hits += any(query["quote"] in p["content"] for p in rows)
                result = {
                    "case": case["id"],
                    "engine": engine,
                    "provider": settings.text_model_provider,
                    "task_success": status["status"] == "completed",
                    "status": status["status"],
                    "wall_seconds": round(elapsed, 4),
                    "model_calls": len([r for r in trace if r["kind"] == "model"]),
                    "tool_calls": len([r for r in trace if r["kind"] == "tool"]),
                    "estimated_input_tokens": sum(
                        r.get("estimated_input_tokens", 0) for r in trace
                    ),
                    "measured_total_tokens": measured_tokens,
                    "quote_verified_items": verified,
                    "knowledge_item_count": len(items),
                    "quote_evidence_coverage": verified / len(items) if items else None,
                    "retrieval_hits_at_4": hits,
                    "retrieval_query_count": len(case["retrieval"]),
                    "fact_consistency": None,
                    "gold_fact_recall": None,
                    "quality_note": "Needs human adjudication; Mock validates execution only"
                    if not live
                    else "Pending independent human annotation",
                }
                results.append(result)
                if live:
                    # Outputs for independent annotation, saved explicitly by the developer.
                    output = {
                        "case": case["id"],
                        "engine": engine,
                        "knowledge": report,
                        "outline": client.get(f"/api/analyses/{tid}/outline").json()
                        if status["status"] == "completed"
                        else None,
                    }
                    evidence_path = ROOT / f"backup/docs/results/live-{case['id']}-{engine}.json"
                    evidence_path.parent.mkdir(parents=True, exist_ok=True)
                    evidence_path.write_text(
                        json.dumps(output, ensure_ascii=False, indent=2)
                    )
                client.delete(f"/api/uploads/{tid}").raise_for_status()
    return {
        "recorded_at": datetime.now(UTC).isoformat(),
        "mode": "live" if live else "mock",
        "results": results,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--live",
        action="store_true",
        help="Explicit paid DeepSeek evaluation using local .env",
    )
    parser.add_argument("--output", default="backup/docs/results/evaluation-mock.json")
    args = parser.parse_args()
    data = evaluate(args.live)
    path = ROOT / args.output
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(json.dumps(data, ensure_ascii=False, indent=2))
