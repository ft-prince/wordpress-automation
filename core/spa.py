from django.http import FileResponse, HttpResponse

from presspilot.settings import DIST_DIR


def spa(request):
    """Serve the built dashboard. index.html is never cached - hashed assets carry versions."""
    index = DIST_DIR / "index.html"
    if not index.exists():
        return HttpResponse("dashboard not built: run `cd dashboard && npm run build`",
                            status=503, content_type="text/plain")
    response = FileResponse(open(index, "rb"), content_type="text/html")
    response["Cache-Control"] = "no-cache, must-revalidate"
    return response
