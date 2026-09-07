"""django-ninja API. One NinjaAPI, routers per domain, X-Auth-Token on everything
except login/setup. Errors always come back as {"detail": "..."} so the dashboard's
fetch wrapper needs no changes."""
from ninja import NinjaAPI
from ninja.errors import ValidationError

from core.auth import TokenAuth

api = NinjaAPI(title="PressPilot control plane", auth=TokenAuth())


def _reply(request, status, detail):
    return api.create_response(request, {"detail": detail}, status=status)


@api.exception_handler(ValueError)
def _bad_request(request, exc):
    return _reply(request, 400, str(exc))


@api.exception_handler(KeyError)
def _not_found(request, exc):
    return _reply(request, 404, f"no such item: {exc.args[0] if exc.args else ''}")


@api.exception_handler(RuntimeError)
def _upstream(request, exc):
    return _reply(request, 502, str(exc)[:400])


@api.exception_handler(ValidationError)
def _invalid(request, exc):
    first = exc.errors[0] if exc.errors else {}
    where = ".".join(str(p) for p in first.get("loc", [])[1:]) or "body"
    return _reply(request, 422, f"{where}: {first.get('msg', 'invalid input')}")


from core.api import auth, content, google, jobs, keywords, seo, system, topics, users, wp  # noqa: E402

for module in (auth, users, jobs, wp, seo, content, keywords, google, topics, system):
    api.add_router("", module.router)
