from __future__ import annotations

import argparse
import json
from .core import IndicPlaces


def main() -> None:
    parser = argparse.ArgumentParser(prog="indic-places")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("lookup")
    p.add_argument("text")
    p.add_argument("--top", type=int, default=5)
    p.add_argument("--min-score", type=float, default=70.0)

    p = sub.add_parser("segment")
    p.add_argument("text")

    p = sub.add_parser("extract")
    p.add_argument("text")
    p.add_argument("--min-score", type=float, default=85.0)

    sub.add_parser("stats")

    args = parser.parse_args()
    ip = IndicPlaces()

    if args.cmd == "lookup":
        print(json.dumps([r.to_dict() for r in ip.lookup(args.text, top_n=args.top, min_score=args.min_score)], indent=2, ensure_ascii=False))
    elif args.cmd == "segment":
        print(ip.segment(args.text).segmented)
    elif args.cmd == "extract":
        print(json.dumps([r.to_dict() for r in ip.extract_places(args.text, min_score=args.min_score)], indent=2, ensure_ascii=False))
    elif args.cmd == "stats":
        print(json.dumps(ip.stats(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
