#!/usr/bin/env python3
"""Build the crawlable parts of agentictools.design from agents.json.

Runs on every push to main (see .github/workflows/build.yml), so the daily
refresh only has to change agents.json. It is a pure function of agents.json
and index.html: running it twice gives the same files.

It writes:
  index.html            use cases, the directory, workflows and FAQ baked into the
                        page between <!--b:NAME--> markers, plus meta tags and JSON-LD
  use-cases/index.html  the hub: which agents to use for what
  use-cases/<id>/index.html  one page per use case (question H1, answer first,
                        the setup in order, alternatives, HowTo and FAQ JSON-LD)
  agents/<id>/index.html  one profile page per agent, listing its use cases
  workflows/<id>/index.html  one page per workflow
  assets/site.css       the page's own styles, shared by the subpages
  sitemap.xml, robots.txt, llms.txt, llms-full.txt, 404.html

Standard library only.
"""
import datetime as dt
import hashlib
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

# Use cases are grouped by where they sit in the product work, in this order.
STAGES = {"discover": "Understand users", "define": "Decide what to build",
          "design": "Design and prototype", "ship": "Build and ship"}

HOME_TITLE = "Which AI Agents to Use for What: Setups for Designers and PMs | agentictools.design"
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
    by_id = {a["id"]: a for a in uniq}
    wf_ids = {w["id"] for w in wfs}

    # Use cases are editorial and reference agents by id. Anything that points
    # at a missing agent or workflow is dropped quietly, and a use case with no
    # usable setup step is skipped, so new or odd data can never break the build.
    ucs, seen_uc = [], set()
    for u in d.get("usecases", []) or []:
        if not isinstance(u, dict) or not ID_OK.match(str(u.get("id", ""))) or not str(u.get("job") or "").strip():
            continue
        if u["id"] in seen_uc:
            continue
        setup = [s for s in u.get("setup") or [] if isinstance(s, dict) and s.get("tool") in by_id]
        if not setup:
            continue
        in_setup = {s["tool"] for s in setup}
        alts, seen_alt = [], set()
        for s in u.get("alternatives") or []:
            if isinstance(s, dict) and s.get("tool") in by_id and s["tool"] not in in_setup and s["tool"] not in seen_alt:
                seen_alt.add(s["tool"])
                alts.append(s)
        seen_uc.add(u["id"])
        ucs.append(dict(u, setup=setup, alternatives=alts,
                        workflows=[w for w in u.get("workflows") or [] if w in wf_ids],
                        stage=u.get("stage") if u.get("stage") in STAGES else "design"))
    ucs = [u for k in STAGES for u in ucs if u["stage"] == k]
    return {
        "updated": updated,
        "updates": [u for u in d.get("updates", []) if isinstance(u, dict)],
        "agents": ordered(uniq),
        "workflows": ordered(wfs),
        "usecases": ucs,
        "is_new": is_new,
        "by_id": by_id,
    }


def cats_present(D):
    return [k for k in CATS if any(a.get("category") == k for a in D["agents"])]


def agent_page(a):
    return "%s/agents/%s/" % (SITE, a["id"])


def wf_page(w):
    return "%s/workflows/%s/" % (SITE, w["id"])


def uc_page(u):
    return "%s/use-cases/%s/" % (SITE, u["id"])


UC_HUB = SITE + "/use-cases/"


def lower_first(s):
    s = str(s or "").strip().rstrip(".?")
    if len(s) > 1 and s[1].isupper():   # keeps "AI ..." or "PRD ..." intact
        return s
    return s[:1].lower() + s[1:]


def uc_question(u):
    return "What's the best AI setup to %s?" % lower_first(u["job"])


def uc_title(D, u):
    year = (parse_date(D["updated"]) or dt.date.today()).year
    return "Best AI setup to %s (%d) | %s" % (lower_first(u["job"]), year, NAME)


def uc_tools(D, u):
    return [D["by_id"][s["tool"]] for s in u["setup"]]


def uc_chain(D, u):
    return " → ".join(a["name"] for a in uc_tools(D, u))


def ucs_for_agent(D, a):
    """(use case, 'setup' step number or 'alt', the line about it) for every use case naming this agent."""
    out = []
    for u in D["usecases"]:
        for i, s in enumerate(u["setup"]):
            if s["tool"] == a["id"]:
                out.append((u, i + 1, s.get("does", "")))
        for s in u["alternatives"]:
            if s["tool"] == a["id"]:
                out.append((u, "alt", s.get("when", "")))
    return out


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
         ('<a class="pill" href="%s" target="_blank" rel="noopener noreferrer" data-agent="%s">Visit site ↗</a>' % (e(u), e(a["name"]))) if u else "")


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
               ('<a class="pill" href="%s" target="_blank" rel="noopener noreferrer" data-agent="%s">Visit site ↗</a>' % (e(u), e(a["name"]))) if u else ""))
    return "".join(out)


def counts(D):
    return len(D["agents"]), len(cats_present(D)), len(D["workflows"])


def fresh_line(D):
    n_new = sum(1 for x in D["agents"] + D["workflows"] if D["is_new"](x))
    n_uc = len(D["usecases"])
    return "Updated %s · %d agents%s%s" % (fmt_date(D["updated"]), len(D["agents"]),
                                          (" · %d use cases" % n_uc) if n_uc else "",
                                          (" · %d new this week" % n_new) if n_new else "")


def uc_card(D, u, answer_len=150):
    return ('<a class="uc" href="/use-cases/%s/"><b>%s</b><span class="ucans">%s</span>'
            '<span class="uctools">%s</span></a>'
            % (e(u["id"]), e(u["job"]), e(clip(u.get("answer"), answer_len)),
               ' <i aria-hidden="true">→</i> '.join(e(a["name"]) for a in uc_tools(D, u))))


def uc_groups(D, heading="h3"):
    out = []
    for k, label in STAGES.items():
        items = [u for u in D["usecases"] if u["stage"] == k]
        if items:
            out.append('<div class="ucgroup"><%s class="eyebrow">%s</%s><div class="ucgrid">%s</div></div>'
                       % (heading, e(label), heading, "".join(uc_card(D, u) for u in items)))
    return '<div class="ucgroups">%s</div>' % "".join(out)


def blk_usecases(D):
    if not D["usecases"]:
        return '<p class="checked">Use cases are on their way.</p>'
    return uc_groups(D)


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

    n_uc = len(D["usecases"])
    intro_t = ("agentictools.design is a free guide to which AI agents product designers and product managers should use "
               "for which job. %sIt also keeps a directory of %d AI agents across %d categories, updated daily, where each "
               "listing explains what the tool does in about 30 seconds, who it is for, what it is best at and what it costs, "
               "checked against the product's own website, plus %d workflows that chain them together."
               % (("It has %d use cases, each with the recommended setup: which agents to use, in what order, and why. " % n_uc)
                  if n_uc else "", n_agents, n_cats, n_wf))
    items.append(("What is agentictools.design?", "<p>%s</p>" % e(intro_t), intro_t))

    if D["usecases"]:
        lis_h, lis_t = [], []
        for u in D["usecases"]:
            lis_h.append('<li><a href="/use-cases/%s/">%s</a>: %s</li>' % (e(u["id"]), e(u["job"]), e(uc_chain(D, u))))
            lis_t.append("%s: %s." % (u["job"], uc_chain(D, u).replace(" → ", ", then ")))
        lead = "It depends on the job. These are the setups we recommend, with the agents in the order you'd use them:"
        items.append(("Which AI agents should designers and PMs use for what?",
                      '<p>%s</p><ul>%s</ul><p><a href="/use-cases/">See every use case with the reasons</a>.</p>'
                      % (e(lead), "".join(lis_h)),
                      "%s %s" % (lead, " ".join(lis_t))))

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
    if D["usecases"]:
        return clip("Which AI agents to use for what. %d jobs designers and PMs actually do, each with the setup to use, "
                    "in what order, and why. Plus a daily-updated directory of %d AI agents." % (len(D["usecases"]), n_agents), 300)
    return clip("A daily-updated directory of %d AI agents and tools for product designers and product managers. "
                "What each one does in 30 seconds, who it's for, pricing, and %d workflows that work." % (n_agents, n_wf), 300)


def uc_itemlist(D, at):
    return {"@type": "ItemList", "@id": at, "name": "AI agent setups for designers and PMs, by use case",
            "numberOfItems": len(D["usecases"]),
            "itemListElement": [{"@type": "ListItem", "position": i + 1, "url": uc_page(u), "name": uc_question(u)}
                                for i, u in enumerate(D["usecases"])]}


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
    if D["usecases"]:
        page["about"].insert(0, {"@type": "Thing", "name": "Which AI agents to use for design and product work"})
        page["hasPart"] = {"@id": SITE + "/#usecases"}
        graph["@graph"].append(uc_itemlist(D, SITE + "/#usecases"))
    m.append('<script type="application/ld+json">%s</script>' % ld(graph))
    return GA_HEAD + "\n" + "\n".join(m)


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
.subhero .eyebrow{line-height:1.5}
.subhero p.lede{color:var(--ink);font-size:clamp(17px,1.9vw,20px);line-height:1.45}
.subhero .meta{font:400 12.5px/1.6 var(--font-mono);color:var(--ink-3)}
.ucsteps{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:16px;counter-reset:s}
.ucsteps li{display:grid;grid-template-columns:22px minmax(0,1fr);gap:10px;align-items:start}
.ucsteps li::before{counter-increment:s;content:counter(s);font:500 11px/20px var(--font-mono);text-align:center;width:20px;height:20px;border-radius:50%;border:1px solid var(--line);color:var(--ink-2);margin-top:12px}
.ucstep{display:grid;gap:2px;min-width:0}
.ucstep a.row,.alt a.row{text-decoration:none;padding-left:0}
.ucstep p{margin:0;font-size:14.5px;line-height:1.5}
.ucstep .checked{margin-top:2px}
.watch{border:1px solid var(--line);border-radius:8px;padding:12px 14px;background:var(--canvas);font-size:14.5px;margin:0}
.watch .eyebrow{display:block;margin-bottom:6px;color:var(--accent)}
.alts{border-top:1px solid var(--line)}
.alt{display:grid;grid-template-columns:minmax(0,280px) minmax(0,1fr);gap:4px 24px;align-items:center;padding:10px 0;border-bottom:1px solid var(--line)}
.alt p{margin:0;color:var(--ink-2);font-size:14.5px}
.alt a.job{font-weight:500;text-decoration:none}.alt a.job:hover{color:var(--accent)}
.hubq{border-bottom:1px solid var(--line);padding:18px 4px}
.hubq h3{margin:0 0 6px;font-size:17px;font-weight:500;letter-spacing:-.01em}
.hubq h3 a{text-decoration:none}.hubq h3 a:hover{color:var(--accent)}
.hubq p{margin:0 0 6px;color:var(--ink-2);max-width:74ch}
.hubq .uctools{font:400 12px/1.5 var(--font-mono);color:var(--ink-3)}
.hublist{border-top:1px solid var(--line)}
@media (max-width:760px){.alt{grid-template-columns:1fr}}
"""

FONT_LINKS = """<link rel="icon" href="/favicon.svg?v=2" type="image/svg+xml">
<link rel="icon" href="/favicon-32.png?v=2" type="image/png" sizes="32x32">
<link rel="apple-touch-icon" href="/apple-touch-icon.png?v=2">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500&display=swap">
<link rel="stylesheet" href="/assets/site.css?v=%s">"""

# set in main() to a short hash of site.css, so a style change reaches
# returning visitors instead of waiting on their cached copy
CSS_VER = "1"

# Google Analytics 4. Goes at the top of <head> on every page (home page via
# blk_head, subpages via page_shell), so every rebuild keeps it.
# /assets/track.js adds the click events (outbound, subscribe, sponsor copy).
GA_ID = "G-976LM8B3MJ"
GA_HEAD = ("<!-- Google tag (gtag.js) -->\n"
           '<script async src="https://www.googletagmanager.com/gtag/js?id=%s"></script>\n'
           "<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}"
           "gtag('js',new Date());gtag('config','%s');</script>\n"
           '<script defer src="/assets/track.js"></script>' % (GA_ID, GA_ID))


def nav():
    return ('<nav class="top" aria-label="Main"><a class="brand" href="/">%s%s</a>'
            '<div class="navlinks"><a href="/use-cases/">Use cases</a><a href="/#directory">Directory</a><a href="/#workflows">Workflows</a>'
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
            % (GA_HEAD + "\n" + "\n".join(head_meta), FONT_LINKS % CSS_VER, nav(), body, footer(D)))


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
         ('<a class="pill dark" href="%s" target="_blank" rel="noopener noreferrer" data-agent="%s">Visit %s ↗</a>' % (e(u), e(a["name"]), e(a["name"]))) if u else "")

    fits = ucs_for_agent(D, a)
    body = ['<div class="crumbs"><a href="/">Directory</a><span>/</span><a href="/#all">%s</a><span>/</span><span>%s</span></div>'
            % (e(cat), e(a["name"])),
            '<header class="subhero"><h1>%s by %s</h1><p>%s</p></header>' % (e(a["name"]), e(a.get("maker", "")), e(a.get("oneLiner", ""))),
            '<div class="stage"><div class="stage-inner"><article class="win page-win"><div class="bar"><span class="lights" aria-hidden="true">'
            '<i></i><i></i><i></i></span><span class="t">agentictools.design · %s</span></div><div class="detail">%s</div></article></div></div>'
            % (e(a["name"]), detail)]
    if fits:
        rows = []
        for u, where, line in fits:
            label = ("Step %d of %d" % (where, len(u["setup"]))) if where != "alt" else "Swap in when"
            rows.append('<div class="alt"><a class="job" href="/use-cases/%s/">%s</a><p><span class="checked">%s</span> %s</p></div>'
                        % (e(u["id"]), e(u["job"]), e(label), e(line)))
        body.append('<section class="block"><div class="sechead"><div><span class="eyebrow">Use cases</span>'
                    '<h2>What to use %s for</h2><p>The jobs where we recommend it, and the part it plays in each setup.</p>'
                    '</div></div><div class="alts">%s</div></section>' % (e(a["name"]), "".join(rows)))
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
            '<div class="links">%s</div></section>' % "".join(row_link(a, D) for a in tools)]
    ucs = [u for u in D["usecases"] if w["id"] in u["workflows"]]
    if ucs:
        body.append('<section class="block"><div class="sechead"><div><span class="eyebrow">Use cases</span>'
                    '<h2>Jobs this workflow gets done</h2></div></div><div class="ucgrid">%s</div></section>'
                    % "".join(uc_card(D, u) for u in ucs))
    body.append(cta_band())
    return page_shell(D, m, "\n".join(body))


def uc_faq(D, u):
    """(question, html, text) for a use case page. Built only from the data, so no claim is made up here."""
    items = []
    steps = [(D["by_id"][s["tool"]], s.get("does", "")) for s in u["setup"]]
    h = "<p>%s</p><ol>%s</ol>" % (e(u.get("answer", "")), "".join(
        '<li><a href="/agents/%s/">%s</a>: %s</li>' % (e(a["id"]), e(a["name"]), e(d)) for a, d in steps))
    t = "%s %s" % (u.get("answer", ""), " ".join("%d. %s: %s" % (i + 1, a["name"], d) for i, (a, d) in enumerate(steps)))
    items.append((uc_question(u), h, t))

    lead = "Each tool's price, from its own website:"
    items.append(("What does this setup cost?",
                  "<p>%s</p><ul>%s</ul>" % (e(lead), "".join("<li>%s: %s</li>" % (e(a["name"]), e(a.get("pricing") or "See site"))
                                                             for a, _ in steps)),
                  "%s %s" % (lead, " ".join("%s: %s." % (a["name"], (a.get("pricing") or "See site").rstrip(".")) for a, _ in steps))))
    if u["alternatives"]:
        alts = [(D["by_id"][s["tool"]], s.get("when", "")) for s in u["alternatives"]]
        items.append(("What can I use instead?",
                      "<ul>%s</ul>" % "".join('<li><a href="/agents/%s/">%s</a>, when: %s</li>' % (e(a["id"]), e(a["name"]), e(w))
                                              for a, w in alts),
                      " ".join("%s, when: %s" % (a["name"], w) for a, w in alts)))
    if u.get("for"):
        t = "%s." % str(u["for"]).rstrip(".")
        items.append(("Who is this setup for?", "<p>%s</p>" % e(t), t))
    if u.get("watchOut"):
        items.append(("What should I watch out for?", "<p>%s</p>" % e(u["watchOut"]), u["watchOut"]))
    return items


def build_uc_page(D, u):
    q = uc_question(u)
    title = uc_title(D, u)
    tools = uc_tools(D, u)
    desc = clip(u.get("answer", ""), 300)
    url = uc_page(u)
    modified = u.get("updated") or u.get("added") or D["updated"]
    m = common_meta(title, desc, url, og_type="article", modified=modified)
    faq = uc_faq(D, u)
    howto = {"@type": "HowTo", "@id": url + "#howto", "name": "How to %s with AI agents" % lower_first(u["job"]),
             "description": desc, "tool": [{"@type": "HowToTool", "name": a["name"]} for a in tools],
             "step": [{"@type": "HowToStep", "position": i + 1, "name": D["by_id"][s["tool"]]["name"],
                       "text": s.get("does", ""), "url": agent_page(D["by_id"][s["tool"]])}
                      for i, s in enumerate(u["setup"])]}
    graph = {"@context": "https://schema.org", "@graph": [
        {"@type": "WebPage", "@id": url, "url": url, "name": title, "headline": q, "description": desc, "inLanguage": "en",
         "isPartOf": {"@id": SITE + "/#website"}, "datePublished": u.get("added") or D["updated"], "dateModified": modified,
         "audience": {"@type": "Audience", "audienceType": u.get("for") or "Product designers and product managers"},
         "mentions": [software_ld(a) for a in tools + [D["by_id"][s["tool"]] for s in u["alternatives"]]],
         "mainEntity": {"@id": url + "#faq"}},
        howto,
        {"@type": "FAQPage", "@id": url + "#faq",
         "mainEntity": [{"@type": "Question", "name": fq, "acceptedAnswer": {"@type": "Answer", "text": ft}} for fq, _, ft in faq]},
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": NAME, "item": SITE + "/"},
            {"@type": "ListItem", "position": 2, "name": "Use cases", "item": UC_HUB},
            {"@type": "ListItem", "position": 3, "name": u["job"], "item": url}]}]}
    m.append('<script type="application/ld+json">%s</script>' % ld(graph))

    steps = "".join(
        '<li><div class="ucstep">%s<p>%s</p><span class="checked">%s</span></div></li>'
        % (row_link(D["by_id"][s["tool"]], D), e(s.get("does", "")), e(D["by_id"][s["tool"]].get("pricing") or "See site"))
        for s in u["setup"])
    watch = ('<p class="watch"><span class="eyebrow">Watch out</span>%s</p>' % e(u["watchOut"])) if u.get("watchOut") else ""
    body = ['<div class="crumbs"><a href="/">Home</a><span>/</span><a href="/use-cases/">Use cases</a><span>/</span><span>%s</span></div>'
            % e(u["job"]),
            '<header class="subhero"><span class="eyebrow">%s · %d-step setup</span><h1>%s</h1><p class="lede">%s</p>%s</header>'
            % (e(STAGES[u["stage"]]), len(u["setup"]), e(q), e(u.get("answer", "")),
               ('<p class="meta">Best for: %s</p>' % e(str(u["for"]).rstrip("."))) if u.get("for") else ""),
            '<div class="stage"><div class="stage-inner"><article class="win page-win"><div class="bar"><span class="lights" aria-hidden="true">'
            '<i></i><i></i><i></i></span><span class="t">agentictools.design · The setup</span></div><div class="wfmain">'
            '<h2>The setup, in order</h2><div class="ask">%s</div><ol class="ucsteps">%s</ol>%s</div></article></div></div>'
            % (e(uc_chain(D, u)), steps, watch)]
    if u["alternatives"]:
        body.append('<section class="block"><div class="sechead"><div><span class="eyebrow">Alternatives</span>'
                    '<h2>Swap a tool in when it fits you better</h2></div></div><div class="alts">%s</div></section>'
                    % "".join('<div class="alt">%s<p>%s</p></div>' % (row_link(D["by_id"][s["tool"]], D), e(s.get("when", "")))
                              for s in u["alternatives"]))
    wfs = [w for w in D["workflows"] if w["id"] in u["workflows"]]
    if wfs:
        body.append('<section class="block"><div class="sechead"><div><span class="eyebrow">Workflows</span>'
                    '<h2>Step-by-step workflows for this job</h2></div></div><div class="faq">%s</div></section>'
                    % "".join('<details><summary><h3>%s</h3>%s</summary><div class="a"><ol>%s</ol><p>Result: %s. '
                              '<a href="/workflows/%s/">Open this workflow</a></p></div></details>'
                              % (e(w["title"]), CHEV, "".join("<li>%s</li>" % e(s) for s in w.get("steps") or []),
                                 e((w.get("outcome") or "").rstrip(".")), e(w["id"])) for w in wfs))
    body.append('<section class="block" aria-labelledby="ucFaq"><div class="sechead"><div><span class="eyebrow">Questions</span>'
                '<h2 id="ucFaq">%s, answered</h2></div></div><div class="faq">%s</div></section>'
                % (e(u["job"]), "".join('<details><summary><h3>%s</h3>%s</summary><div class="a">%s</div></details>'
                                        % (e(fq), CHEV, fh) for fq, fh, _ in faq)))
    related = [x for x in D["usecases"] if x["stage"] == u["stage"] and x["id"] != u["id"]]
    related += [x for x in D["usecases"] if x["stage"] != u["stage"]]
    if related:
        body.append('<section class="block"><div class="sechead"><div><span class="eyebrow">Keep going</span>'
                    '<h2>More setups for designers and PMs</h2></div><a class="link" href="/use-cases/">All use cases →</a></div>'
                    '<div class="ucgrid">%s</div></section>' % "".join(uc_card(D, x, 110) for x in related[:6]))
    body.append(cta_band())
    return page_shell(D, m, "\n".join(body))


def build_uc_hub(D):
    year = (parse_date(D["updated"]) or dt.date.today()).year
    title = "Which AI agents to use for what: %d setups for designers and PMs (%d) | %s" % (len(D["usecases"]), year, NAME)
    desc = clip("Pick the job and get the AI setup that does it. %d use cases for product designers and product managers, "
                "each with the agents to use, in what order, and why." % len(D["usecases"]), 300)
    m = common_meta(title, desc, UC_HUB, modified=D["updated"])
    graph = {"@context": "https://schema.org", "@graph": [
        {"@type": "CollectionPage", "@id": UC_HUB, "url": UC_HUB, "name": title, "description": desc, "inLanguage": "en",
         "isPartOf": {"@id": SITE + "/#website"}, "dateModified": D["updated"], "mainEntity": {"@id": UC_HUB + "#list"}},
        uc_itemlist(D, UC_HUB + "#list"),
        {"@type": "FAQPage", "@id": UC_HUB + "#faq",
         "mainEntity": [{"@type": "Question", "name": uc_question(u),
                         "acceptedAnswer": {"@type": "Answer", "text": u.get("answer", ""), "url": uc_page(u)}}
                        for u in D["usecases"]]},
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": NAME, "item": SITE + "/"},
            {"@type": "ListItem", "position": 2, "name": "Use cases", "item": UC_HUB}]}]}
    m.append('<script type="application/ld+json">%s</script>' % ld(graph))
    body = ['<div class="crumbs"><a href="/">Home</a><span>/</span><span>Use cases</span></div>',
            '<header class="subhero"><span class="eyebrow">%d use cases · updated %s</span><h1>Which AI agents to use for what</h1>'
            '<p>Most AI lists tell you what exists. This one tells you what to use for the job in front of you: '
            'the agents, the order, and why. Every tool is checked on its own site.</p></header>'
            % (len(D["usecases"]), e(fmt_date(D["updated"])))]
    for k, label in STAGES.items():
        items = [u for u in D["usecases"] if u["stage"] == k]
        if not items:
            continue
        body.append('<section class="block" style="padding-top:40px"><div class="sechead"><div><span class="eyebrow">Stage</span>'
                    '<h2>%s</h2></div></div><div class="hublist">%s</div></section>'
                    % (e(label), "".join('<article class="hubq"><h3><a href="/use-cases/%s/">%s</a></h3><p>%s</p>'
                                         '<span class="uctools">%s</span></article>'
                                         % (e(u["id"]), e(uc_question(u)), e(u.get("answer", "")), e(uc_chain(D, u)))
                                         for u in items)))
    body.append(cta_band())
    return page_shell(D, m, "\n".join(body))


def build_404(D):
    m = ["<title>Page not found | %s</title>" % NAME, '<meta name="robots" content="noindex">']
    body = ('<header class="subhero"><h1>That page isn\'t here.</h1><p>The page may have a new address. '
            'Start from the job you want done, or browse every agent.</p><div class="cta"><a class="pill dark big" href="/use-cases/">'
            'Find your setup</a><a class="pill big" href="/#all">Browse the directory</a></div></header>')
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
    if D["usecases"]:
        urls.append((UC_HUB, D["updated"], "weekly", "0.9"))
        urls += [(uc_page(u), u.get("updated") or u.get("added") or D["updated"], "weekly", "0.9") for u in D["usecases"]]
    urls += [(agent_page(a), a.get("verified") or a.get("added") or D["updated"], "weekly", "0.8") for a in D["agents"]]
    urls += [(wf_page(w), w.get("added") or D["updated"], "monthly", "0.6") for w in D["workflows"]]
    body = "".join("  <url><loc>%s</loc>%s<changefreq>%s</changefreq><priority>%s</priority></url>\n"
                   % (e(u), ("<lastmod>%s</lastmod>" % e(d)) if parse_date(d) else "", f, p) for u, d, f, p in urls)
    return '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n%s</urlset>\n' % body


def md(s):
    return re.sub(r"[\r\n]+", " ", str(s or "")).replace("[", "(").replace("]", ")")


def llms(D, full=False):
    n_agents, n_cats, n_wf = counts(D)
    n_uc = len(D["usecases"])
    out = ["# agentictools.design", "",
           "> A free guide to which AI agents product designers and product managers should use for which job. "
           "%sIt also keeps a daily-updated directory where each listing says what the tool does in 30 seconds, who it is for, "
           "what it is best at and what it costs, checked against the product's own website. "
           "%d agents, %d categories, %d workflows. Last updated %s."
           % (("%d use cases, each with the recommended setup: which agents to use, in what order, and why. " % n_uc) if n_uc else "",
              n_agents, n_cats, n_wf, D["updated"]), "",
           "Machine-readable data: %s/agents.json (agents: name, maker, category, url, oneLiner, forWho, standout, pricing, tags, "
           "verified, added; usecases: job, stage, for, answer, setup, alternatives, workflows, watchOut)." % SITE,
           ""]
    if D["usecases"]:
        out += ["## Use cases: which AI agents to use for what", "", "Index: %s" % UC_HUB, ""]
        for u in D["usecases"]:
            if full:
                out.append("### %s" % md(uc_question(u)))
                out.append("- Page: %s" % uc_page(u))
                out.append("- Stage: %s" % STAGES[u["stage"]])
                if u.get("for"):
                    out.append("- For: %s" % md(u["for"]))
                out.append("- Short answer: %s" % md(u.get("answer")))
                out.append("- Setup, in order:")
                for i, s in enumerate(u["setup"]):
                    a = D["by_id"][s["tool"]]
                    out.append("  %d. %s (%s): %s Pricing: %s" % (i + 1, md(a["name"]), agent_page(a), md(s.get("does")),
                                                                md(a.get("pricing") or "See site")))
                for s in u["alternatives"]:
                    a = D["by_id"][s["tool"]]
                    out.append("- Alternative: %s (%s), when: %s" % (md(a["name"]), agent_page(a), md(s.get("when"))))
                if u.get("watchOut"):
                    out.append("- Watch out: %s" % md(u["watchOut"]))
                out.append("")
            else:
                out.append("- [%s](%s): %s Setup: %s." % (md(u["job"]), uc_page(u), md(u.get("answer")), md(uc_chain(D, u))))
        out.append("")
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
        "uccount": e("%d use cases" % len(D["usecases"])),
        "usecases": blk_usecases(D),
        "footfresh": e("Refreshed daily, last on %s. Every listing is checked against the product's own site." % fmt_date(D["updated"])),
    }
    for k, v in blocks.items():
        src = replace_block(src, k, v)
    write("index.html", src)

    style = re.search(r"<style>(.*?)</style>", src, re.S)
    if not style:
        sys.exit("build: no <style> in index.html")
    css = style.group(1).strip() + "\n" + SUB_CSS
    write("assets/site.css", css)
    global CSS_VER
    CSS_VER = hashlib.sha256(css.encode()).hexdigest()[:8]

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

    # use case pages and their hub
    base = os.path.join(ROOT, "use-cases")
    keep = {u["id"] for u in D["usecases"]}
    if os.path.isdir(base):
        for name in os.listdir(base):
            if name not in keep and os.path.isdir(os.path.join(base, name)):
                shutil.rmtree(os.path.join(base, name))
    for u in D["usecases"]:
        write("use-cases/%s/index.html" % u["id"], build_uc_page(D, u))
    if D["usecases"]:
        write("use-cases/index.html", build_uc_hub(D))

    write("404.html", build_404(D))
    write("sitemap.xml", sitemap(D))
    write("robots.txt", robots())
    write("llms.txt", llms(D))
    write("llms-full.txt", llms(D, full=True))
    print("build: %d agents, %d workflows, %d use cases, updated %s"
          % (len(D["agents"]), len(D["workflows"]), len(D["usecases"]), D["updated"]))


if __name__ == "__main__":
    main()
