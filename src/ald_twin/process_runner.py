"""Run and resume the bounded synthetic process study without changing its inputs."""

import argparse
import hashlib
import json
from pathlib import Path

from .process_study import evaluate_case, feasibility, summarize_cases, validate_plan, write_json

# repository paths and the default synthetic study files

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PLAN = ROOT/"config/synthetic/process-study.json"
DEFAULT_BASE = ROOT/"config/synthetic/phase45.json"
STUDY_MODULES = ("process_study.py", "cycles.py", "cycle_study.py", "cycle_transport.py",
                 "numerics.py", "channel_flow.py", "units.py", "results.py")


# hashes of the study sources

def digest(path):
    """sha256 hex digest of a file's bytes."""

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_hashes(plan_path, base_path):
    """hash every file the study depends on, keyed by its path under ROOT when possible."""

    paths = [Path(plan_path).resolve(), Path(base_path).resolve(), Path(__file__), ROOT/"docs/process-study-plan.md"]
    for name in STUDY_MODULES:
        paths.append(ROOT/"src/ald_twin"/name)
    hashes = {}
    for path in paths:
        if path.is_relative_to(ROOT):
            key = str(path.relative_to(ROOT))
        else:
            key = str(path)
        hashes[key] = digest(path)
    return hashes


def check_sources(record):
    """raise when any recorded study source has changed."""

    for name, expected in record["source_hashes"].items():
        if digest(ROOT/name) != expected:
            raise ValueError(f"Study source changed: {name}")


# saved cases

def saved_case(folder):
    """return a finished saved case after checking its artifacts, or None when there is none."""

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
    """reuse a matching saved case, or evaluate it and record its artifact hashes."""

    record = saved_case(folder)
    if record is not None:
        if record["pulse_ratio"] != pulse or record["purge_ratio"] != purge or record["scenario"] != scenario:
            raise ValueError("Saved trial identity differs from the requested case")
        return record
    record = evaluate_case(base, plan, pulse, purge, scenario, folder, **options)
    artifacts = {}
    for path in sorted(folder.iterdir()):
        if path.suffix in (".npz", ".json") and path.name != "case.json":
            artifacts[path.name] = digest(path)
    record["artifact_sha256"] = artifacts
    write_json(folder/"case.json", record)
    return record


# choosing a recipe from a pareto front

def _selection_key(row):
    """shortest cycle first, then least precursor."""

    return (row["objectives"]["cycle_time_s"], row["objectives"]["precursor_moles"])


def finish_selection(front, results, count):
    """pick one recipe from a complete front, only when every candidate stayed feasible."""

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
    candidates = [row for row in results if row["recipe"] in names]
    selected = min(candidates, key=_selection_key)
    return dict(status="PASS", selected=selected["recipe"], candidates=front["candidates"],
                selection_rule="Shortest cycle, then least precursor, among finite Pareto candidates")


def _is_candidate(row, nominal, robust):
    """true for a robust-front recipe, or a nominal-front recipe in its reference scenario."""

    name = row["recipe"]
    if name in robust:
        return True
    return name in nominal and row["scenario"]["name"] == "reference"


# the full study

def run_study(output, plan_path=DEFAULT_PLAN, base_path=DEFAULT_BASE, *, resume=False):
    """run every declared case, refine the candidates and select recipes, saving as it goes."""

    output = Path(output).resolve()
    plan = json.loads(Path(plan_path).read_text())
    base = json.loads(Path(base_path).read_text())
    validate_plan(plan)
    hashes = source_hashes(plan_path, base_path)

    # a resume must see the same sources, configs and saved case records

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

        # every recipe in every scenario

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

        # recheck front candidates on a doubled grid

        nominal = set(summary["nominal_front"]["candidates"])
        robust = set(summary["scenario_front"]["candidates"])
        refinements = []
        for row in cases:
            if not _is_candidate(row, nominal, robust):
                continue
            name = row["recipe"]
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

        # selections from the refined candidates

        reference = [row for row in refinements if row["scenario"]["name"] == "reference"]
        record["selections"] = dict(nominal=finish_selection(summary["nominal_front"], reference, 1),
                                    all_scenarios=finish_selection(summary["scenario_front"], refinements,
                                                                   len(plan["scenarios"])))
        verified = all(row["status"] == "PASS" for row in cases)
        selected = all(row["status"] in ("PASS", "NO_FEASIBLE_CANDIDATE") for row in record["selections"].values())
        if verified and selected:
            status = "PASS"
        else:
            status = "COMPLETE_WITH_UNVERIFIED"
        record.update(status=status, stage="complete")
        check_sources(record)
    except Exception as error:
        record.update(status="ERROR", error=f"{type(error).__name__}: {error}")
        write_json(output/"study.json", record)
        raise
    write_json(output/"study.json", record)
    print(record["status"], flush=True)
    return record


# command line

def main():
    """parse the study command line and run or resume the study."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    run_study(args.output, args.plan, args.base, resume=args.resume)


if __name__ == "__main__":
    main()
