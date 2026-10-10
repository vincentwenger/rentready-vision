"""Step 58: read-only cross-check of previously committed evidence.

Does not run Bedrock, AWS, detector inference, or any held-out video.
Only writes the optional --output JSON chosen by the operator.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def verify(root: Path) -> dict:
    checks: list[dict] = []

    def record(name: str, passed: bool, details: object = None) -> None:
        checks.append({"name": name, "passed": bool(passed), "details": details})

    def load_json(path: str) -> dict:
        with (root / path).open("r", encoding="utf-8-sig") as file:
            return json.load(file)

    def equal_approx(value: float, target: float, tolerance: float = .02) -> bool:
        return math.isclose(value, target, abs_tol=tolerance, rel_tol=0)

    required = [
        "docs/step58/system_architecture.svg",
        "docs/step58/system_architecture.dot",
        "docs/step58/agent_loop.svg",
        "docs/step58/agent_loop.dot",
        "STEP13_BENCHMARK.md",
        "STEP35_OPENCV_CONTRIBUTION.md",
        "STEP48_PROTOCOL.md",
        "STEP48_RESULTS.md",
        "STEP23_AGENT_ACTION_LOG.md",
        "evaluation/step13/benchmark_results.csv",
        "evaluation/step13/output_equivalence.json",
        "evaluation/step34/clip_metrics.json",
        "evaluation/step34d/detector_v2_freeze.json",
        "evaluation/step36/challenge_final_v1/measurement.json",
        "evaluation/step37/failure_cases.json",
        "evaluation/step48/final_metrics.json",
        "evaluation/step23/live_aws_verification.json",
    ]
    missing = [p for p in required if not (root / p).is_file()]
    record("all_required_artifacts_present", not missing, {"missing": missing})
    if missing:
        return {"step": 58, "passed": False, "checks": checks, "error": "Required files are missing"}

    with (root / "evaluation/step13/benchmark_results.csv").open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    counts = Counter((r["phase"].strip().lower(), r["environment"].strip().lower()) for r in rows)
    measured = {group: [r for r in rows if r["phase"].lower() == "measured" and r["environment"].lower() == group] for group in ("stock", "cool")}
    record("step13_warmup_and_measured_counts", len(rows) == 12 and all(counts[("warmup", g)] == 1 and counts[("measured", g)] == 5 for g in ("stock", "cool")), dict((f"{k[0]}_{k[1]}",v) for k, v in counts.items()))
    record("step13_all_measured_successful", all(r["success"].strip().lower() == "true" for group in measured.values() for r in group))
    means = {g: statistics.mean(float(r["wall_clock_seconds"]) for r in group) for g, group in measured.items()}
    speeds = {g: statistics.mean(float(r["sampled_frames_per_second"]) for r in group) for g, group in measured.items()}
    record("step13_historical_mean_seconds", equal_approx(means["stock"], 161.719) and equal_approx(means["cool"], 150.696), means)
    record("step13_historical_frame_throughput", equal_approx(speeds["stock"], 6.511) and equal_approx(speeds["cool"], 6.988), speeds)
    output_equivalence = load_json("evaluation/step13/output_equivalence.json")
    record("step13_output_equivalence", output_equivalence.get("passed") is True and len(output_equivalence.get("comparisons", [])) == 10 and all(c.get("equivalent") is True for c in output_equivalence.get("comparisons", [])), {"comparisons": len(output_equivalence.get("comparisons", []))})
    record("step13_74_frames_54_scenes", all(int(r["retained_frame_count"]) == 74 and int(r["scene_count"]) == 54 for group in measured.values() for r in group))
    source_runs = root / "evaluation/step13/runs/20260906T165332Z/raw_runs"
    record("step13_raw_runs_retained", source_runs.is_dir() and len(list(source_runs.glob("*.json"))) == 12, {"run_json_count": len(list(source_runs.glob("*.json"))) if source_runs.is_dir() else 0})

    historical = load_json("evaluation/step34/clip_metrics.json")
    record("step34_old_mozart_test_scope", all(historical.get(k) == v for k,v in {"test_videos":23,"defect_videos":8,"clean_videos":15,"true_positives":0,"false_negatives":8,"true_negatives":15,"false_positives":0}.items()))
    dev = load_json("evaluation/step34d/detector_v2_freeze.json").get("development_live_result", {})
    record("step34d_v2_development_scope", all(dev.get(k) == v for k,v in {"clips":21,"tp":3,"fn":5,"tn":13,"fp":0,"owner_verified_intervals":2,"annotated_intervals":9}.items()))

    step36 = load_json("evaluation/step36/challenge_final_v1/measurement.json")
    step36_rows = step36.get("per_candidate", [])
    record("step36_challenge_two_candidates", step36.get("candidate_count") == 2 and len(step36_rows) == 2 and step36.get("purpose") == "challenge")
    record("step36_measured_accuracy_before_after", equal_approx(step36.get("metrics", {}).get("accuracy_before_agent_investigation", -1), 0) and equal_approx(step36.get("metrics", {}).get("accuracy_after_agent_investigation", -1), .5))
    record("step36_false_positive_not_hidden", any(x.get("ground_truth") == "ABSENT" and x.get("final_outcome") == "PRESENT" and x.get("final_correct") is False for x in step36_rows))
    candidate_checks=[]
    for x in step36_rows:
        path=f'evaluation/step36/challenge_final_v1/candidates/{x["candidate_id"]}/candidate_result.json'
        sample=load_json(path)
        candidate_checks.append(sample.get("candidate_id") == x["candidate_id"] and sample.get("final_assessment", {}).get("outcome") == x.get("final_outcome") and sample.get("agent_tool_calls") == 1 and any(s.get("tool") == "inspect_interval" for s in sample.get("steps", [])))
    record("step36_actual_tool_traces_present", len(candidate_checks) == 2 and all(candidate_checks))

    failures=load_json("evaluation/step37/failure_cases.json")
    record("step37_five_failure_cases", failures.get("case_count") == 5 and len(failures.get("cases",[])) == 5)

    holdout=load_json("evaluation/step48/final_metrics.json")
    conf=holdout.get("confusion_matrix",{})
    tp,tn,fp,fn=(conf.get(k) for k in ("true_positive","true_negative","false_positive","false_negative"))
    record("step48_heldout_raw_confusion",(tp,tn,fp,fn)==(8,9,0,1) and holdout.get("videos")==18 and holdout.get("detector_profile")=="detector_v4_candidate/1.0")
    scored=holdout.get("metrics",{})
    correct=(tp+tn)/(tp+tn+fp+fn) if all(isinstance(x,int) for x in (tp,tn,fp,fn)) else -1
    recall=tp/(tp+fn) if isinstance(tp,int) and isinstance(fn,int) and tp+fn else -1
    precision=tp/(tp+fp) if isinstance(tp,int) and isinstance(fp,int) and tp+fp else -1
    record("step48_accuracy_precision_recall", equal_approx(correct,scored.get("accuracy",-1),.0001) and equal_approx(recall,scored.get("recall",-1),.0001) and equal_approx(precision,scored.get("precision",-1),.0001), {"accuracy":correct,"precision":precision,"recall":recall})
    record("step48_faucet_false_negative_preserved", holdout.get("false_negatives")==["v4p008"] and holdout.get("false_positives")==[])
    raw_preds=root/"evaluation/step48/raw_predictions"
    record("step48_18_raw_predictions_present", raw_preds.is_dir() and len(list(raw_preds.glob("*.json")))==18, {"count":len(list(raw_preds.glob("*.json"))) if raw_preds.is_dir() else 0})

    prod=load_json("evaluation/step23/live_aws_verification.json")
    action_log=prod.get("action_log",{})
    actions=action_log.get("actions",[])
    record("step23_real_live_trace_verified", prod.get("passed") is True and not prod.get("errors") and action_log.get("action_count")==3 and len(actions)==3)
    record("step23_actual_agent_sequence", [x.get("action") for x in actions]==["observe_candidate","inspect_interval","final_decision"] and [x.get("sequence") for x in actions]==[1,2,3])
    if len(actions)==3:
        record("step23_true_frame_confidence_transition", actions[1].get("frames_returned")==15 and actions[1].get("confidence_before")==.8 and actions[1].get("confidence_after")==.9 and actions[2].get("details",{}).get("result")=="ACCEPT_CANDIDATE")
    else:
        record("step23_true_frame_confidence_transition",False)

    return {
        "schema_version":"rentready-step58-evidence-validation/1.0",
        "step":58,
        "verification_scope":"read-only cross-check of previously stored evidence, NOT fresh evaluation",
        "checked_utc":datetime.now(timezone.utc).isoformat(),
        "passed": all(x["passed"] for x in checks),
        "checks_passed":sum(x["passed"] for x in checks),
        "checks_total":len(checks),
        "checks":checks,
        "aws_calls":0,
        "inference_calls":0,
        "holdout_reruns":0,
    }


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,default=Path("."))
    parser.add_argument("--output",type=Path,default=None)
    args=parser.parse_args()
    try:
        report=verify(args.root.resolve())
    except (OSError,ValueError,KeyError,TypeError,ZeroDivisionError) as exc:
        report={"step":58,"passed":False,"error":f"{type(exc).__name__}: {exc}"}
    if args.output is not None:
        out=args.output if args.output.is_absolute() else args.root/args.output
        out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
        print("Saved verification:",out)
    print(f"STEP 58: {'PASS' if report['passed'] else 'FAIL'} | {report.get('checks_passed',0)}/{report.get('checks_total',0)} checks")
    for check in report.get("checks",[]):
        print(f"  {'PASS' if check['passed'] else 'FAIL'}  {check['name']}")
    if report.get("error"):
        print("Error:",report["error"])
    raise SystemExit(0 if report["passed"] else 1)

if __name__=="__main__":
    main()
