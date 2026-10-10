"""Command-line interface: ``classmark sample|profile|run|report``."""

import argparse
import json
import os
import sys
from pathlib import Path

from classmark import config


def load_dotenv(path: Path = Path(".env")) -> None:
    """Read KEY=VALUE lines from a git-ignored .env file; real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip().removeprefix("export ").strip(), value.strip().strip("'\""))


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="classmark", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("sample", help="draw a stratified sample of public Zenodo records")
    p.add_argument("experiment", help="question set name, for example e1 or e2_oecd_fos")
    p.add_argument("--n", type=int, required=True, help="number of records to keep")

    p = sub.add_parser("profile", help="print the state built for a local folder (sends nothing)")
    p.add_argument("folder", type=Path)
    p.add_argument("--title")
    p.add_argument("--description")
    p.add_argument("--cap", type=int, default=config.STATE_CAP_CHARS)

    p = sub.add_parser("run", help="answer a question set for sampled records with one backend")
    p.add_argument("experiment")
    p.add_argument("--backend", choices=["jev", "claude"], required=True)
    p.add_argument("--n", type=int, help="use only the first N sampled records")
    p.add_argument(
        "--budget",
        type=float,
        default=config.DEFAULT_BUDGET_USD,
        help=f"hard spending limit in US$ for this run (default {config.DEFAULT_BUDGET_USD})",
    )
    p.add_argument("--dry-run", action="store_true", help="build states and requests but do not call any model API")
    p.add_argument(
        "--reverse-options", action="store_true", help="ask with Choice options in reverse order (position-bias check)"
    )
    p.add_argument("--workers", type=int, default=4)

    p = sub.add_parser("report", help="evaluate results and write reports/<experiment>/report.md")
    p.add_argument("experiment")

    args = parser.parse_args(argv)

    if args.command == "sample":
        from classmark.sample import sample

        print(f"Wrote {sample(args.experiment, args.n)}")
    elif args.command == "profile":
        from classmark.profile import profile_folder

        prof = profile_folder(args.folder, args.title, args.description, cap=args.cap)
        print(json.dumps({"state": prof.state, "meta": prof.meta}, indent=2, ensure_ascii=False))
    elif args.command == "run":
        from classmark.run import run

        run(
            args.experiment,
            args.backend,
            n=args.n,
            budget_usd=args.budget,
            dry_run=args.dry_run,
            reverse_options=args.reverse_options,
            workers=args.workers,
        )
    elif args.command == "report":
        from classmark.report import build_report

        print(f"Wrote {build_report(args.experiment)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
