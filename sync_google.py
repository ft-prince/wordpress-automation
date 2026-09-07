"""Sync Search Console + GA4 for one site. Registry entrypoint for sync-google."""
import sys


def _arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


if __name__ == "__main__":
    from core import google

    site = _arg("--site")
    days = int(_arg("--days", 90))
    if "--dry-run" in sys.argv:
        print(f"dry run: would sync GSC + GA4 for {site or 'default site'} ({days} days)")
        raise SystemExit(0)
    failed = 0
    for name, fn in (("Search Console", google.sync_gsc), ("GA4", google.sync_ga4)):
        try:
            rows = fn(site=site, days=days)
            print(f"{name}: {rows} rows stored")
        except ValueError as exc:
            print(f"{name}: skipped - {exc}")
        except Exception as exc:
            print(f"{name}: FAILED - {exc}", file=sys.stderr)
            failed += 1
    raise SystemExit(1 if failed else 0)
