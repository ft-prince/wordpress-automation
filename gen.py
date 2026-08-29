"""Article generator via Groq (free tier). stdlib only, OpenAI-compatible endpoint."""
import json
import re
import time
import urllib.error
import urllib.request

from wp import TIMEOUT_SECONDS, load_env

GROQ_URL = "https://api.groq.com/openai/v1"
# hardcoded default; override with GROQ_MODEL in .env. `python3 gen.py --models` lists live ones.
DEFAULT_MODEL = "openai/gpt-oss-120b"


def api_key(env):
    """GROQ_KEY or GROQ_API_KEY — accept whichever name is in .env."""
    key = env.get("GROQ_KEY") or env.get("GROQ_API_KEY")
    if not key:
        raise SystemExit("GROQ_KEY missing from .env — get one at console.groq.com/keys")
    return key

# groq/compound-mini has built-in web search — used for a research pass before writing.
RESEARCH_MODEL = "groq/compound-mini"

KEYWORD_PROMPT = """Search the web for what currently ranks for the topic: {topic}

Based on the titles, headings and "people also ask" style questions you find in real
top-ranking articles, choose:
- primary: the ONE keyword phrase (2-5 words) these articles actually target
- secondary: 3-5 related phrases or questions searchers use

Reply with ONLY this JSON, nothing else:
{{"primary": "...", "secondary": ["...", "..."]}}"""

KEYWORD_BLOCK = """
Keyword targeting (hard requirements):
- Primary keyword: "{primary}" — must appear in the title, in the first 100 words,
  and in at least one <h2>. Use it naturally, never stuffed.
- Secondary keywords: {secondary} — work each one in naturally, as an <h2>/<h3>
  or within body text. Skip any that would read forced.
"""

RESEARCH_PROMPT = """Search the web for current facts about: {topic}

Return 8-12 bullet points: recent statistics with year, industry benchmarks,
named tools/services, and notable trends. Facts only, no prose, cite the year
for every number. If a fact can't be verified, leave it out."""

PROMPT = """Write a blog post about: {topic}

Voice — write like an experienced practitioner sharing what they actually know,
not like an AI or a content mill:
- Conversational and direct. Use "you" and "we". Contractions are fine (it's, you'll, don't).
- Vary sentence length. Short ones land. Then follow with something longer that carries
  the detail, the way people actually explain things to a colleague.
- Open with a concrete situation or observation, never a definition or "In today's world".
- Take positions: "honestly, most teams don't need this" beats neutral hedging.
- One small aside, opinion, or real-world caveat per section keeps it human.
- BANNED words/phrases: delve, leverage, robust, seamless, crucial, landscape, realm,
  furthermore, moreover, "it's important to note", "in conclusion", "game-changer",
  "in the world of", "when it comes to", "at the end of the day".
- BANNED punctuation: no em dashes or en dashes anywhere in the text. Use commas,
  periods, or parentheses instead. Plain hyphens only inside compound words.
- Don't start consecutive paragraphs with the same word. Don't end with a summary that
  repeats what was already said. End with a next step or a pointed takeaway.
- Sections must not all be the same length or shape. At most one bullet list in the
  whole article. Include one short concrete scenario or example a reader would recognise.
- Small imperfections are fine: an occasional one-sentence paragraph, a sentence
  starting with And or But, a parenthetical aside.

Format:
- Return ONLY raw HTML for the post body. No <html>, <head>, <body>, no markdown fences.
- Use <h2>, <h3>, <p>, <ul>, <li>, <strong>. No <h1> — WordPress renders the title.
- {words} words, useful and specific.
- SEO: main keyword in the title and first paragraph, question-style <h2> headings
  people actually search for, title under 60 characters.
- First line must be exactly: TITLE: <the post title>
- Second line must be exactly: META: <compelling meta description, 140-155 characters>
{keywords}{research}"""

LINKS_BLOCK = """
Internal linking (required): naturally link to 1-3 of these existing pages on the same
site where genuinely relevant, using <a href="URL">descriptive anchor text</a>:
{pages}
Never force a link; skip any that don't fit.
"""

RESEARCH_BLOCK = """
Ground the post in these researched facts (weave them in naturally, keep the years):
{facts}
"""


def _post(path, payload, key, _retried=False):
    request = urllib.request.Request(
        f"{GROQ_URL}{path}",
        data=json.dumps(payload).encode(),
        # Groq's CDN 403s the default Python-urllib agent. Any real UA passes.
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "curl/8.7.1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS * 4) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf8", "replace")[:400]
        # Free tier is 8k tokens/min — wait out a 429 once instead of failing the run.
        if exc.code == 429 and not _retried:
            wait_match = re.search(r"try again in ([\d.]+)s", detail)
            delay = min(float(wait_match.group(1)) + 1 if wait_match else 30, 90)
            time.sleep(delay)
            return _post(path, payload, key, _retried=True)
        raise RuntimeError(f"Groq {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"cannot reach Groq: {exc.reason}") from exc


def _split_title(text):
    """Pull 'TITLE: ...' and 'META: ...' off the front. Returns (title, meta, body)."""
    meta = ""
    match = re.match(r"\s*TITLE:\s*(.+)", text)
    if match:
        title, rest = match.group(1).strip().strip('"'), text[match.end():].strip()
        meta_match = re.match(r"META:\s*(.+)", rest)
        if meta_match:
            meta = meta_match.group(1).strip().strip('"')
            rest = rest[meta_match.end():].strip()
        return title, meta, rest
    heading = re.search(r"<h[23][^>]*>(.*?)</h[23]>", text, re.S | re.I)
    title = re.sub(r"<[^>]+>", "", heading.group(1)).strip() if heading else "Untitled"
    return title, meta, text.strip()


def _strip_fences(text):
    return re.sub(r"^```(?:html)?\s*|\s*```$", "", text.strip())


def pick_keywords(topic, key):
    """Web-search pass: what do top-ranking articles actually target?
    Returns {"primary": str, "secondary": [str]} — falls back to the topic itself."""
    fallback = {"primary": topic.strip(), "secondary": []}
    try:
        data = _post(
            "/chat/completions",
            {
                "model": RESEARCH_MODEL,
                "messages": [{"role": "user", "content": KEYWORD_PROMPT.format(topic=topic)}],
            },
            key,
        )
        text = data["choices"][0]["message"]["content"]
        match = re.search(r"\{.*\}", text, re.S)
        parsed = json.loads(match.group(0)) if match else {}
        primary = (parsed.get("primary") or "").strip()
        secondary = [s.strip() for s in parsed.get("secondary", []) if isinstance(s, str) and s.strip()][:5]
        if not primary:
            return fallback
        return {"primary": primary, "secondary": secondary}
    except (RuntimeError, json.JSONDecodeError):
        return fallback


def research(topic, key):
    """Web-search pass via compound-mini. Returns fact bullets, or '' if search fails."""
    try:
        data = _post(
            "/chat/completions",
            {
                "model": RESEARCH_MODEL,
                "messages": [{"role": "user", "content": RESEARCH_PROMPT.format(topic=topic)}],
            },
            key,
        )
        return data["choices"][0]["message"]["content"].strip()
    except RuntimeError as exc:
        # research is an enhancer, not a dependency — post still ships without it.
        print(f"research skipped: {exc}")
        return ""


def write_full(topic, words=800, env=None, site_pages=None):
    """Generate one post. Returns (title, meta_description, html, keywords).
    site_pages: [{"title","url"}] published content the writer may link to."""
    if not topic or not topic.strip():
        raise ValueError("topic is required")
    env = env or load_env()
    key = api_key(env)

    links_part = ""
    if site_pages:
        page_lines = "\n".join(f'- {p["title"]}: {p["url"]}' for p in site_pages[:15])
        links_part = LINKS_BLOCK.format(pages=page_lines)

    keywords = pick_keywords(topic, key)
    keyword_part = KEYWORD_BLOCK.format(
        primary=keywords["primary"],
        secondary=", ".join(f'"{s}"' for s in keywords["secondary"]) or "none found",
    )
    facts = research(topic, key)
    research_part = RESEARCH_BLOCK.format(facts=facts) if facts else ""

    data = _post(
        "/chat/completions",
        {
            "model": env.get("GROQ_MODEL", DEFAULT_MODEL),
            "messages": [
                {
                    "role": "user",
                    "content": PROMPT.format(topic=topic, words=words,
                                             keywords=keyword_part,
                                             research=links_part + research_part),
                }
            ],
            "temperature": 0.7,
        },
        key,
    )
    text = _strip_fences(data["choices"][0]["message"]["content"])
    title, meta, html = _split_title(text)
    if not html:
        raise RuntimeError(f"model returned no body for topic: {topic}")
    html = _cleanup(humanize(html, key, env.get("GROQ_MODEL", DEFAULT_MODEL)))
    meta = _cleanup(meta)
    return title, meta, html, keywords


HUMANIZE_PROMPT = """You are a human editor at a small tech company reviewing a blog draft
before it goes live. Rewrite it so it reads like an experienced colleague wrote it, not
an AI. Keep the same HTML tags, structure, facts, numbers and links. Keep length within
10% of the original.

Change:
- Any sentence that sounds templated, over-polished or like marketing copy.
- Uniform paragraph rhythm. Vary it. Some short. Some longer.
- Hedged, neutral statements. Give them a point of view.
- Any em dashes or en dashes. Replace with commas, periods or parentheses.

Do not add an intro or outro. Return ONLY the rewritten HTML body, nothing else."""


def _cleanup(html):
    """Strip the punctuation tells models leave behind."""
    html = html.replace("\u2011", "-")           # non-breaking hyphen
    html = re.sub(r"\s*[\u2014\u2013]\s*", ", ", html)   # em/en dashes -> comma
    html = re.sub(r"【[^】]*】", "", html)      # research-pass citation brackets
    html = re.sub(r",\s*,", ",", html)
    html = re.sub(r"\s+([.,;:])", r"\1", html)
    return html


def humanize(html, key, model):
    """Second pass: an editor rewrite. On any failure the original draft ships."""
    try:
        data = _post(
            "/chat/completions",
            {"model": model,
             "messages": [{"role": "user", "content": HUMANIZE_PROMPT + "\n\n" + html}],
             "temperature": 0.8},
            key,
        )
        rewritten = _strip_fences(data["choices"][0]["message"]["content"])
        # Sanity: a rewrite that lost half the article is a failure, not an edit.
        if len(rewritten) > len(html) * 0.6 and "<p>" in rewritten:
            return rewritten
    except RuntimeError:
        pass
    return html


def write(topic, words=800, env=None):
    """Back-compat: (title, html) without the meta description."""
    title, _meta, html, _kw = write_full(topic, words, env)
    return title, html


def models(env=None):
    env = env or load_env()
    request = urllib.request.Request(
        f"{GROQ_URL}/models",
        headers={"Authorization": f"Bearer {api_key(env)}", "User-Agent": "curl/8.7.1"},
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return sorted(m["id"] for m in json.loads(response.read())["data"])


if __name__ == "__main__":
    import sys

    if "--models" in sys.argv:
        print("\n".join(models()))
        raise SystemExit

    # self-check. Real call, asserts the contract the publisher depends on.
    title, meta, html, kw = write_full("Why small businesses need uptime monitoring", words=300)
    assert title and title != "Untitled", f"bad title: {title!r}"
    assert "<p>" in html, "no paragraphs in output"
    assert "<h1" not in html.lower(), "model emitted an h1"
    assert "```" not in html, "markdown fence leaked through"
    assert meta, "no META description returned"
    assert kw["primary"], "no primary keyword chosen"
    print(f"TITLE: {title}\nMETA:  {meta}\nKW:    {kw['primary']} | {', '.join(kw['secondary'])}"
          f"\n\n{html[:300]}...\n\nOK ({len(html)} chars)")
