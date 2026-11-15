#!/usr/bin/env python3
"""Download each agent's own icon into logos/<agent id>.png.

Runs in the GitHub Action before scripts/build.py, so an agent the daily
refresh adds gets its logo on the same push. Only agents with no logo yet are
fetched; an existing file is never replaced (delete it to fetch again).

Where the icon comes from: the agent's own page (its "url" in agents.json,
or the product site in SITE_OVERRIDE). We read that page's <link rel="icon">
and <link rel="apple-touch-icon"> tags, prefer the largest, then fall back to
/apple-touch-icon.png and /favicon.ico on the same site. Nothing is hotlinked.

Every image is decoded and re-encoded as a 96x96 PNG with Pillow, so only
plain pixels end up in the repo (no SVG, no scripts). If nothing usable is
found the agent keeps its letter badge; build.py handles that.

Some product sites turn automated requests away. For those we try the site's
own /apple-touch-icon.png and /favicon.ico anyway, then the company's own
GitHub organization picture (GITHUB_ORGS), used only when GitHub says the
organization is verified and its website is on the agent's own domain.

logos/sources.json records where each file came from.
"""
import html
import io
import json
import os
import re
import sys
import urllib.parse
import urllib.request

try:
    from PIL import Image
except ImportError:
    sys.exit("fetch_logos: Pillow is not installed; agents keep their letter badges.")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "logos")
ID_OK = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SIZE = 96
MAX_BYTES = 1_500_000
Image.MAX_IMAGE_PIXELS = 4096 * 4096

# Product sites to read the icon from when the listing links elsewhere
# (for example an announcement post).
SITE_OVERRIDE = {
    "google-stitch": "https://stitch.withgoogle.com/",
}
# The company's GitHub organization, tried in order when the site itself won't
# give us an icon. Each is checked (verified, website on the agent's domain)
# before its picture is used, so a wrong guess here is simply skipped.
GITHUB_ORGS = {
    "lovable": ["lovablelabs", "lovable-dev", "GPT-Engineer-App"],
    "openai-codex": ["openai"],
    "perplexity-comet": ["perplexityai", "ppl-ai"],
}
UA = {"User-Agent": "Mozilla/5.0 (compatible; agentictools.design logo fetcher; +https://agentictools.design/)",
      "Accept": "text/html,image/*;q=0.9,*/*;q=0.5"}


def get(url, limit):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        final = r.geturl()
        if not final.startswith("https://"):
            raise ValueError("not https")
        body = r.read(limit + 1)
        if len(body) > limit:
            raise ValueError("too big")
        return final, body


def candidates(page_url):
    out = []
    final, body = get(page_url, 3_000_000)
    txt = body.decode("utf-8", "ignore")
    for tag in re.findall(r"<link\b[^>]*>", txt, re.I):
        rel = re.search(r'\brel\s*=\s*["\']([^"\']+)', tag, re.I)
        href = re.search(r'\bhref\s*=\s*["\']([^"\']+)', tag, re.I)
        if not rel or not href:
            continue
        rel = rel.group(1).lower()
        if "icon" not in rel or "mask" in rel:
            continue
        h = html.unescape(href.group(1)).strip()
        if h.startswith("data:"):
            continue
        u = urllib.parse.urljoin(final, h)
        if not u.startswith("https://"):
            continue
        sz = re.search(r'\bsizes\s*=\s*["\'](\d+)x\d+', tag, re.I)
        size = int(sz.group(1)) if sz else (180 if "apple" in rel else 32)
        if re.search(r"\.svg(\?|$)", u, re.I) or "svg" in tag.lower():
            size = 0          # we can't rasterise SVG safely here; try it last
        out.append((size + (1000 if "apple" in rel else 0), u))
    origin = "{0.scheme}://{0.netloc}".format(urllib.parse.urlparse(final))
    out += [(1180, origin + "/apple-touch-icon.png"), (17, origin + "/favicon.ico")]
    seen, uniq = set(), []
    for s, u in sorted(out, key=lambda x: -x[0]):
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


def site_domain(url):
    host = urllib.parse.urlparse(url).hostname or ""
    return ".".join(host.split(".")[-2:])


def from_github(aid, page):
    """(png bytes, source url) from a verified GitHub org whose website is on the agent's domain."""
    want = site_domain(page)
    for org in GITHUB_ORGS.get(aid, []):
        try:
            req = urllib.request.Request("https://api.github.com/orgs/" + urllib.parse.quote(org),
                                         headers={"User-Agent": UA["User-Agent"], "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                info = json.loads(r.read(200_000).decode("utf-8"))
            blog = str(info.get("blog") or "")
            if "://" not in blog:
                blog = "https://" + blog
            if not info.get("is_verified") or not want or site_domain(blog) != want:
                print("fetch_logos: %s: skipped GitHub org %s (not verified on %s)" % (aid, org, want))
                continue
            av = str(info.get("avatar_url") or "")
            if not av.startswith("https://avatars.githubusercontent.com/"):
                continue
            av += ("&" if "?" in av else "?") + "s=192"
            _, data = get(av, MAX_BYTES)
            return to_png(data), av
        except Exception as ex:
            print("fetch_logos: %s: GitHub org %s failed (%s)" % (aid, org, ex))
    return None, None


def to_png(data):
    im = Image.open(io.BytesIO(data))
    im.load()
    if min(im.size) < 16:
        raise ValueError("too small")
    im = im.convert("RGBA")
    w, h = im.size
    side = max(w, h)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(im, ((side - w) // 2, (side - h) // 2))
    canvas = canvas.resize((SIZE, SIZE), Image.LANCZOS)
    buf = io.BytesIO()
    canvas.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def main():
    with open(os.path.join(ROOT, "agents.json"), encoding="utf-8") as f:
        agents = json.load(f).get("agents", [])
    os.makedirs(OUT, exist_ok=True)
    src_path = os.path.join(OUT, "sources.json")
    try:
        with open(src_path, encoding="utf-8") as f:
            sources = json.load(f)
    except Exception:
        sources = {}
    got = missed = 0
    for a in agents:
        aid = str(a.get("id", ""))
        if not ID_OK.match(aid) or os.path.exists(os.path.join(OUT, aid + ".png")):
            continue
        page = SITE_OVERRIDE.get(aid) or str(a.get("url") or "")
        if not page.startswith("https://"):
            continue
        try:
            urls = candidates(page)
        except Exception as ex:
            print("fetch_logos: %s: couldn't read %s (%s); trying its standard icon files" % (aid, page, ex))
            origin = "{0.scheme}://{0.netloc}".format(urllib.parse.urlparse(page))
            urls = [origin + "/apple-touch-icon.png", origin + "/favicon.ico", origin + "/favicon.png"]
        done = False
        for u in urls:
            try:
                _, data = get(u, MAX_BYTES)
                png = to_png(data)
            except Exception:
                continue
            with open(os.path.join(OUT, aid + ".png"), "wb") as f:
                f.write(png)
            sources[aid] = u
            print("fetch_logos: %s <- %s" % (aid, u))
            got += 1
            done = True
            break
        if not done:
            png, src = from_github(aid, page)
            if png:
                with open(os.path.join(OUT, aid + ".png"), "wb") as f:
                    f.write(png)
                sources[aid] = src
                print("fetch_logos: %s <- %s" % (aid, src))
                got += 1
                done = True
        if not done:
            print("fetch_logos: %s: no usable icon, keeping the letter badge" % aid)
            missed += 1
    with open(src_path, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(sources.items())), f, indent=1)
        f.write("\n")
    print("fetch_logos: %d new, %d without a logo" % (got, missed))


if __name__ == "__main__":
    main()
