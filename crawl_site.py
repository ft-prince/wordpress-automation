"""Crawl one site into the SEO database. Registry entrypoint for crawl-site."""
import sys


def _arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


if __name__ == "__main__":
    from core import crawl

    if "--dry-run" in sys.argv:
        print("dry run: would crawl", _arg("--site", "default site"))
        raise SystemExit(0)
    try:
        crawl.run(site=_arg("--site"), max_pages=int(_arg("--max-pages", 300)))
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
