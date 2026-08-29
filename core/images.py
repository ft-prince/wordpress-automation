"""Featured images: curated stock via Pexels (free key) with AI-illustration fallback."""
import json
import re
import urllib.parse
import urllib.request

import wp
from core import sites, wp_api

MIN_WIDTH = 800
STOPWORDS = {"what", "is", "are", "the", "a", "an", "and", "or", "when", "should", "you",
             "your", "how", "to", "why", "for", "of", "in", "it", "use", "using", "with",
             "signs", "guide", "tips", "best", "vs", "5", "10"}

AI_STYLE = ("detailed isometric 3D illustration, deep navy background with orange accents, "
            "high quality digital art, absolutely no text, no words, no letters")


def _search_terms(subject):
    words = [w for w in re.findall(r"[A-Za-z]+", subject.lower()) if w not in STOPWORDS]
    return " ".join(words[:4]) or subject


def _fetch(url, timeout=45, limit=10 * 1024 * 1024):
    req = urllib.request.Request(url, headers={"User-Agent": "wp-automation/1.0 (Mozilla/5.0)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(limit), resp.headers.get("Content-Type", "image/jpeg").split(";")[0]


def _generate_ai(subject):
    """Fallback: Pollinations generation when no stock photo matches."""
    prompt = urllib.parse.quote(f"Concept illustration for an article titled '{subject}'. {AI_STYLE}")
    seed = sum(ord(c) for c in subject) % 100000
    url = (f"https://image.pollinations.ai/prompt/{prompt}"
           f"?width=1200&height=630&nologo=true&model=flux&seed={seed}")
    data, content_type = _fetch(url, timeout=90)
    if not content_type.startswith("image/") or len(data) < 5000:
        raise RuntimeError("image fallback returned something that isn't an image")
    return data, content_type, None


def search_pexels(subject):
    """Curated stock photos — needs a free PEXELS_KEY in .env (pexels.com/api).
    Far more reliable than open-web CC search for business topics."""
    key = wp.load_env().get("PEXELS_KEY")
    if not key:
        return None
    query = urllib.parse.urlencode({
        "query": _search_terms(subject), "orientation": "landscape", "per_page": 5,
    })
    req = urllib.request.Request(
        f"https://api.pexels.com/v1/search?{query}",
        headers={"Authorization": key, "User-Agent": "wp-automation/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            photos = json.loads(resp.read()).get("photos", [])
    except Exception:
        return None
    if not photos:
        return None
    p = photos[0]
    return {
        "url": p["src"].get("large2x") or p["src"]["original"],
        "title": p.get("alt") or subject,
        "creator": p.get("photographer") or "Pexels",
        "license": "Pexels License (free commercial use)",
        "license_url": "https://www.pexels.com/license/",
        "source": p.get("url") or "",
    }


def get_image(subject):
    """Returns (bytes, content_type, attribution|None).
    Pexels (curated stock, needs free PEXELS_KEY) → AI illustration.
    keyless CC search (Openverse/Flickr) was tried and removed — three test
    queries returned a conference talk, a 2003 screenshot and a blurry selfie."""
    photo = search_pexels(subject)
    if photo:
        try:
            data, content_type = _fetch(photo["url"])
            if content_type.startswith("image/") and len(data) > 5000:
                return data, content_type, photo
        except Exception:
            pass
    return _generate_ai(subject)


def set_featured(post_id, subject, site=None):
    """Find/generate + upload + attach as featured image, with license attribution."""
    env = sites.env_for(site)
    data, content_type, attribution = get_image(subject)
    ext = content_type.split("/")[-1].replace("jpeg", "jpg")
    media = wp.upload_media(data, f"featured-{post_id}.{ext}", content_type, env=env)

    # CC licenses require attribution — write it into the media caption + alt text.
    if attribution:
        caption = (f'"{attribution["title"]}" by {attribution["creator"]}, '
                   f'{attribution["license"]}'
                   + (f' — {attribution["source"]}' if attribution["source"] else ""))
        try:
            wp.call(f"/media/{media['id']}", {"alt_text": subject, "caption": caption},
                    method="POST", env=env)
        except RuntimeError:
            pass  # attribution write is best-effort; the image itself matters more
    wp_api.update_post(post_id, {"featured_media": media["id"]}, site=site)
    return media["id"]
