"""
indic_places command-line interface.

Usage:
    indic-places lookup "Bangalor"
    indic-places lookup "Mumbai" --kind city
    indic-places tag "I live in Banglore near Koramanagala"
    indic-places search "Nagar"
    indic-places info "Maharashtra"
    indic-places stats
"""

import argparse
import sys
from .core import IndicPlaces
from .tagger import PlaceTagger


def main():
    parser = argparse.ArgumentParser(
        prog="indic-places",
        description="Indian Place Name Identifier — fuzzy lookup & tagging",
    )
    sub = parser.add_subparsers(dest="command")

    # lookup
    p_lookup = sub.add_parser("lookup", help="Fuzzy match a place name")
    p_lookup.add_argument("query", help="Place name to look up")
    p_lookup.add_argument("--kind", "-k", default=None, help="Filter by kind: city|state|village|road|area|landmark|district")
    p_lookup.add_argument("--top", "-n", type=int, default=5)
    p_lookup.add_argument("--min-score", type=float, default=50.0)

    # search
    p_search = sub.add_parser("search", help="Substring search")
    p_search.add_argument("query")
    p_search.add_argument("--kind", "-k", default=None)
    p_search.add_argument("--top", "-n", type=int, default=20)

    # tag
    p_tag = sub.add_parser("tag", help="Tag place names in free text")
    p_tag.add_argument("text", help="Text to tag")
    p_tag.add_argument("--annotated", "-a", action="store_true", help="Show annotated text")

    # info
    p_info = sub.add_parser("info", help="Get metadata for a place")
    p_info.add_argument("name")

    # stats
    sub.add_parser("stats", help="Show dictionary statistics")

    args = parser.parse_args()

    if args.command == "lookup":
        ip = IndicPlaces()
        results = ip.lookup(args.query, kind=args.kind, top_n=args.top, min_score=args.min_score)
        if not results:
            print(f"No matches found for '{args.query}'")
        for r in results:
            state = f"  [{r.state}]" if r.state else ""
            print(f"  {r.name:<30} kind={r.kind:<15} score={r.score:.1f}  dist={r.edit_distance}{state}")

    elif args.command == "search":
        ip = IndicPlaces()
        results = ip.search(args.query, kind=args.kind, top_n=args.top)
        if not results:
            print(f"No results for '{args.query}'")
        for r in results:
            state = f"  [{r.state}]" if r.state else ""
            print(f"  {r.name:<30} kind={r.kind}{state}")

    elif args.command == "tag":
        tagger = PlaceTagger()
        result = tagger.tag(args.text)
        if args.annotated:
            print(result.annotated)
        else:
            print(f"Found {len(result.places)} place(s):")
            for tp in result.places:
                canon = f" → {tp.canonical}" if tp.canonical != tp.text else ""
                print(f"  '{tp.text}'{canon}  kind={tp.kind}  score={tp.score:.1f}")

    elif args.command == "info":
        ip = IndicPlaces()
        info = ip.info(args.name)
        if info is None:
            print(f"'{args.name}' not found in dictionary.")
        else:
            for k, v in info.items():
                if isinstance(v, list):
                    print(f"  {k}: [{', '.join(v[:10])}{'...' if len(v) > 10 else ''}]")
                else:
                    print(f"  {k}: {v}")

    elif args.command == "stats":
        ip = IndicPlaces()
        stats = ip.stats()
        total = sum(stats.values())
        print(f"  {'Kind':<20} {'Count':>8}")
        print(f"  {'-'*20} {'-'*8}")
        for kind, count in sorted(stats.items(), key=lambda x: -x[1]):
            print(f"  {kind:<20} {count:>8,}")
        print(f"  {'-'*20} {'-'*8}")
        print(f"  {'TOTAL':<20} {total:>8,}")

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
