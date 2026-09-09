"""run synthetic cases and studies, or inspect their saved results."""

import argparse
import json
from pathlib import Path
import sys

from .process_runner import DEFAULT_BASE, DEFAULT_PLAN, run_case, run_study, source_hashes
from .process_study import write_json


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    gui = commands.add_parser("gui", help="Open the local reactor workspace")
    gui.add_argument("--runs", type=Path, default=Path("runs"), help="Folder for saved runs")
    gui.add_argument("--port", type=int, default=8765, help="Local port; use 0 to choose an available port")
    gui.add_argument("--no-browser", action="store_true")
    commands.add_parser("processes", help="List the packaged synthetic examples without calculating")
    inspect = commands.add_parser("inspect", help="Inspect required inputs, units and missing values")
    inspect.add_argument("process", help="Packaged process ID or a JSON input file")
    simulate = commands.add_parser("simulate", help="Verify one synthetic recipe using explicit SI inputs")
    simulate.add_argument("process", help="Packaged process ID or a JSON input file")
    simulate.add_argument("--output", type=Path, required=True)
    for segment in ("a-pulse", "a-purge", "b-pulse", "b-purge"):
        simulate.add_argument(f"--{segment}", type=float, help="Duration / carrier residence time")
    compare = commands.add_parser("compare", help="Compare completed saved runs without calculating")
    compare.add_argument("folders", type=Path, nargs="+")
    for name in ("run", "case"):
        command = commands.add_parser(name, help="Run a bounded study" if name == "run" else "Verify one declared case")
        command.add_argument("--base", type=Path, default=DEFAULT_BASE)
        command.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
        command.add_argument("--output", type=Path, required=True)
        if name == "run":
            command.add_argument("--resume", action="store_true")
        else:
            command.add_argument("--pulse", type=float, required=True, help="A pulse / residence time")
            command.add_argument("--purge", type=float, required=True, help="Each purge / residence time")
            command.add_argument("--scenario", default="reference")
    report = commands.add_parser("report", help="Generate figures and a local saved-results view")
    report.add_argument("study", type=Path)
    report.add_argument("--output", type=Path, required=True)
    status = commands.add_parser("status", help="Read current saved progress without running a calculation")
    status.add_argument("study", type=Path)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "gui":
            from .gui import serve
            serve(args.runs, args.port, not args.no_browser)
        elif args.command == "processes":
            from .process_inputs import process_catalog
            for process in process_catalog():
                print(f"{process['id']}: {process['name']} [synthetic]")
        elif args.command == "inspect":
            from .process_inputs import inspect_process, load_process
            result = inspect_process(load_process(args.process))
            print(json.dumps(result, indent=2, allow_nan=False))
            return 0 if result["runnable"] else 1
        elif args.command == "simulate":
            from .process_inputs import load_process
            from .workflow import run_process
            data = load_process(args.process)
            if not isinstance(data, dict) or not isinstance(data.get("recipe"), dict):
                raise ValueError("recipe must be an input object containing the four segment durations")
            for segment in ("a_pulse", "a_purge", "b_pulse", "b_purge"):
                value = getattr(args, segment)
                if value is not None:
                    data["recipe"][segment] = value
            result = run_process(data, args.output,
                                 progress=lambda row: print(row["stage"], file=sys.stderr, flush=True))
            print(json.dumps({key: result[key] for key in
                  ("kind", "status", "numerical_acceptance", "recipe_feasibility", "models")}, indent=2))
            return 0 if result["numerical_acceptance"] else 1
        elif args.command == "compare":
            from .workflow import compare_runs
            print(json.dumps(compare_runs(args.folders), indent=2, allow_nan=False))
        elif args.command == "run":
            run_study(args.output, args.plan, args.base, resume=args.resume)
        elif args.command == "case":
            base, plan = (json.loads(path.read_text()) for path in (args.base, args.plan))
            scenario = next((row for row in plan["scenarios"] if row["name"] == args.scenario), None)
            if scenario is None:
                raise ValueError("Unknown scenario; choose a name from the declared plan")
            args.output.mkdir(parents=True, exist_ok=False)
            write_json(args.output/"inputs.json", dict(kind="synthetic", base=base, plan=plan,
                        source_hashes=source_hashes(args.plan, args.base)))
            result = run_case(base, plan, args.pulse, args.purge, scenario, args.output)
            print(result["status"])
        elif args.command == "report":
            from .process_report import build_report
            build_report(args.study, args.output)
        else:
            if (args.study/"run.json").exists():
                result = json.loads((args.study/"run.json").read_text())
                print(json.dumps({key: result.get(key) for key in
                      ("kind", "status", "stage", "numerical_acceptance", "recipe_feasibility", "physical_fit_ready")}, indent=2))
            else:
                result = json.loads((args.study/"study.json").read_text())
                print(json.dumps(dict(kind=result["kind"], status=result["status"], stage=result.get("stage"),
                       completed_pairs=len(result["cases"]), verified_pairs=sum(row["status"] == "PASS" for row in result["cases"]),
                       refinements=len(result["refinements"]), physical_fit_ready=False), indent=2))
    except (ValueError, OSError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
