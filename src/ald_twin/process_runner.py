"""Run and resume the bounded synthetic process study without changing its inputs."""

import argparse
import hashlib
import json
from pathlib import Path

from .process_study import evaluate_case, feasibility, summarize_cases, validate_plan, write_json

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PLAN = ROOT/"config/synthetic/process-study.json"
DEFAULT_BASE = ROOT/"config/synthetic/phase45.json"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_hashes(plan_path, base_path):
    paths = [Path(plan_path).resolve(), Path(base_path).resolve(), Path(__file__), ROOT/"docs/process-study-plan.md"]
    paths += [ROOT/"src/ald_twin"/name for name in
              ("process_study.py", "cycles.py", "cycle_study.py", "cycle_transport.py",
               "numerics.py", "channel_flow.py", "units.py", "results.py")]
    return {str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path): digest(path) for path in paths}


def check_sources(record):
    for name, expected in record["source_hashes"].items():
        if digest(ROOT/name) != expected:
            raise ValueError(f"Study source changed: {name}")


def saved_case(folder):
    path = folder/"case.json"
    if not path.exists():
        return None
    record = json.loads(path.read_text())
    if record["status"] not in ("PASS", "UNVERIFIED") or "artifact_sha256" not in record:
        return None
    for name, expected in record["artifact_sha256"].items():
        if digest(folder/name) != expected:
            raise ValueError(f"Saved trial changed: {folder/name}")
    return record


def run_case(base, plan, pulse, purge, scenario, folder, **options):
    record = saved_case(folder)
    if record is not None:
        if record["pulse_ratio"] != pulse or record["purge_ratio"] != purge or record["scenario"] != scenario:
            raise ValueError("Saved trial identity differs from the requested case")
        return record
    record = evaluate_case(base, plan, pulse, purge, scenario, folder, **options)
    record["artifact_sha256"] = {path.name: digest(path) for path in sorted(folder.iterdir())
                                 if path.suffix in (".npz", ".json") and path.name != "case.json"}
    write_json(folder/"case.json", record)
    return record


def finish_selection(front, results, count):
    if not front["complete"]:
        return dict(status="UNRESOLVED", selected=None, candidates=front["candidates"],
                    reason="An unresolved or unverified candidate could change the front")
    if not front["candidates"]:
        return dict(status="NO_FEASIBLE_CANDIDATE", selected=None, candidates=[])
    for name in front["candidates"]:
        rows = [row for row in results if row["recipe"] == name]
        if feasibility(rows, count) != "pass":
            return dict(status="UNVERIFIED_SELECTION", selected=None, candidates=front["candidates"],
                        reason=f"Refined checks did not retain feasibility for {name}")
    names = set(front["candidates"])
    selected = min((row for row in results if row["recipe"] in names),
                   key=lambda row: (row["objectives"]["cycle_time_s"], row["objectives"]["precursor_moles"]))
    return dict(status="PASS", selected=selected["recipe"], candidates=front["candidates"],
                selection_rule="Shortest cycle, then least precursor, among finite Pareto candidates")


def run_study(output, plan_path=DEFAULT_PLAN, base_path=DEFAULT_BASE, *, resume=False):
    output = Path(output).resolve()
    plan, base = (json.loads(Path(path).read_text()) for path in (plan_path, base_path))
    validate_plan(plan)
    hashes = source_hashes(plan_path, base_path)
    if resume:
        record = json.loads((output/"study.json").read_text())
        if record["source_hashes"] != hashes or record["plan"] != plan or record["base"] != base:
            raise ValueError("Resume refused: sources or configurations changed")
        check_sources(record)
        for name, expected in record["record_sha256"].items():
            if digest(output/name) != expected:
                raise ValueError(f"Saved case record changed: {name}")
    else:
        output.mkdir(parents=True, exist_ok=False)
        record = dict(kind="synthetic", status="RUNNING", physical_fit_ready=False,
                      source_hashes=hashes, plan=plan, base=base, cases=[], refinements=[], record_sha256={})
        (output/"sources").mkdir()
        for index, name in enumerate(hashes):
            (output/"sources"/f"{index:02d}-{Path(name).name}").write_bytes((ROOT/name).read_bytes())
        write_json(output/"study.json", record)
    try:
        record["status"] = "RUNNING"
        record.pop("error", None)
        cases = []
        for pulse in plan["a_pulse_ratios"]:
            for purge in plan["purge_ratios"]:
                for scenario in plan["scenarios"]:
                    name = f"a-{pulse:g}-purge-{purge:g}--{scenario['name']}"
                    print(f"Checking {name}", flush=True)
                    row = run_case(base, plan, pulse, purge, scenario, output/"cases"/name)
                    record["record_sha256"][f"cases/{name}/case.json"] = digest(output/"cases"/name/"case.json")
                    cases.append(row)
                    record.update(cases=cases, stage="scenario matrix")
                    write_json(output/"study.json", record)
        summary = summarize_cases(base, plan, cases)
        record["summary"] = summary
        nominal = set(summary["nominal_front"]["candidates"])
        robust = set(summary["scenario_front"]["candidates"])
        refinements = []
        for row in cases:
            name = row["recipe"]
            if name not in robust and not (name in nominal and row["scenario"]["name"] == "reference"):
                continue
            if row["status"] != "PASS":
                raise ValueError("An unverified baseline reached candidate refinement")
            grids = [row["accepted_cells"], row["accepted_cells"]*2]
            if grids[-1] > plan["selection_grid_ceiling"]:
                raise ValueError("Candidate refinement would exceed its declared ceiling")
            label = f"{name}--{row['scenario']['name']}"
            print(f"Refining candidate {label}: {grids}", flush=True)
            refined = run_case(base, plan, row["pulse_ratio"], row["purge_ratio"], row["scenario"],
                              output/"refinements"/label, grids=grids, include_mixed=False)
            record["record_sha256"][f"refinements/{label}/case.json"] = digest(output/"refinements"/label/"case.json")
            refinements.append(refined)
            record.update(refinements=refinements, stage="candidate refinement")
            write_json(output/"study.json", record)
        reference = [row for row in refinements if row["scenario"]["name"] == "reference"]
        record["selections"] = dict(nominal=finish_selection(summary["nominal_front"], reference, 1),
                                    all_scenarios=finish_selection(summary["scenario_front"], refinements, len(plan["scenarios"])))
        verified = all(row["status"] == "PASS" for row in cases)
        selected = all(row["status"] in ("PASS", "NO_FEASIBLE_CANDIDATE") for row in record["selections"].values())
        record.update(status="PASS" if verified and selected else "COMPLETE_WITH_UNVERIFIED", stage="complete")
        check_sources(record)
    except Exception as error:
        record.update(status="ERROR", error=f"{type(error).__name__}: {error}")
        write_json(output/"study.json", record)
        raise
    write_json(output/"study.json", record)
    print(record["status"], flush=True)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    run_study(args.output, args.plan, args.base, resume=args.resume)


if __name__ == "__main__":
    main()
