import argparse
import asyncio
import json


def main():
    parser = argparse.ArgumentParser(description="Extract job data from URLs")
    parser.add_argument("url", nargs="?", help="Extract a single URL")
    parser.add_argument("--llm", action="store_true", help="Fill missing fields with LLM")
    args = parser.parse_args()

    if args.url:
        from extractor.router import route_extract
        result = asyncio.run(route_extract(args.url, use_llm=args.llm))
        print(json.dumps(result, indent=2))
    else:
        from extractor.runner import run_extractor
        asyncio.run(run_extractor(use_llm=args.llm))


if __name__ == "__main__":
    main()
