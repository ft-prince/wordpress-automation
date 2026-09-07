"""Keyword pipeline steps as a job so they stream logs and can be stopped.
--step research | cluster | map | serp | all. Registry entrypoint for keyword-pipeline."""
import sys


def _arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


STEPS = ("research", "cluster", "map", "serp")


def main():
    from core import keywords, serp

    site, step = _arg("--site"), _arg("--step", "all")
    steps = STEPS if step == "all" else (step,)
    if step not in STEPS + ("all",):
        raise SystemExit(f"unknown step {step}; use one of {', '.join(STEPS)} or all")
    if "--dry-run" in sys.argv:
        print(f"dry run: would run {', '.join(steps)} for {site or 'default site'}")
        return
    for s in steps:
        print(f"== {s}")
        if s == "research":
            r = keywords.research(site)
            print(f"   {r['new']} new keywords, {r['scored']} scored, {r['total']} total")
        elif s == "cluster":
            r = keywords.cluster(site)
            print(f"   {r['clusters']} clusters, {r['assigned']} keywords assigned")
        elif s == "map":
            r = keywords.map_urls(site)
            print(f"   {r['mapped']} clusters mapped")
        elif s == "serp":
            r = serp.analyze_top(site, int(_arg("--limit", 10)), log=print)
            print(f"   {r['analysed']} clusters analysed" + (f", {len(r['errors'])} failed" if r["errors"] else ""))
            for e in r["errors"]:
                print(f"   ! {e}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
