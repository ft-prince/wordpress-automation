"""Token + cost ledger for Groq calls. Prices per 1M tokens (input, output), USD.
ponytail: static table; edit when Groq changes pricing."""
from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone

from core.models import LlmCall

PRICES = {"openai/gpt-oss-120b": (0.15, 0.60), "openai/gpt-oss-20b": (0.10, 0.50),
          "groq/compound-mini": (0.15, 0.60), "groq/compound": (0.15, 0.60)}
DEFAULT_PRICE = (0.20, 0.80)


def record(response, purpose=""):
    """Call with the raw chat-completions JSON. Never raises - accounting must not break jobs."""
    try:
        usage = response.get("usage") or {}
        model = response.get("model") or ""
        if not usage:
            return
        p_in, p_out = PRICES.get(model, (0, 0) if ":" in model or not model.startswith(("openai/", "groq/")) else DEFAULT_PRICE)  # local models cost nothing
        pt, ct = int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
        LlmCall.objects.create(model=model[:64], purpose=purpose[:32], prompt_tokens=pt, completion_tokens=ct,
                               cost_usd=(pt * p_in + ct * p_out) / 1_000_000)
    except Exception:
        pass


def summary():
    now = timezone.now()

    def window(days):
        agg = LlmCall.objects.filter(ts__gte=now - timedelta(days=days)).aggregate(
            pt=Sum("prompt_tokens"), ct=Sum("completion_tokens"), usd=Sum("cost_usd"))
        return {"calls": LlmCall.objects.filter(ts__gte=now - timedelta(days=days)).count(),
                "tokens": (agg["pt"] or 0) + (agg["ct"] or 0), "usd": round(agg["usd"] or 0, 4)}

    from core import secrets

    env = secrets._parse()
    return {"today": window(1), "week": window(7), "month": window(30),
            "endpoint": env.get("LLM_BASE_URL") or "groq", "model": env.get("LLM_MODEL") or env.get("GROQ_MODEL") or "openai/gpt-oss-120b"}
