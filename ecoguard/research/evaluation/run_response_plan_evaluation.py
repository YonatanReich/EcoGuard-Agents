"""
Run the response plan evaluation suite.

Replays the artificial cases through the pipeline and has the judging agent
grade each resulting plan against the protocol corpus, then writes a full
machine-readable record and a human report.

What the number is, and is not:
    The suite score is one model's protocol-grounded judgement of another
    model's plan. There is no ground truth here, so it is not an accuracy
    measurement — nothing defines the single correct plan for a wildfire. Treat
    it as a quality signal with a real error bar, and read `weakest_dimension`
    rather than the headline figure when deciding what to fix.

    The pipeline is also not deterministic: adaptive thinking has no seed, no
    temperature control exists on Sonnet 5, and gap-filling search reaches a web
    that changes. A single run is a sample. Use --repeat to see the spread, and
    --no-search to remove the web as a variable when comparing two runs.

    Every run writes its full inputs, outputs and web findings, so any number in
    a report traces back to the exact plan and the exact sources that produced
    it.

Usage:
    python scripts/run_response_plan_evaluation.py                 # full suite
    python scripts/run_response_plan_evaluation.py --dry-run       # no API calls
    python scripts/run_response_plan_evaluation.py --case fire-04-negev-open-nothing-nearby
    python scripts/run_response_plan_evaluation.py --mode plan-only --repeat 3
    python scripts/run_response_plan_evaluation.py --replay data/generated/evaluation/latest.json

Needs ANTHROPIC_API_KEY except with --dry-run.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv

load_dotenv()

from ecoguard.response_planner.fire.plan_judge import ResponsePlanJudgeAgent
from ecoguard.response_planner.fire.planning_agent import ResponsePlanningAgent
from ecoguard.analyzers.emergency.fire.risk_analysis_agent import RiskAnalysisAgent
from ecoguard.shared.llm import ClaudeLLMService
from ecoguard.shared.protocols import ProtocolRetriever
from ecoguard.paths import EVALUATION, GENERATED

DEFAULT_CASES_DIR = EVALUATION / "fire_cases"
DEFAULT_OUT_DIR = GENERATED / "evaluation"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_cases(cases_dir: Path, only: list[str] | None = None) -> list[dict]:
    """
    Load case files, optionally filtered to specific ids.

    A malformed case is reported and counted rather than silently skipped —
    a suite that quietly evaluated six of eight cases would report a score that
    looks complete.

    Args:
        cases_dir (Path): Directory of case JSON files.
        only (list[str] | None): Case ids to keep.

    Returns:
        list[dict]: Loaded cases in filename order.

    Raises:
        SystemExit: If the directory is missing or a file will not parse.
    """
    if not cases_dir.is_dir():
        raise SystemExit(f"No such cases directory: {cases_dir}")

    cases = []
    for path in sorted(cases_dir.glob("*.json")):
        try:
            cases.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as error:
            raise SystemExit(f"Could not read {path.name}: {error}") from None

    if only:
        wanted = set(only)
        cases = [case for case in cases if case.get("case_id") in wanted]
        missing = wanted - {case.get("case_id") for case in cases}
        if missing:
            raise SystemExit(f"No such case id(s): {', '.join(sorted(missing))}")

    if not cases:
        raise SystemExit(f"No cases found in {cases_dir}")

    return cases


def git_commit() -> str | None:
    """Short commit hash, or None. A convenience for tracing a run, not a requirement."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        return result.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def corpus_provenance(retriever: ProtocolRetriever) -> dict:
    """Record exactly which corpus a score was produced against."""
    return {
        "hazard": retriever.hazard,
        "documents": len(retriever.documents),
        "chunks": len(retriever.chunks),
        "manifest": {
            doc_id: {
                "title": entry.get("title"),
                "sha256": entry.get("sha256"),
                "license": entry.get("license"),
            }
            for doc_id, entry in retriever.documents.items()
        },
    }


# ---------------------------------------------------------------------------
# Usage accounting
# ---------------------------------------------------------------------------


def accumulate_usage(total: dict, service) -> dict:
    """
    Add one service's most recent usage to a running total.

    ``last_usage`` is set only on success and holds only the most recent call,
    so this must be called immediately after each one. Failed calls are billed
    but contribute nothing here, which the report states rather than presenting
    the totals as complete.
    """
    usage = getattr(service, "last_usage", None) or {}

    for key in (
        "input_tokens", "output_tokens",
        "cache_creation_input_tokens", "cache_read_input_tokens",
    ):
        total[key] = total.get(key, 0) + (usage.get(key) or 0)

    total["calls"] = total.get("calls", 0) + (1 if usage else 0)
    total["web_searches"] = total.get("web_searches", 0) + getattr(
        service, "last_web_searches", 0
    )

    return total


# ---------------------------------------------------------------------------
# Running one case
# ---------------------------------------------------------------------------


def run_case(
    case: dict, *, risk_agent, planning_agent, judge, mode: str, use_judge: bool, usage: dict
) -> dict:
    """
    Put one case through the pipeline and the judge.

    Args:
        case (dict): The evaluation case.
        mode (str): "full" runs the risk agent; "plan-only" replays the frozen
            assessment so the upstream half is held constant.
        use_judge (bool): False runs the pipeline without grading it.

    Returns:
        dict: Everything produced for this case.
    """
    event = case["detected_event"]

    if mode == "full":
        risk = risk_agent.analyze_event(event)
        accumulate_usage(usage, risk_agent.llm_service)
    else:
        risk = case["risk_assessment"]

    plan = planning_agent.plan_response(event, risk)
    accumulate_usage(usage, planning_agent.llm_service)

    verdict = None
    if use_judge:
        verdict = judge.judge_case(
            case=case, risk_assessment=risk, response_plan=plan
        )
        accumulate_usage(usage, judge.llm_service)

    return {
        "case_id": case["case_id"],
        "title": case["title"],
        "probes": case.get("probes", []),
        "detected_event": event,
        "risk_assessment": risk,
        "response_plan": plan,
        "verdict": verdict,
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def build_markdown_report(run: dict) -> str:
    """
    Render the human-readable report.

    Must not crash on a suite where every case failed — that is the shape a bad
    API key produces, and it is the first one anybody hits.
    """
    meta = run["metadata"]
    summary = run["suite"]
    lines: list[str] = []

    lines.append(f"# Response plan evaluation — {meta['hazard']}")
    lines.append("")
    lines.append(
        f"Run {meta['timestamp']} · mode {meta['mode']} · repeat {meta['repeat']} · "
        f"{meta['model']} (effort {meta['effort']}) · "
        f"search {'on' if meta['web_search'] else 'off'}"
    )
    corpus = meta["corpus"]
    lines.append(
        f"Corpus: {corpus['hazard']}, {corpus['documents']} documents, "
        f"{corpus['chunks']} chunks · commit {meta.get('commit') or 'unknown'}"
    )
    lines.append("")
    lines.append(
        "> This is a judged quality score, not an accuracy measurement. There is no "
        "reference answer; the judge grades each plan against the protocol corpus. "
        "The pipeline is non-deterministic, so a single run is a sample."
    )
    lines.append("")

    # ---- Suite -----------------------------------------------------------
    lines.append("## Suite")
    lines.append("")

    score = summary.get("suite_score")
    if score is None:
        lines.append(
            f"**No cases were judged.** {summary.get('cases_total', 0)} attempted, "
            f"{summary.get('cases_judge_failed', 0)} judge failures."
        )
    else:
        lines.append(
            f"**Suite score {score}** over {summary['cases_judged']} judged case(s)."
        )
    lines.append("")
    lines.append(
        f"{summary.get('cases_refusal_correct', 0)} correct refusal(s) · "
        f"{summary.get('cases_pipeline_failed', 0)} pipeline failure(s) · "
        f"{summary.get('cases_judge_failed', 0)} judge failure(s)"
    )
    lines.append("")

    means = summary.get("dimension_means") or {}
    if means:
        weakest = summary.get("weakest_dimension")
        lines.append(f"Weakest dimension: **{weakest}** ({means.get(weakest)})")
        lines.append("")
        lines.append("| dimension | mean (0-1) |")
        lines.append("| --- | --- |")
        for name, value in sorted(means.items(), key=lambda kv: kv[1]):
            lines.append(f"| {name} | {value} |")
        lines.append("")

    # ---- Per case table --------------------------------------------------
    lines.append("## Cases")
    lines.append("")
    lines.append("| case | risk | verdict | score | grnd | unit | act | prop | safe |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")

    for result in run["cases"]:
        verdict = result.get("verdict") or {}
        risk = result.get("risk_assessment") or {}
        dims = verdict.get("dimension_scores") or {}

        risk_cell = (
            f"{risk.get('risk_score')} {risk.get('risk_level')}"
            if risk.get("risk_score") is not None
            else "not assessed"
        )

        lines.append(
            f"| {result['case_id']} | {risk_cell} | {verdict.get('verdict') or '—'} "
            f"| {verdict.get('case_score') if verdict.get('case_score') is not None else '—'} "
            f"| {dims.get('grounding', '—')} | {dims.get('unit_correctness', '—')} "
            f"| {dims.get('action_quality', '—')} | {dims.get('proportionality', '—')} "
            f"| {dims.get('safety_criticality', '—')} |"
        )

    lines.append("")

    # ---- Per case detail -------------------------------------------------
    for result in run["cases"]:
        lines.extend(render_case_detail(result))

    # ---- Usage -----------------------------------------------------------
    usage = run.get("usage") or {}
    lines.append("## Cost and usage")
    lines.append("")
    lines.append(
        f"{usage.get('calls', 0)} successful model call(s) · "
        f"{usage.get('web_searches', 0)} web search(es). "
        f"input {usage.get('input_tokens', 0):,} · "
        f"output {usage.get('output_tokens', 0):,} · "
        f"cache read {usage.get('cache_read_input_tokens', 0):,}."
    )
    lines.append("")
    lines.append(
        "Usage is recorded only for successful calls. A failed call is still "
        "billed but does not appear here, so these totals are a floor."
    )
    lines.append("")

    return "\n".join(lines)


def render_case_detail(result: dict) -> list[str]:
    """Render one case's section of the report."""
    verdict = result.get("verdict") or {}
    risk = result.get("risk_assessment") or {}
    plan = result.get("response_plan") or {}
    context = risk.get("situational_context") or {}

    lines = [f"### {result['case_id']} — {result['title']}", ""]

    if risk.get("risk_score") is not None:
        lines.append(
            f"Risk {risk['risk_score']} ({risk.get('risk_level')}, confidence "
            f"{risk.get('confidence')}) · area {context.get('area_type', 'n/a')} · "
            f"population {context.get('population_band', 'n/a')} "
            f"({context.get('population_basis', 'n/a')})"
        )
    else:
        status = (risk.get("metadata") or {}).get("analysis_status")
        lines.append(f"Risk analysis {status}: {(risk.get('metadata') or {}).get('reason') or risk.get('error')}")

    for finding in risk.get("web_findings") or []:
        lines.append(f"- Looked up: {finding.get('fact')} — {finding.get('source_url')}")

    units = plan.get("recommended_units") or []
    if units:
        lines.append(
            f"Plan: {', '.join(units)} — {len(plan.get('response_actions') or [])} action(s)"
        )
    else:
        status = (plan.get("metadata") or {}).get("planning_status")
        lines.append(f"No plan produced ({status}).")

    audit = verdict.get("citation_audit")
    if audit:
        lines.append(
            f"Citations: {audit['verified_against_corpus']}/{audit['claimed']} "
            f"verified against the corpus."
        )

    if verdict.get("verdict"):
        lines.append("")
        lines.append(
            f"**Verdict {verdict['verdict']}** "
            f"({verdict.get('case_score')}) · corpus coverage "
            f"{verdict.get('corpus_coverage')}"
        )
        if verdict.get("summary"):
            lines.append("")
            lines.append(verdict["summary"])
        for label, key in (("Problems", "problems"),
                           ("Missed protocol points", "missed_protocol_points")):
            items = verdict.get(key) or []
            if items:
                lines.append("")
                lines.append(f"{label}:")
                lines.extend(f"- {item}" for item in items)
    elif verdict.get("refusal_correct") is True:
        lines.append("")
        lines.append(
            "**Correct refusal.** The pipeline declined to plan and was right to; "
            "no model call was made and nothing was spent."
        )
    elif verdict.get("refusal_correct") is False:
        lines.append("")
        lines.append(
            "**Pipeline failure.** Risk analysis succeeded but planning did not."
        )
    elif verdict:
        lines.append("")
        lines.append(f"**Not judged:** {verdict.get('error')}")

    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--hazard", default="fire")
    parser.add_argument("--cases-dir", type=Path, default=DEFAULT_CASES_DIR)
    parser.add_argument("--case", action="append", dest="cases")
    parser.add_argument("--mode", choices=["full", "plan-only"], default="full")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--effort", default="medium")
    parser.add_argument("--retries", type=int, default=4,
                        help="SDK retries per call. Higher than the interactive "
                             "pipeline: a dropped case leaves a hole in the score.")
    parser.add_argument("--timeout", type=float, default=180.0,
                        help="Per-call timeout in seconds.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate cases and build prompts; make no API calls.")
    parser.add_argument("--no-judge", action="store_true")
    parser.add_argument("--no-search", action="store_true",
                        help="Disable gap-filling search for a comparison run.")
    parser.add_argument("--replay", type=Path,
                        help="Re-judge the plans stored in a previous run's JSON.")
    return parser.parse_args(argv)


def dry_run(cases: list[dict], retriever: ProtocolRetriever, args) -> int:
    """Validate everything and build every prompt without spending anything."""
    print("DRY RUN — no API calls will be made\n")
    print(f"  corpus       : {retriever.hazard}, {len(retriever.chunks)} chunks, "
          f"{len(retriever.documents)} documents")
    print(f"  corpus ready : {retriever.available}")
    print(f"  cases        : {len(cases)}\n")

    risk_agent = RiskAnalysisAgent(
        llm_service=ClaudeLLMService(api_key=""), retriever=retriever,
        enable_web_search=not args.no_search,
    )
    planner = ResponsePlanningAgent(
        llm_service=ClaudeLLMService(api_key=""), retriever=retriever
    )
    judge = ResponsePlanJudgeAgent(
        llm_service=ClaudeLLMService(api_key=""), retriever=retriever,
        hazard=args.hazard,
    )

    ok = True
    for case in cases:
        event = case["detected_event"]
        risk = case["risk_assessment"]

        risk_blocks, risk_text = risk_agent.build_prompt(
            event, retriever.retrieve(risk_agent.build_query(event), top_k=5)
        )
        plan_blocks, plan_text = planner.build_prompt(
            event, risk, retriever.retrieve(planner.build_query(event, risk), top_k=5)
        )
        judge_query = judge.build_query(
            detected_event=event, risk_assessment=risk,
            response_plan={"recommended_units": [], "response_actions": []},
        )

        # The leak that would invalidate the whole evaluation.
        leaked = [
            key for key in ("expected_behaviour_notes", "notes")
            if case.get(key) and case[key] in (risk_text + plan_text)
        ]
        if leaked:
            print(f"  FAIL {case['case_id']}: author notes leaked into a prompt: {leaked}")
            ok = False
            continue

        print(f"  ok   {case['case_id']:36} "
              f"risk_prompt={len(risk_text):5}c plan_prompt={len(plan_text):5}c "
              f"judge_query={len(judge_query):4}c")

    print(f"\n{'All cases validated.' if ok else 'Problems found — see above.'}")
    return 0 if ok else 1


def main(argv=None) -> int:
    args = parse_args(argv)

    retriever = ProtocolRetriever(hazard=args.hazard)

    if args.replay:
        return replay(args, retriever)

    cases = load_cases(args.cases_dir, args.cases)

    if args.dry_run:
        return dry_run(cases, retriever, args)

    if not retriever.available:
        print(f"No protocol corpus for hazard {args.hazard!r}.")
        return 1

    # A batch evaluation should prefer completeness over latency. The interactive
    # pipeline retries once because a user is waiting; here a transient 5xx that
    # drops a case turns into a missing score, and three dropped cases out of
    # eight makes the suite figure meaningless. Retry harder and wait longer.
    risk_service = ClaudeLLMService(
        effort=args.effort, max_retries=args.retries, timeout_seconds=args.timeout
    )
    if not risk_service.available:
        print("ANTHROPIC_API_KEY is not set. Use --dry-run to validate without it.")
        return 1

    risk_agent = RiskAnalysisAgent(
        llm_service=risk_service, retriever=retriever,
        enable_web_search=not args.no_search,
    )
    planning_agent = ResponsePlanningAgent(
        llm_service=ClaudeLLMService(
            effort="low", max_retries=args.retries, timeout_seconds=args.timeout
        ),
        retriever=retriever,
    )
    judge = ResponsePlanJudgeAgent(
        llm_service=ClaudeLLMService(
            effort=args.effort, max_retries=args.retries, timeout_seconds=args.timeout
        ),
        retriever=ProtocolRetriever(hazard=args.hazard),   # its own instance
        hazard=args.hazard,
    )

    usage: dict = {}
    results: list[dict] = []

    print(f"Running {len(cases)} case(s) x {args.repeat}, mode {args.mode}\n")

    for repetition in range(args.repeat):
        for case in cases:
            label = case["case_id"]
            if args.repeat > 1:
                label = f"{label} (run {repetition + 1})"
            print(f"  {label} ...", flush=True)

            result = run_case(
                case, risk_agent=risk_agent, planning_agent=planning_agent,
                judge=judge, mode=args.mode, use_judge=not args.no_judge,
                usage=usage,
            )
            result["repetition"] = repetition + 1
            results.append(result)

            verdict = result.get("verdict") or {}
            print(
                f"      risk={(result['risk_assessment'] or {}).get('risk_score')} "
                f"verdict={verdict.get('verdict') or verdict.get('error') or 'n/a'} "
                f"score={verdict.get('case_score')}"
            )

    suite = judge.judge_suite([r["verdict"] for r in results if r.get("verdict")])

    run = {
        "metadata": {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "hazard": args.hazard,
            "mode": args.mode,
            "repeat": args.repeat,
            "model": risk_service.model,
            "effort": args.effort,
            "web_search": not args.no_search,
            "commit": git_commit(),
            "corpus": corpus_provenance(retriever),
        },
        "suite": suite,
        "cases": results,
        "usage": usage,
    }

    write_outputs(run, args.out_dir)
    print_summary(suite)

    return 0


def replay(args, retriever) -> int:
    """Re-judge the plans stored in a previous run, without re-running the pipeline."""
    try:
        previous = json.loads(args.replay.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SystemExit(f"Could not read {args.replay}: {error}") from None

    judge = ResponsePlanJudgeAgent(
        llm_service=ClaudeLLMService(effort=args.effort),
        retriever=retriever, hazard=args.hazard,
    )

    if not judge.llm_service.available:
        print("ANTHROPIC_API_KEY is not set.")
        return 1

    usage: dict = {}
    results = []

    print(f"Re-judging {len(previous['cases'])} stored plan(s)\n")

    for stored in previous["cases"]:
        print(f"  {stored['case_id']} ...", flush=True)
        verdict = judge.judge_case(
            case={"case_id": stored["case_id"],
                  "detected_event": stored["detected_event"]},
            risk_assessment=stored["risk_assessment"],
            response_plan=stored["response_plan"],
        )
        accumulate_usage(usage, judge.llm_service)
        results.append({**stored, "verdict": verdict})

    suite = judge.judge_suite([r["verdict"] for r in results if r.get("verdict")])

    run = {
        "metadata": {
            **previous["metadata"],
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "replayed_from": str(args.replay),
        },
        "suite": suite,
        "cases": results,
        "usage": usage,
    }

    write_outputs(run, args.out_dir, prefix="replay")
    print_summary(suite)

    return 0


def write_outputs(run: dict, out_dir: Path, prefix: str = "run") -> None:
    """Write the full record, the report, and the stable latest.* copies."""
    out_dir.mkdir(parents=True, exist_ok=True)

    stamp = run["metadata"]["timestamp"].replace(":", "").replace("-", "")
    base = f"{prefix}_{stamp}_{run['metadata']['hazard']}"

    report = build_markdown_report(run)

    for path in (out_dir / f"{base}.json", out_dir / "latest.json"):
        path.write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")

    for path in (out_dir / f"{base}.md", out_dir / "latest.md"):
        path.write_text(report, encoding="utf-8")

    print(f"\nWrote {out_dir / f'{base}.md'}")
    print(f"      {out_dir / 'latest.md'}")


def print_summary(suite: dict) -> None:
    score = suite.get("suite_score")
    print()
    if score is None:
        print("No cases were judged.")
    else:
        print(f"Suite score {score} over {suite['cases_judged']} judged case(s).")
        print(f"Weakest dimension: {suite.get('weakest_dimension')}")
    print(
        f"{suite.get('cases_refusal_correct', 0)} correct refusal(s), "
        f"{suite.get('cases_pipeline_failed', 0)} pipeline failure(s), "
        f"{suite.get('cases_judge_failed', 0)} judge failure(s)."
    )


if __name__ == "__main__":
    raise SystemExit(main())
