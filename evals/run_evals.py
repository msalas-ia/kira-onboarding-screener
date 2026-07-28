"""The eval suite: real runs over the labelled dev set, scored, gated, and written down. `uv run python evals/run_evals.py`."""

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import httpx

from agent.brain import BrainUnavailable, load_brain, load_version
from agent.extraction import ExtractionFailed
from agent.guardrails import GuardrailViolated
from agent.llm import AnthropicClient, ModelUnavailable
from agent.orchestrate import screen
from agent.schemas import Applicant, CaseFile, RunTrace
from agent.screening import WatchlistUnavailable, watchlist_digest
from evals.ablation import NAIVE_VERSION, compare, override_demonstrated
from evals.report import Report, render
from evals.scoring import RunOutcome, gates, outcome_of, passed, read_labels

GATE_FAILED = 1
COULD_NOT_MEASURE = 2

BRAIN_DIR = Path("company_brain")
PACKETS = Path("assets/data/applicants.json")
LABELS = Path("assets/data/labels_dev.csv")

Run = Callable[[Applicant, str], tuple[CaseFile, RunTrace]]


class BudgetExceeded(RuntimeError):
    """The suite stopped rather than spending more than it was allowed to."""


@dataclass
class Budget:
    """A gate that can silently cost ten times its estimate is a defect regardless of what the estimate was."""

    limit: float
    spent: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def charge(self, amount: float) -> None:
        """Charged as runs land, so the overshoot is bounded by whatever was already in flight."""
        with self._lock:
            self.spent += amount
            if self.spent > self.limit:
                raise BudgetExceeded(f"${self.spent:.4f} spent against a limit of ${self.limit:.2f}")


def in_process(brain, model: str, max_steps: int, timeout: float) -> Run:
    """The default: CI has no running container, and POST /screen is already covered by its own tests."""
    client = AnthropicClient(model=model, api_key=os.environ.get("ANTHROPIC_API_KEY", ""), timeout=timeout)

    def run(packet: Applicant, run_id: str) -> tuple[CaseFile, RunTrace]:
        return screen(
            packet, brain, client, run_id=run_id, model=model, max_steps=max_steps, timeout_seconds=timeout
        )

    return run


def over_http(url: str, timeout: float) -> Run:
    """The same scoring against a deployed instance, so the suite can be pointed at staging or production."""
    token = os.environ.get("SCREEN_API_TOKEN", "")

    def run(packet: Applicant, _run_id: str) -> tuple[CaseFile, RunTrace]:
        response = httpx.post(
            f"{url.rstrip('/')}/screen",
            json=packet.model_dump(mode="json"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )
        response.raise_for_status()
        body = response.json()
        return CaseFile.model_validate(body["case_file"]), RunTrace.model_validate(body["trace"])

    return run


def measure(run: Run, packets: dict[str, Applicant], applicant_ids: list[str], runs: int, concurrency: int, budget: Budget) -> list[RunOutcome]:
    """Every applicant, N times. Each run is independent, so concurrency changes the wall clock and nothing else."""
    tasks = [(applicant_id, index) for index in range(runs) for applicant_id in applicant_ids]
    outcomes: list[RunOutcome] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {
            pool.submit(run, packets[applicant_id], f"eval-{index}-{applicant_id}"): applicant_id
            for applicant_id, index in tasks
        }
        try:
            for future in concurrent.futures.as_completed(futures):
                outcome = outcome_of(*future.result())
                outcomes.append(outcome)
                budget.charge(outcome.cost_usd)
                print(
                    f"  {outcome.applicant_id} {outcome.decision:<6} "
                    f"{outcome.duration_ms / 1000:5.1f}s  ${budget.spent:.4f} spent",
                    flush=True,
                )
        finally:
            for future in futures:
                future.cancel()
    return outcomes


def commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=3, help="runs per applicant; the reported sweep uses 5")
    parser.add_argument("--concurrency", type=int, default=4, help="parallel applicant runs")
    parser.add_argument("--max-cost-usd", type=float, default=3.0, help="stop rather than exceed this")
    parser.add_argument("--url", default=None, help="screen through a deployed /screen instead of in-process")
    parser.add_argument("--model", default=os.environ.get("ANTHROPIC_MODEL", "claude-opus-5"))
    parser.add_argument("--max-steps", type=int, default=12, help="the adjudication loop's budget, as production runs it")
    parser.add_argument("--timeout", type=float, default=150.0)
    parser.add_argument("--report", type=Path, default=Path("evals/results.md"))
    parser.add_argument("--json", dest="json_path", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse(argv)

    try:
        brain = load_brain(BRAIN_DIR)
        naive = load_version(BRAIN_DIR, NAIVE_VERSION)
        watchlist_hash = watchlist_digest()
        packets = {
            entry["applicant_id"]: Applicant.model_validate(entry)
            for entry in json.loads(PACKETS.read_text(encoding="utf-8"))
        }
        labels = read_labels(LABELS)
    except (BrainUnavailable, WatchlistUnavailable, OSError, ValueError) as exc:
        print(f"could not measure: {exc}", file=sys.stderr)
        return COULD_NOT_MEASURE

    if not args.url and not os.environ.get("ANTHROPIC_API_KEY"):
        print("could not measure: ANTHROPIC_API_KEY is unset and no --url was given", file=sys.stderr)
        return COULD_NOT_MEASURE

    # Offline and free, so it runs before anything is spent: if the override
    # stopped holding, there is no reason to pay for the rest.
    ablation = compare(packets, brain, naive)

    applicant_ids = sorted(labels)
    budget = Budget(limit=args.max_cost_usd)
    run = over_http(args.url, args.timeout) if args.url else in_process(brain, args.model, args.max_steps, args.timeout)

    print(f"screening {len(applicant_ids)} applicants x {args.runs} runs against {args.model}", flush=True)
    try:
        outcomes = measure(run, packets, applicant_ids, args.runs, args.concurrency, budget)
    except BudgetExceeded as exc:
        print(f"could not measure: budget exhausted, {exc}", file=sys.stderr)
        return COULD_NOT_MEASURE
    except (ModelUnavailable, ExtractionFailed, httpx.HTTPError) as exc:
        print(f"could not measure: {exc}", file=sys.stderr)
        return COULD_NOT_MEASURE
    except GuardrailViolated as exc:
        # Not a measurement failure: the system refused to return a verdict it
        # could not justify, which is the never-auto-CLEAR property failing.
        print(f"gate failed: {exc}", file=sys.stderr)
        return GATE_FAILED

    results = gates(outcomes, labels, ablation_passed=override_demonstrated(ablation))
    report = Report(
        commit=commit(),
        model=args.model,
        runs=args.runs,
        brain_version=brain.version,
        brain_hash=brain.brain_hash,
        naive_version=naive.version,
        watchlist_hash=watchlist_hash,
        gates=results,
        outcomes=outcomes,
        labels=labels,
        ablation=ablation,
        unlabelled=sorted(set(packets) - set(labels)),
    )

    args.report.write_text(render(report), encoding="utf-8")
    if args.json_path:
        args.json_path.write_text(_as_json(report), encoding="utf-8")

    print()
    for gate in results:
        print(f"{'pass' if gate.passed else 'FAIL'}  {gate.name:<28} {gate.detail}")
    print(f"\n${budget.spent:.4f} spent. Report written to {args.report}.")

    return 0 if passed(results) else GATE_FAILED


def _as_json(report: Report) -> str:
    return json.dumps(
        {
            "commit": report.commit,
            "model": report.model,
            "runs": report.runs,
            "brain_version": report.brain_version,
            "brain_hash": report.brain_hash,
            "watchlist_hash": report.watchlist_hash,
            "gates": [{"name": gate.name, "passed": gate.passed, "detail": gate.detail} for gate in report.gates],
            "outcomes": [outcome.__dict__ for outcome in report.outcomes],
            "ablation": [row.__dict__ for row in report.ablation],
        },
        indent=1,
        sort_keys=True,
    )


if __name__ == "__main__":
    sys.exit(main())
