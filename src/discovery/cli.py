import argparse


def main():
    parser = argparse.ArgumentParser(description="Discover job URLs via DDGS search")
    parser.add_argument("--max-workers", type=int, default=8, help="Parallel worker threads")
    parser.add_argument("--dry-run", action="store_true", help="Print queries without searching")
    args = parser.parse_args()

    from discovery.engine import run_discovery
    run_discovery(max_workers=args.max_workers, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
