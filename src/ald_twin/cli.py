"""run synthetic cases and studies, or inspect their saved results."""

import argparse
import json
from pathlib import Path
import sys

from .process_runner import DEFAULT_BASE, DEFAULT_PLAN, run_case, run_study, source_hashes
from .process_study import write_json

# the four recipe segments, as cli flag names and as recipe keys
SEGMENT_FLAGS = ("a-pulse", "a-purge", "b-pulse", "b-purge")
SEGMENT_KEYS = ("a_pulse", "a_purge", "b_pulse", "b_purge")

# keys printed after a single simulation
SIMULATE_SUMMARY_KEYS = ("kind", "status", "numerical_acceptance", "recipe_feasibility", "models")

# keys printed by status for a single saved run
RUN_STATUS_KEYS = ("kind", "status", "stage", "numerical_acceptance", "recipe_feasibility", "physical_fit_ready")


def add_study_paths(command):
    """add the base, plan and output folder options shared by run and case."""
    command.add_argument("--base", type=Path, default=DEFAULT_BASE)
    command.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    command.add_argument("--output", type=Path, required=True)


def build_parser():
    """build the argument parser with one subcommand per action."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    # local browser workspace
    gui = commands.add_parser("gui", help="Open the local reactor workspace")
    gui.add_argument("--runs", type=Path, default=Path("runs"), help="Folder for saved runs")
    gui.add_argument("--port", type=int, default=8765, help="Local port; use 0 to choose an available port")
    gui.add_argument("--no-browser", action="store_true")

    # read-only views of the packaged examples
    commands.add_parser("processes", help="List the packaged synthetic examples without calculating")
    inspect = commands.add_parser("inspect", help="Inspect required inputs, units and missing values")
    inspect.add_argument("process", help="Packaged process ID or a JSON input file")

    # one explicit simulation, with optional segment overrides
    simulate = commands.add_parser("simulate", help="Verify one synthetic recipe using explicit SI inputs")
    simulate.add_argument("process", help="Packaged process ID or a JSON input file")
    simulate.add_argument("--output", type=Path, required=True)
    for segment in SEGMENT_FLAGS:
        simulate.add_argument(f"--{segment}", type=float, help="Duration / carrier residence time")

    # compare saved runs
    compare = commands.add_parser("compare", help="Compare completed saved runs without calculating")
    compare.add_argument("folders", type=Path, nargs="+")

    # bounded study over the declared plan
    run = commands.add_parser("run", help="Run a bounded study")
    add_study_paths(run)
    run.add_argument("--resume", action="store_true")

    # one declared case from the plan
    case = commands.add_parser("case", help="Verify one declared case")
    add_study_paths(case)
    case.add_argument("--pulse", type=float, required=True, help="A pulse / residence time")
    case.add_argument("--purge", type=float, required=True, help="Each purge / residence time")
    case.add_argument("--scenario", default="reference")

    # figures and progress for saved results
    report = commands.add_parser("report", help="Generate figures and a local saved-results view")
    report.add_argument("study", type=Path)
    report.add_argument("--output", type=Path, required=True)
    status = commands.add_parser("status", help="Read current saved progress without running a calculation")
    status.add_argument("study", type=Path)
    return parser


def list_processes():
    """print the packaged synthetic examples."""
    from .process_inputs import process_catalog
    for process in process_catalog():
        print(f"{process['id']}: {process['name']} [synthetic]")


def inspect_command(args):
    """print what a process needs. exit code 1 when it cannot run yet."""
    from .process_inputs import inspect_process, load_process
    result = inspect_process(load_process(args.process))
    print(json.dumps(result, indent=2, allow_nan=False))
    if result["runnable"]:
        return 0
    return 1


def print_stage(row):
    """report worker progress on stderr so stdout stays json."""
    print(row["stage"], file=sys.stderr, flush=True)


def simulate_command(args):
    """run one recipe with any segment overrides. exit code 1 unless accepted."""
    from .process_inputs import load_process
    from .workflow import run_process
    data = load_process(args.process)
    if not isinstance(data, dict) or not isinstance(data.get("recipe"), dict):
        raise ValueError("recipe must be an input object containing the four segment durations")

    # flags left out keep the durations from the input file
    for segment in SEGMENT_KEYS:
        value = getattr(args, segment)
        if value is not None:
            data["recipe"][segment] = value

    result = run_process(data, args.output, progress=print_stage)
    summary = {}
    for key in SIMULATE_SUMMARY_KEYS:
        summary[key] = result[key]
    print(json.dumps(summary, indent=2))
    if result["numerical_acceptance"]:
        return 0
    return 1


def compare_command(args):
    """print a comparison of completed saved runs."""
    from .workflow import compare_runs
    print(json.dumps(compare_runs(args.folders), indent=2, allow_nan=False))


def find_scenario(plan, name):
    """return the declared scenario with this name, or None."""
    for row in plan["scenarios"]:
        if row["name"] == name:
            return row
    return None


def case_command(args):
    """run one declared pulse and purge case into a new output folder."""
    base = json.loads(args.base.read_text())
    plan = json.loads(args.plan.read_text())
    scenario = find_scenario(plan, args.scenario)
    if scenario is None:
        raise ValueError("Unknown scenario; choose a name from the declared plan")
    args.output.mkdir(parents=True, exist_ok=False)
    inputs = dict(kind="synthetic", base=base, plan=plan, source_hashes=source_hashes(args.plan, args.base))
    write_json(args.output/"inputs.json", inputs)
    result = run_case(base, plan, args.pulse, args.purge, scenario, args.output)
    print(result["status"])


def status_command(args):
    """print saved progress for a single run or a whole study."""

    # a single run folder has run.json
    if (args.study/"run.json").exists():
        result = json.loads((args.study/"run.json").read_text())
        summary = {}
        for key in RUN_STATUS_KEYS:
            summary[key] = result.get(key)
        print(json.dumps(summary, indent=2))
        return

    # otherwise it is a study folder with study.json
    # read each field in output order, so a damaged study.json reports its first missing key
    result = json.loads((args.study/"study.json").read_text())
    kind = result["kind"]
    status = result["status"]
    stage = result.get("stage")
    completed_pairs = len(result["cases"])
    verified_pairs = 0
    for row in result["cases"]:
        if row["status"] == "PASS":
            verified_pairs += 1
    refinements = len(result["refinements"])
    summary = dict(kind=kind, status=status, stage=stage,
                   completed_pairs=completed_pairs, verified_pairs=verified_pairs,
                   refinements=refinements, physical_fit_ready=False)
    print(json.dumps(summary, indent=2))


def run_command(args):
    """send parsed arguments to the chosen command and return its exit code."""
    if args.command == "gui":
        from .gui import serve
        serve(args.runs, args.port, not args.no_browser)
    elif args.command == "processes":
        list_processes()
    elif args.command == "inspect":
        return inspect_command(args)
    elif args.command == "simulate":
        return simulate_command(args)
    elif args.command == "compare":
        compare_command(args)
    elif args.command == "run":
        run_study(args.output, args.plan, args.base, resume=args.resume)
    elif args.command == "case":
        case_command(args)
    elif args.command == "report":
        from .process_report import build_report
        build_report(args.study, args.output)
    else:
        status_command(args)
    return None


def main(argv=None):
    """parse arguments and run one command. bad inputs become usage errors."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run_command(args)
    except (ValueError, OSError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
