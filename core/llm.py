"""One door to Groq for every module that isn't the blog writer. Returns text or parsed JSON."""
import json
import re


def ask(prompt, temperature=0.4, model=None):
    import gen

    env = gen.load_env()
    data = gen._post(
        "/chat/completions",
        {"model": model or env.get("GROQ_MODEL", gen.DEFAULT_MODEL),
         "messages": [{"role": "user", "content": prompt}],
         "temperature": temperature},
        gen.api_key(env),
    )
    return data["choices"][0]["message"]["content"].strip()


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
