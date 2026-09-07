"""Scheduled writer. Claims the next approved topic and runs the same gate the dashboard
uses: brief -> draft -> QA -> WordPress draft. Never publishes unless --policy publish
AND QA passed at 80+. Registry entrypoint for publish-blog."""
import sys
from datetime import datetime, timezone

QA_PUBLISH_THRESHOLD = 80
QA_DRAFT_THRESHOLD = 60


def run(dry_run=False, site=None, policy="draft", category=None):
    """policy: draft   -> WP draft whenever QA >= 60, else brief waits for human review
               review  -> WP draft only when QA verdict is pass
               publish -> as draft, then publish when QA >= 80 and verdict pass"""
    from core import briefs, images, topics, wp_api

    topic = topics.claim_next(site)
    if not topic:
        print(f"topic queue is empty. Approve topics on the dashboard ({topics.queue_depth(site)} queued)")
        return 0
    print(f"topic #{topic['id']}: {topic['title']}  (source: {topic['source']})")
    try:
        brief = briefs.create(topic["title"], site=site, topic_id=topic["id"])
        print(f"brief #{brief['id']}: keyword='{brief['primary_keyword']}' intent={brief['intent']} "
              f"sections={len(brief['outline'])} links={len(brief['internal_links'])}")
        brief = briefs.write_draft(brief["id"], site=site)
        print(f"draft: {brief['draft_title']} ({len(brief['draft_html'])} chars)")
        brief = briefs.run_qa(brief["id"], site=site)
        qa = brief["qa"]
        failed = [c["code"] for c in qa["checks"] if not c["ok"]]
        print(f"QA: score {qa['score']} verdict={qa['verdict']} failed={failed or 'none'} "
              f"unsupported={len((qa.get('model') or {}).get('unsupported_claims') or [])}")
    except Exception:
        topics.release(topic["id"])
        raise

    if dry_run:
        topics.release(topic["id"])
        print("dry run: brief kept for review, nothing sent to WordPress")
        return 0

    ok_for_draft = qa["score"] >= QA_DRAFT_THRESHOLD if policy == "draft" else qa["verdict"] == "pass"
    if not ok_for_draft:
        print(f"QA below the bar - brief #{brief['id']} left in review on the dashboard")
        return 0

    result = briefs.approve(brief["id"], site=site, actor="publish-blog", status="draft")
    post = result["post"]
    print(f"draft #{post['id']} -> {post['link']}")

    try:
        wp_api.update_post(post["id"], {"categories": [wp_api.ensure_category(category or "Insights", site=site)]}, site=site)
    except RuntimeError as exc:
        print(f"category skipped: {exc}")
    try:
        media_id = images.set_featured(post["id"], brief["primary_keyword"] or brief["title"], site=site)
        print(f"featured image set (media #{media_id})")
    except RuntimeError as exc:
        print(f"featured image skipped: {exc}")

    if policy == "publish" and qa["score"] >= QA_PUBLISH_THRESHOLD and qa["verdict"] == "pass":
        wp_api.update_post(post["id"], {"status": "publish"}, site=site)
        print(f"QA {qa['score']} >= {QA_PUBLISH_THRESHOLD} and verdict pass - published")
    elif policy == "publish":
        print(f"QA {qa['score']} / {qa['verdict']} - left as draft for review")
    return 0


def _arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


if __name__ == "__main__":
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        code = run(dry_run="--dry-run" in sys.argv, site=_arg("--site"),
                   policy=_arg("--policy", "publish" if "--publish" in sys.argv else "draft"),
                   category=_arg("--category"))
    except Exception as exc:
        print(f"[{stamp}] FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
    print(f"[{stamp}] done")
    raise SystemExit(code)
