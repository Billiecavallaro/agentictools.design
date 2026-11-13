#!/usr/bin/env python3
"""Build the crawlable parts of agentictools.design from agents.json.

Runs on every push to main (see .github/workflows/build.yml), so the daily
refresh only has to change agents.json. It is a pure function of agents.json
and index.html: running it twice gives the same files.

It writes:
  index.html            the directory, workflows and FAQ baked into the page
                        between <!--b:NAME--> markers, plus meta tags and JSON-LD
  agents/<id>/index.html  one profile page per agent
  workflows/<id>/index.html  one page per workflow
  assets/site.css       the page's own styles, shared by the subpages
  sitemap.xml, robots.txt, llms.txt, llms-full.txt, 404.html

Standard library only.
"""
import datetime as dt
import html
import json
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = "https://agentictools.design"
NAME = "agentictools.design"
OG_IMAGE = SITE + "/og.png"
ID_OK = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

CATS = {"design": "Design", "prototype": "Prototyping", "research": "Research",
        "pm": "Product & specs", "build": "Build", "general": "General"}
TINT = {"design": "#D9CFE6", "prototype": "#CFE0DA", "research": "#E6DCC8",
        "pm": "#D3DCE8", "build": "#E3D3CC", "general": "#DADAD2"}
APP_CAT = {"design": "DesignApplication", "prototype": "DesignApplication",
           "research": "BusinessApplication", "pm": "BusinessApplication",
           "build": "DeveloperApplication", "general": "BusinessApplication"}

HOME_TITLE = "AI Agents for Designers and Product Managers, Updated Daily | agentictools.design"
CHEV = ('<span class="chev" aria-hidden="true"><svg width="10" height="10" viewBox="0 0 10 10">'
        '<path d="M3 1.5L6.5 5 3 8.5" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg></span>')
ICON = ('<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><circle cx="6" cy="6" r="5" fill="none" '
        'stroke="currentColor" stroke-width="1.2"/><path d="M3.6 6.1l1.6 1.6 3.2-3.4" fill="none" stroke="currentColor" '
        'stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/></svg>')
GLYPH = '<span class="glyph" aria-hidden="true"><i></i><i></i></span>'


def e(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def safe_url(u):
    u = str(u or "").strip()
    if not re.match(r"^https://[A-Za-z0-9.-]+(?:[:/?#]|$)", u) or any(c in u for c in '"<> \n\r\t\\'):
        return None
    return u


def parse_date(s):
    try:
        return dt.date.fromisoformat(str(s))
    except Exception:
        return None


def fmt_date(s, year=True):
    d = parse_date(s)
    if not d:
        return str(s or "")
    out = d.strftime("%b ") + str(d.day)
    return out + ", " + str(d.year) if year else out


def ld(obj):
    """JSON-LD that can't break out of its script tag."""
    txt = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return txt.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def mark_text(name):
    return re.sub(r"[^A-Za-z0-9]", "", name or "")[:2] or "?"


def mark(a, big=False):
    return ('<span class="mark" aria-hidden="true" style="--tint:%s">%s</span>'
            % (TINT.get(a.get("category"), TINT["general"]), e(mark_text(a.get("name")))))


def clip(s, n):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    if len(s) <= n:
        return s
    cut = s[:n - 1].rsplit(" ", 1)[0].rstrip(",;:.")
    return cut + "…"


# ---------------------------------------------------------------- data

def load():
    with open(os.path.join(ROOT, "agents.json"), encoding="utf-8") as f:
        d = json.load(f)
    updated = d.get("updated") or dt.date.today().isoformat()
    ref = parse_date(updated) or dt.date.today()

    def is_new(x):
        a = parse_date(x.get("added"))
        return bool(a) and 0 <= (ref - a).days < 8

    def ordered(items):
        fresh = sorted([x for x in items if is_new(x)], key=lambda x: x.get("added", ""), reverse=True)
        return fresh + [x for x in items if not is_new(x)]

    agents = [a for a in d.get("agents", []) if isinstance(a, dict) and ID_OK.match(str(a.get("id", ""))) and a.get("name")]
    seen, uniq = set(), []
    for a in agents:
        if a["id"] not in seen:
            seen.add(a["id"])
            uniq.append(a)
    wfs = [w for w in d.get("workflows", []) if isinstance(w, dict) and ID_OK.match(str(w.get("id", ""))) and w.get("title")]
    return {
        "updated": updated,
        "updates": [u for u in d.get("updates", []) if isinstance(u, dict)],
        "agents": ordered(uniq),
        "workflows": ordered(wfs),
        "is_new": is_new,
        "by_id": {a["id"]: a for a in uniq},
    }


def cats_present(D):
    return [k for k in CATS if any(a.get("category") == k for a in D["agents"])]


def agent_page(a):
    return "%s/agents/%s/" % (SITE, a["id"])


def wf_page(w):
    return "%s/workflows/%s/" % (SITE, w["id"])


# ---------------------------------------------------------------- home page blocks

def new_badge(D, x):
    return '<em class="nw">New</em>' if D["is_new"](x) else ""


def blk_cats(D):
    out = []
    for k in ["all"] + cats_present(D):
        n = len(D["agents"]) if k == "all" else sum(1 for a in D["agents"] if a.get("category") == k)
        out.append('<button class="cat" type="button" aria-pressed="%s"><span>%s</span><span class="n">%d</span></button>'
                   % ("true" if k == "all" else "false", e("All agents" if k == "all" else CATS[k]), n))
    return "".join(out)


def blk_list(D):
    out = []
    for i, a in enumerate(D["agents"]):
        out.append('<button class="row" type="button" role="option" aria-selected="%s">%s<span class="txt"><b>%s</b>'
                   '<span>%s · %s</span></span>%s</button>'
                   % ("true" if i == 0 else "false", mark(a), e(a["name"]), e(a.get("maker", "")),
                      e(CATS.get(a.get("category"), "")), new_badge(D, a)))
    return "".join(out)


def blk_detail(D):
    if not D["agents"]:
        return '<p class="checked">No agents in this category yet.</p>'
    a = D["agents"][0]
    u = safe_url(a.get("url"))
    return (
        '<div class="dhead">%s<div><h3>%s</h3><p>%s · %s</p></div>%s</div>'
        '<div class="thirty"><span class="eyebrow"><span>In 30 seconds</span><span>0:30</span></span><p>%s</p></div>'
        '<dl class="facts"><dt>For</dt><dd>%s</dd><dt>Best at</dt><dd>%s</dd><dt>Pricing</dt><dd>%s</dd></dl>'
        '<div class="tags">%s</div>'
        '<div class="dfoot"><span class="checked">Checked on its own site %s</span>%s</div>'
    ) % (mark(a), e(a["name"]), e(a.get("maker", "")), e(CATS.get(a.get("category"), "")), new_badge(D, a),
         e(a.get("oneLiner", "")), e(a.get("forWho", "")), e(a.get("standout", "")), e(a.get("pricing") or "See site"),
         "".join('<span class="tag">%s</span>' % e(t) for t in a.get("tags") or []),
         e(fmt_date(a.get("verified") or D["updated"])),
         ('<a class="pill" href="%s" target="_blank" rel="noopener noreferrer">Visit site ↗</a>' % e(u)) if u else "")


def blk_log(D):
    ups = D["updates"][:6] or [{"date": D["updated"], "text": "Directory refreshed"}]
    return "".join('<time datetime="%s">%s</time><span>%s</span>' % (e(u.get("date")), e(fmt_date(u.get("date"), False)), e(u.get("text")))
                   for u in ups)


def blk_wflist(D):
    out = []
    for i, w in enumerate(D["workflows"]):
        out.append('<button class="wfbtn" type="button" aria-pressed="%s">%s<span><b>%s%s</b><span>%d tools</span></span></button>'
                   % ("true" if i == 0 else "false", ICON, e(w["title"]), new_badge(D, w), len(w.get("tools") or [])))
    return "".join(out)


def tool_names(D, w):
    return [D["by_id"][t]["name"] for t in (w.get("tools") or []) if t in D["by_id"]]


def blk_wfmain(D):
    if not D["workflows"]:
        return ""
    w = D["workflows"][0]
    return ('<h3>%s</h3><div class="ask">Uses %s</div><ol class="steps">%s</ol>'
            '<p class="done"><b>Done</b><span>%s</span></p><a class="link" href="/workflows/%s/">Open this workflow →</a>'
            % (e(w["title"]), e(", ".join(tool_names(D, w))),
               "".join("<li><span>%s</span></li>" % e(s) for s in w.get("steps") or []),
               e(w.get("outcome", "")), e(w["id"])))


def blk_chips(D):
    return "".join('<button class="chip" type="button" aria-pressed="%s">%s</button>'
                   % ("true" if k == "all" else "false", e("All" if k == "all" else CATS[k]))
                   for k in ["all"] + cats_present(D))


def blk_table(D):
    out = []
    for a in D["agents"]:
        u = safe_url(a.get("url"))
        out.append(
            '<details class="trow"><summary><span class="nm">%s<span style="min-width:0"><b>%s%s</b><span>%s</span></span></span>'
            '<span class="ol">%s</span><span class="cl">%s</span><span class="pr">%s</span>%s</summary>'
            '<div class="more"><div><span class="eyebrow">For</span><span>%s</span></div>'
            '<div><span class="eyebrow">Best at</span><span>%s</span></div>'
            '<div class="acts"><a class="pill" href="/agents/%s/">Full profile</a>%s</div></div></details>'
            % (mark(a), e(a["name"]), new_badge(D, a), e(a.get("maker", "")), e(a.get("oneLiner", "")),
               e(CATS.get(a.get("category"), "")), e(a.get("pricing") or "See site"), CHEV,
               e(a.get("forWho", "")), e(a.get("standout", "")), e(a["id"]),
               ('<a class="pill" href="%s" target="_blank" rel="noopener noreferrer">Visit site ↗</a>' % e(u)) if u else ""))
    return "".join(out)


def counts(D):
    return len(D["agents"]), len(cats_present(D)), len(D["workflows"])


def fresh_line(D):
    n_new = sum(1 for x in D["agents"] + D["workflows"] if D["is_new"](x))
    return "Updated %s · %d agents%s" % (fmt_date(D["updated"]), len(D["agents"]), (" · %d new this week" % n_new) if n_new else "")


# ---------------------------------------------------------------- FAQ (visible text and FAQPage JSON-LD come from the same source)

def faq_items(D):
    n_agents, n_cats, n_wf = counts(D)
    items = []

    def by_cat(*keys):
        return [a for a in D["agents"] if a.get("category") in keys]

    def agent_list(agents, limit=8):
        html_items, txt_items = [], []
        for a in agents[:limit]:
            html_items.append('<li><a href="/agents/%s/">%s</a> by %s: %s</li>' % (e(a["id"]), e(a["name"]), e(a.get("maker", "")), e(a.get("oneLiner", ""))))
            txt_items.append("%s by %s: %s" % (a["name"], a.get("maker", ""), a.get("oneLiner", "")))
        return "<ul>%s</ul>" % "".join(html_items), " ".join(t if t.endswith(".") else t + "." for t in txt_items)

    intro_t = ("agentictools.design is a free directory of AI agents and AI tools for product designers and product managers, "
               "updated daily. Each listing explains what the tool does in about 30 seconds, who it is for, what it is best at "
               "and what it costs, and is checked against the product's own website. It lists %d agents across %d categories, "
               "plus %d workflows that chain them together." % (n_agents, n_cats, n_wf))
    items.append(("What is agentictools.design?", "<p>%s</p>" % e(intro_t), intro_t))

    groups = [
        ("What are the best AI agents for product designers?", ("design",),
         "These are the design agents in the directory right now, newest first:"),
        ("Which AI tools turn a prompt or a design into a working prototype?", ("prototype",),
         "These prototyping tools are in the directory right now, newest first:"),
        ("What AI tools should product managers use?", ("pm",),
         "These product and spec tools are in the directory right now, newest first:"),
        ("What AI tools help with user research?", ("research",),
         "These research tools are in the directory right now, newest first:"),
        ("Which AI coding agents can build what designers and PMs spec?", ("build",),
         "These build tools are in the directory right now, newest first:"),
    ]
    for q, keys, lead in groups:
        ag = by_cat(*keys)
        if not ag:
            continue
        lst_h, lst_t = agent_list(ag)
        more = len(ag) - min(len(ag), 8)
        tail = (" There are %d more in the full directory." % more) if more else ""
        items.append((q, "<p>%s</p>%s%s" % (e(lead), lst_h, ("<p>%s</p>" % e(tail.strip())) if tail else ""),
                      "%s %s%s" % (lead, lst_t, tail)))

    if D["workflows"]:
        w = D["workflows"][0]
        names = tool_names(D, w)
        t = ("A workflow is a short, repeatable chain of AI tools that ends in something you can ship or share. For example, "
             "\"%s\" uses %s: %s The result: %s. The directory has %d workflows."
             % (w["title"], ", ".join(names), " ".join("%d. %s." % (i + 1, s.rstrip(".")) for i, s in enumerate(w.get("steps") or [])),
                (w.get("outcome") or "").rstrip("."), n_wf))
        h = ('<p>A workflow is a short, repeatable chain of AI tools that ends in something you can ship or share. For example, '
             '<a href="/workflows/%s/">%s</a> uses %s:</p><ul>%s</ul><p>The result: %s. The directory has %d workflows.</p>'
             % (e(w["id"]), e(w["title"]), e(", ".join(names)), "".join("<li>%s</li>" % e(s) for s in w.get("steps") or []),
                e((w.get("outcome") or "").rstrip(".")), n_wf))
        items.append(("What is an AI agent workflow for design and product work?", h, t))

    t = ("New agents and workflows are added daily, and the directory was last updated on %s. Every listing is checked on the "
         "product's own official website, and the link on each listing goes straight to that site." % fmt_date(D["updated"]))
    items.append(("How often is the directory updated, and how are tools checked?", "<p>%s</p>" % e(t), t))

    t = "Yes. The directory is free to browse, and the weekly email with the best new agents and one workflow is free too."
    items.append(("Is agentictools.design free?", '<p>%s <a href="#subscribe">Get the weekly email</a>.</p>' % e(t), t))

    t = ("Sponsors get a featured card at the top of the directory, always labeled as sponsored. "
         "Use the Sponsor a spot section on this page to get in touch.")
    items.append(("Can I sponsor a spot or get my AI tool featured?", '<p>%s <a href="#sponsor">Sponsor a spot</a>.</p>' % e(t), t))
    return items


def blk_faq(D):
    rows = "".join('<details><summary><h3>%s</h3>%s</summary><div class="a">%s</div></details>' % (e(q), CHEV, h)
                   for q, h, _ in faq_items(D))
    return ('<section class="block" id="faq" aria-labelledby="faqTitle">\n    <div class="sechead"><div>'
            '<span class="eyebrow">Questions</span><h2 id="faqTitle">AI agents for designers and PMs, answered</h2>'
            '<p>Plain answers, rebuilt from the directory every day.</p></div></div>\n'
            '    <div class="faq">%s</div>\n  </section>' % rows)


# ---------------------------------------------------------------- head / JSON-LD

def common_meta(title, desc, url, og_type="website", modified=None):
    m = [
        "<title>%s</title>" % e(title),
        '<meta name="description" content="%s">' % e(desc),
        '<link rel="canonical" href="%s">' % e(url),
        '<meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1">',
        '<meta name="theme-color" content="#F6F6F3">',
        '<meta property="og:site_name" content="%s">' % NAME,
        '<meta property="og:type" content="%s">' % og_type,
        '<meta property="og:title" content="%s">' % e(title),
        '<meta property="og:description" content="%s">' % e(desc),
        '<meta property="og:url" content="%s">' % e(url),
        '<meta property="og:image" content="%s">' % OG_IMAGE,
        '<meta property="og:image:width" content="1200">',
        '<meta property="og:image:height" content="630">',
        '<meta property="og:image:alt" content="agentictools.design: every new AI agent for design and product work, explained in 30 seconds">',
        '<meta property="og:locale" content="en_US">',
        '<meta name="twitter:card" content="summary_large_image">',
        '<meta name="twitter:title" content="%s">' % e(title),
        '<meta name="twitter:description" content="%s">' % e(desc),
        '<meta name="twitter:image" content="%s">' % OG_IMAGE,
        '<link rel="alternate" type="text/plain" title="LLM summary" href="/llms.txt">',
    ]
    if modified:
        m.append('<meta property="og:updated_time" content="%s">' % e(modified))
    return m


def software_ld(a, with_page=True):
    o = {"@type": "SoftwareApplication", "name": a["name"], "description": a.get("oneLiner", ""),
         "applicationCategory": APP_CAT.get(a.get("category"), "BusinessApplication"),
         "operatingSystem": "Web", "audience": {"@type": "Audience", "audienceType": a.get("forWho", "")}}
    if a.get("maker"):
        o["creator"] = {"@type": "Organization", "name": a["maker"]}
    u = safe_url(a.get("url"))
    if u:
        o["sameAs"] = u
    if with_page:
        o["url"] = agent_page(a)
    if a.get("tags"):
        o["keywords"] = ", ".join(a["tags"])
    return o


def home_desc(D):
    n_agents, _, n_wf = counts(D)
    return clip("A daily-updated directory of %d AI agents and tools for product designers and product managers. "
                "What each one does in 30 seconds, who it's for, pricing, and %d workflows that work." % (n_agents, n_wf), 300)


def blk_head(D):
    desc = home_desc(D)
    m = common_meta(HOME_TITLE, desc, SITE + "/", modified=D["updated"])
    website = {"@type": "WebSite", "@id": SITE + "/#website", "name": NAME, "url": SITE + "/",
               "description": "AI agents and tools for designers and product managers, explained in 30 seconds and updated daily.",
               "inLanguage": "en", "publisher": {"@id": SITE + "/#org"}}
    org = {"@type": "Organization", "@id": SITE + "/#org", "name": NAME, "url": SITE + "/",
           "logo": SITE + "/apple-touch-icon.png"}
    page = {"@type": "CollectionPage", "@id": SITE + "/#page", "url": SITE + "/", "name": HOME_TITLE,
            "description": desc, "isPartOf": {"@id": SITE + "/#website"}, "dateModified": D["updated"], "inLanguage": "en",
            "about": [{"@type": "Thing", "name": "AI agents for product design"},
                      {"@type": "Thing", "name": "AI tools for product managers"}],
            "mainEntity": {"@type": "ItemList", "name": "AI agents for designers and product managers",
                           "numberOfItems": len(D["agents"]),
                           "itemListElement": [{"@type": "ListItem", "position": i + 1, "url": agent_page(a),
                                                "item": software_ld(a)} for i, a in enumerate(D["agents"])]}}
    faq = {"@type": "FAQPage", "@id": SITE + "/#faq",
           "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": t}}
                          for q, _, t in faq_items(D)]}
    graph = {"@context": "https://schema.org", "@graph": [website, org, page, faq]}
    m.append('<script type="application/ld+json">%s</script>' % ld(graph))
    return "\n".join(m)


# ---------------------------------------------------------------- subpages

SUB_CSS = """
/* subpages */
.crumbs{font:400 12px var(--font-mono);color:var(--ink-3);padding-block:12px 0;display:flex;gap:8px;flex-wrap:wrap}
.crumbs a{text-decoration:none}.crumbs a:hover{color:var(--ink)}
.subhero{padding-block:28px 28px;display:grid;gap:14px;max-width:760px}
.subhero h1{font-weight:400;font-size:clamp(28px,4.2vw,42px);line-height:1.08;letter-spacing:-.025em;margin:0;text-wrap:balance}
.subhero p{margin:0;font-size:clamp(16px,1.8vw,19px);color:var(--ink-2);max-width:60ch;text-wrap:pretty}
.page-win .detail{overflow:visible}
.faq .a ol{margin:0 0 10px;padding-left:20px}
.faq .a ol li{margin-bottom:4px}
.page-win .dhead h2{margin:0;font-size:20px;font-weight:500;letter-spacing:-.01em}
.page-win .wfmain{padding:22px 26px}
.page-win .wfmain h2{margin:0;font-size:15px;font-weight:500}
.links{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:4px 16px;border-top:1px solid var(--line);padding-top:10px}
.links a.row{text-decoration:none}
.cta-band{display:flex;flex-wrap:wrap;gap:16px 32px;align-items:center;justify-content:space-between;border:1px solid var(--line);border-radius:10px;padding:clamp(18px,3vw,28px);background:var(--window)}
.cta-band h2{margin:0 0 6px;font-size:clamp(20px,2.2vw,24px);font-weight:400;letter-spacing:-.02em}
.cta-band p{margin:0;color:var(--ink-2);max-width:58ch}
"""

FONT_LINKS = """<link rel="icon" href="/favicon.svg?v=2" type="image/svg+xml">
<link rel="icon" href="/favicon-32.png?v=2" type="image/png" sizes="32x32">
<link rel="apple-touch-icon" href="/apple-touch-icon.png?v=2">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500&display=swap">
<link rel="stylesheet" href="/assets/site.css">"""


def nav():
    return ('<nav class="top" aria-label="Main"><a class="brand" href="/">%s%s</a>'
            '<div class="navlinks"><a href="/#directory">Directory</a><a href="/#workflows">Workflows</a>'
            '<a href="/#all">All agents</a><a href="/#faq">FAQ</a></div>'
            '<a class="pill dark" href="/#subscribe">Subscribe</a></nav>' % (GLYPH, NAME))


def footer(D):
    return ('<footer><div><a class="brand" href="/">%s%s</a></div>'
            '<p>Refreshed daily, last on %s. Every listing is checked against the product\'s own site.</p>'
            '<p>Sponsored listings are always labeled.</p></footer>' % (GLYPH, NAME, e(fmt_date(D["updated"]))))


def cta_band():
    return ('<section class="block"><div class="cta-band"><div><h2>New agents, once a week.</h2>'
            '<p>The best additions from the directory and one workflow worth stealing, in your inbox every week.</p></div>'
            '<a class="pill dark big" href="/#subscribe">Get the weekly email</a></div></section>')


def page_shell(D, head_meta, body):
    return ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n%s\n%s\n</head>\n<body>\n"
            "<div class=\"wrap\">\n%s\n<main>\n%s\n</main>\n%s\n</div>\n</body>\n</html>\n"
            % ("\n".join(head_meta), FONT_LINKS, nav(), body, footer(D)))


def row_link(a, D):
    return ('<a class="row" href="/agents/%s/">%s<span class="txt"><b>%s</b><span>%s · %s</span></span>%s</a>'
            % (e(a["id"]), mark(a), e(a["name"]), e(a.get("maker", "")), e(CATS.get(a.get("category"), "")), new_badge(D, a)))


def build_agent_page(D, a):
    cat = CATS.get(a.get("category"), "General")
    title = "%s by %s: what it does, pricing and who it's for | %s" % (a["name"], a.get("maker", ""), NAME)
    desc = clip("%s Who it's for: %s. Pricing: %s." % (a.get("oneLiner", "").rstrip(".") + ".",
                                                     (a.get("forWho") or "designers and PMs").rstrip("."),
                                                     (a.get("pricing") or "see site").rstrip(".")), 300)
    url = agent_page(a)
    m = common_meta(title, desc, url, og_type="article", modified=a.get("verified"))
    app = software_ld(a)
    app["mainEntityOfPage"] = url
    graph = {"@context": "https://schema.org", "@graph": [
        dict(app, **{"@id": url + "#app"}),
        {"@type": "WebPage", "@id": url, "url": url, "name": title, "description": desc, "inLanguage": "en",
         "isPartOf": {"@id": SITE + "/#website"}, "about": {"@id": url + "#app"},
         "dateModified": a.get("verified") or D["updated"], "datePublished": a.get("added") or D["updated"]},
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "AI agents directory", "item": SITE + "/"},
            {"@type": "ListItem", "position": 2, "name": a["name"], "item": url}]}]}
    m.append('<script type="application/ld+json">%s</script>' % ld(graph))

    u = safe_url(a.get("url"))
    wfs = [w for w in D["workflows"] if a["id"] in (w.get("tools") or [])]
    related = [x for x in D["agents"] if x.get("category") == a.get("category") and x["id"] != a["id"]]
    others = [x for x in D["agents"] if x.get("category") != a.get("category")][: max(0, 6 - len(related))]

    detail = (
        '<div class="dhead">%s<div><h2>%s</h2><p>%s · %s</p></div>%s</div>'
        '<div class="thirty"><span class="eyebrow"><span>In 30 seconds</span><span>0:30</span></span><p>%s</p></div>'
        '<dl class="facts"><dt>For</dt><dd>%s</dd><dt>Best at</dt><dd>%s</dd><dt>Pricing</dt><dd>%s</dd>'
        '<dt>Category</dt><dd>%s</dd><dt>Maker</dt><dd>%s</dd></dl>'
        '<div class="tags">%s</div>'
        '<div class="dfoot"><span class="checked">Checked on its own site %s</span>%s</div>'
    ) % (mark(a), e(a["name"]), e(a.get("maker", "")), e(cat), new_badge(D, a), e(a.get("oneLiner", "")),
         e(a.get("forWho", "")), e(a.get("standout", "")), e(a.get("pricing") or "See site"), e(cat), e(a.get("maker", "")),
         "".join('<span class="tag">%s</span>' % e(t) for t in a.get("tags") or []),
         e(fmt_date(a.get("verified") or D["updated"])),
         ('<a class="pill dark" href="%s" target="_blank" rel="noopener noreferrer">Visit %s ↗</a>' % (e(u), e(a["name"]))) if u else "")

    body = ['<div class="crumbs"><a href="/">Directory</a><span>/</span><a href="/#all">%s</a><span>/</span><span>%s</span></div>'
            % (e(cat), e(a["name"])),
            '<header class="subhero"><h1>%s by %s</h1><p>%s</p></header>' % (e(a["name"]), e(a.get("maker", "")), e(a.get("oneLiner", ""))),
            '<div class="stage"><div class="stage-inner"><article class="win page-win"><div class="bar"><span class="lights" aria-hidden="true">'
            '<i></i><i></i><i></i></span><span class="t">agentictools.design · %s</span></div><div class="detail">%s</div></article></div></div>'
            % (e(a["name"]), detail)]
    if wfs:
        body.append('<section class="block"><div class="sechead"><div><span class="eyebrow">Workflows</span>'
                    '<h2>Workflows that use %s</h2></div></div><div class="faq">%s</div></section>'
                    % (e(a["name"]), "".join(
                        '<details open><summary><h3>%s</h3>%s</summary><div class="a"><ol>%s</ol><p>Result: %s. '
                        '<a href="/workflows/%s/">Open this workflow</a></p></div></details>'
                        % (e(w["title"]), CHEV, "".join("<li>%s</li>" % e(s) for s in w.get("steps") or []),
                           e((w.get("outcome") or "").rstrip(".")), e(w["id"])) for w in wfs)))
    if related or others:
        body.append('<section class="block"><div class="sechead"><div><span class="eyebrow">Keep browsing</span>'
                    '<h2>%s</h2></div></div><div class="links">%s</div></section>'
                    % ("More %s agents" % e(cat.lower()) if related else "More AI agents",
                       "".join(row_link(x, D) for x in (related + others)[:12])))
    body.append(cta_band())
    return page_shell(D, m, "\n".join(body))


def build_wf_page(D, w):
    names = tool_names(D, w)
    title = "%s: an AI workflow for designers and PMs | %s" % (w["title"], NAME)
    desc = clip("%s, using %s. Result: %s." % (w["title"], ", ".join(names), (w.get("outcome") or "").rstrip(".")), 300)
    url = wf_page(w)
    m = common_meta(title, desc, url, og_type="article", modified=w.get("added"))
    howto = {"@type": "HowTo", "@id": url + "#howto", "name": w["title"], "description": desc,
             "tool": [{"@type": "HowToTool", "name": n} for n in names],
             "step": [{"@type": "HowToStep", "position": i + 1, "text": s} for i, s in enumerate(w.get("steps") or [])]}
    graph = {"@context": "https://schema.org", "@graph": [
        howto,
        {"@type": "WebPage", "@id": url, "url": url, "name": title, "description": desc, "inLanguage": "en",
         "isPartOf": {"@id": SITE + "/#website"}, "datePublished": w.get("added") or D["updated"]},
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "AI agents directory", "item": SITE + "/"},
            {"@type": "ListItem", "position": 2, "name": w["title"], "item": url}]}]}
    m.append('<script type="application/ld+json">%s</script>' % ld(graph))
    tools = [D["by_id"][t] for t in (w.get("tools") or []) if t in D["by_id"]]
    body = ['<div class="crumbs"><a href="/">Directory</a><span>/</span><a href="/#workflows">Workflows</a><span>/</span><span>%s</span></div>' % e(w["title"]),
            '<header class="subhero"><h1>%s</h1><p>%s</p></header>' % (e(w["title"]), e((w.get("outcome") or "").rstrip(".") + ".")),
            '<div class="stage"><div class="stage-inner"><article class="win page-win"><div class="bar"><span class="lights" aria-hidden="true">'
            '<i></i><i></i><i></i></span><span class="t">agentictools.design · Workflow</span></div><div class="wfmain">'
            '<h2>The steps</h2><div class="ask">Uses %s</div><ol class="steps">%s</ol><p class="done"><b>Done</b><span>%s</span></p>'
            '</div></article></div></div>' % (e(", ".join(names)), "".join("<li><span>%s</span></li>" % e(s) for s in w.get("steps") or []),
                                              e(w.get("outcome", ""))),
            '<section class="block"><div class="sechead"><div><span class="eyebrow">In this workflow</span><h2>The tools</h2></div></div>'
            '<div class="links">%s</div></section>' % "".join(row_link(a, D) for a in tools),
            cta_band()]
    return page_shell(D, m, "\n".join(body))


def build_404(D):
    m = ["<title>Page not found | %s</title>" % NAME, '<meta name="robots" content="noindex">']
    body = ('<header class="subhero"><h1>That page isn\'t here.</h1><p>The agent or workflow may have a new address. '
            'Everything is listed in the directory.</p><div class="cta"><a class="pill dark big" href="/#all">Browse the directory</a></div></header>')
    return page_shell(D, m, body)


# ---------------------------------------------------------------- text files for crawlers and LLMs

def robots():
    bots = ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-SearchBot", "Claude-User", "anthropic-ai",
            "PerplexityBot", "Perplexity-User", "Google-Extended", "Applebot", "Applebot-Extended", "Bingbot",
            "DuckAssistBot", "Meta-ExternalAgent", "MistralAI-User", "CCBot", "Amazonbot", "YouBot"]
    lines = ["# agentictools.design welcomes search engines and AI assistants.", ""]
    for b in bots:
        lines += ["User-agent: %s" % b, "Allow: /", ""]
    lines += ["User-agent: *", "Allow: /", "", "Sitemap: %s/sitemap.xml" % SITE, ""]
    return "\n".join(lines)


def sitemap(D):
    urls = [(SITE + "/", D["updated"], "daily", "1.0")]
    urls += [(agent_page(a), a.get("verified") or a.get("added") or D["updated"], "weekly", "0.8") for a in D["agents"]]
    urls += [(wf_page(w), w.get("added") or D["updated"], "monthly", "0.6") for w in D["workflows"]]
    body = "".join("  <url><loc>%s</loc>%s<changefreq>%s</changefreq><priority>%s</priority></url>\n"
                   % (e(u), ("<lastmod>%s</lastmod>" % e(d)) if parse_date(d) else "", f, p) for u, d, f, p in urls)
    return '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n%s</urlset>\n' % body


def md(s):
    return re.sub(r"[\r\n]+", " ", str(s or "")).replace("[", "(").replace("]", ")")


def llms(D, full=False):
    n_agents, n_cats, n_wf = counts(D)
    out = ["# agentictools.design", "",
           "> A free, daily-updated directory of AI agents and AI tools for product designers and product managers. "
           "Each listing says what the tool does in 30 seconds, who it is for, what it is best at and what it costs, "
           "checked against the product's own website. %d agents, %d categories, %d workflows. Last updated %s."
           % (n_agents, n_cats, n_wf, D["updated"]), "",
           "Machine-readable data: %s/agents.json (fields: name, maker, category, url, oneLiner, forWho, standout, pricing, tags, verified, added)." % SITE,
           ""]
    for k in cats_present(D):
        out.append("## %s" % CATS[k])
        out.append("")
        for a in [x for x in D["agents"] if x.get("category") == k]:
            if full:
                out.append("### %s (by %s)" % (md(a["name"]), md(a.get("maker"))))
                out.append("- Profile: %s" % agent_page(a))
                u = safe_url(a.get("url"))
                if u:
                    out.append("- Official site: %s" % u)
                out.append("- What it does: %s" % md(a.get("oneLiner")))
                out.append("- For: %s" % md(a.get("forWho")))
                out.append("- Best at: %s" % md(a.get("standout")))
                out.append("- Pricing: %s" % md(a.get("pricing") or "See site"))
                if a.get("tags"):
                    out.append("- Tags: %s" % ", ".join(md(t) for t in a["tags"]))
                out.append("- Checked on its own site: %s" % md(a.get("verified") or D["updated"]))
                out.append("")
            else:
                out.append("- [%s](%s): %s (by %s)" % (md(a["name"]), agent_page(a), md(a.get("oneLiner")), md(a.get("maker"))))
        out.append("")
    out.append("## Workflows")
    out.append("")
    for w in D["workflows"]:
        names = ", ".join(md(n) for n in tool_names(D, w))
        if full:
            out.append("### %s" % md(w["title"]))
            out.append("- Page: %s" % wf_page(w))
            out.append("- Tools: %s" % names)
            for i, s in enumerate(w.get("steps") or []):
                out.append("%d. %s" % (i + 1, md(s)))
            out.append("- Result: %s" % md(w.get("outcome")))
            out.append("")
        else:
            out.append("- [%s](%s): %s, using %s" % (md(w["title"]), wf_page(w), md(w.get("outcome")), names))
    out.append("")
    if not full:
        out += ["## Optional", "", "- [Full text of every listing](%s/llms-full.txt)" % SITE,
                "- [Directory data as JSON](%s/agents.json)" % SITE, ""]
    return "\n".join(out)


# ---------------------------------------------------------------- main

def replace_block(src, name, content):
    pat = re.compile(r"(<!--b:%s-->)(.*?)(<!--/b:%s-->)" % (re.escape(name), re.escape(name)), re.S)
    if len(pat.findall(src)) != 1:
        sys.exit("build: marker b:%s missing or repeated in index.html" % name)
    return pat.sub(lambda m: m.group(1) + content + m.group(3), src)


def write(rel, text):
    path = os.path.join(ROOT, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    old = None
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            old = f.read()
    if old != text:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)


def main():
    D = load()
    idx_path = os.path.join(ROOT, "index.html")
    with open(idx_path, encoding="utf-8") as f:
        src = f.read()
    blocks = {
        "head": "\n" + blk_head(D) + "\n",
        "fresh": e(fresh_line(D)),
        "cats": blk_cats(D),
        "list": blk_list(D),
        "detail": blk_detail(D),
        "log": blk_log(D),
        "wfcount": e("Ready to run %d" % len(D["workflows"])),
        "wflist": blk_wflist(D),
        "wfmain": blk_wfmain(D),
        "allcount": e("%d agents · %d categories" % (len(D["agents"]), len(cats_present(D)))),
        "chips": blk_chips(D),
        "table": blk_table(D),
        "faq": blk_faq(D),
        "footfresh": e("Refreshed daily, last on %s. Every listing is checked against the product's own site." % fmt_date(D["updated"])),
    }
    for k, v in blocks.items():
        src = replace_block(src, k, v)
    write("index.html", src)

    style = re.search(r"<style>(.*?)</style>", src, re.S)
    if not style:
        sys.exit("build: no <style> in index.html")
    write("assets/site.css", style.group(1).strip() + "\n" + SUB_CSS)

    # profile pages: rebuild the folders so removed or renamed ids don't linger
    for folder, items, fn in (("agents", D["agents"], build_agent_page), ("workflows", D["workflows"], build_wf_page)):
        base = os.path.join(ROOT, folder)
        keep = {x["id"] for x in items}
        if os.path.isdir(base):
            for name in os.listdir(base):
                if name not in keep and os.path.isdir(os.path.join(base, name)):
                    shutil.rmtree(os.path.join(base, name))
        for x in items:
            write("%s/%s/index.html" % (folder, x["id"]), fn(D, x))

    write("404.html", build_404(D))
    write("sitemap.xml", sitemap(D))
    write("robots.txt", robots())
    write("llms.txt", llms(D))
    write("llms-full.txt", llms(D, full=True))
    print("build: %d agents, %d workflows, updated %s" % (len(D["agents"]), len(D["workflows"]), D["updated"]))


if __name__ == "__main__":
    main()
