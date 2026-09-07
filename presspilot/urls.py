from django.contrib import admin
from django.urls import path, re_path
from django.views.static import serve

from core.api import api
from core.spa import spa
from presspilot.settings import DIST_DIR

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", api.urls),
    re_path(r"^assets/(?P<path>.*)$", serve, {"document_root": DIST_DIR / "assets"}),
    # Everything else is the React app; it routes client-side.
    re_path(r"^(?!api/|admin/|assets/).*$", spa),
]
