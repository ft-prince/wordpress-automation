"""Measure Core Web Vitals for the latest crawl. Registry entrypoint for pagespeed."""
import sys


def _arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


if __name__ == "__main__":
    from core import pagespeed

    if "--dry-run" in sys.argv:
        print("dry run: would measure", _arg("--site", "default site"))
        raise SystemExit(0)
    try:
        n = pagespeed.run(site=_arg("--site"), max_pages=int(_arg("--max-pages", 30)))
        print(f"measured {n} pages")
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
