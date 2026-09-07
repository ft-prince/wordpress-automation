"""One door to Groq for every module that isn't the blog writer. Returns text or parsed JSON."""
import json
import re


MAX_TOKENS = 12000
REASONING = "low"  # gpt-oss otherwise spends the whole budget thinking and returns nothing


def ask(prompt, temperature=0.4, model=None):
    import gen

    env = gen.load_env()
    payload = {"model": model or env.get("GROQ_MODEL", gen.DEFAULT_MODEL),
               "messages": [{"role": "user", "content": prompt}],
               "temperature": temperature, "max_completion_tokens": MAX_TOKENS}
    if "gpt-oss" in payload["model"]:
        payload["reasoning_effort"] = REASONING
    data = gen._post("/chat/completions", payload, gen.api_key(env))
    choice = data["choices"][0]
    content = (choice["message"].get("content") or "").strip()
    if not content:
        raise RuntimeError(f"model returned no content (finish_reason={choice.get('finish_reason')})")
    return content


def ask_json(prompt, temperature=0.3, model=None):
    """Prompt must demand a single JSON object/array. Fenced or chatty replies are tolerated."""
    raw = ask(prompt, temperature, model)
    match = re.search(r"[\[{].*[\]}]", raw, re.S)
    if not match:
        raise RuntimeError("model returned no JSON")
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"model returned bad JSON: {exc.msg}")
