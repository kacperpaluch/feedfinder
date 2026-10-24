#!/usr/bin/env python3
"""Znajduje adres RSS dla podanego URL-a. Tylko biblioteka standardowa."""
import html
import ipaddress
import json
import os
import re
import socket
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
MAX_BYTES = 3_000_000
FEED_TYPES = ("application/rss+xml", "application/atom+xml", "application/feed+json")
COMMON_PATHS = ("/feed", "/rss", "/rss.xml", "/feed.xml", "/atom.xml", "/index.xml")
TITLE_NOTE = "Dopasowano tylko po tytule w katalogu Apple Podcasts – sprawdź, czy to właściwy podcast."
SIMILAR_NOTE = "Brak dokładnego dopasowania. Podobne podcasty z katalogu Apple Podcasts:"


class Fail(Exception):
    pass


# --- pobieranie -------------------------------------------------------------

def check_public(url):
    """Blokuje adresy prywatne, żeby nie dało się odpytywać sieci wewnętrznej serwera."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise Fail("Nieprawidłowy adres URL.")
    try:
        infos = socket.getaddrinfo(parts.hostname, None)
    except OSError:
        raise Fail("Nie znaleziono takiego hosta.")
    for info in infos:
        if not ipaddress.ip_address(info[4][0].split("%")[0]).is_global:
            raise Fail("Ten adres jest niedozwolony.")


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_public(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


opener = urllib.request.build_opener(SafeRedirect)


def fetch(url, timeout=10):
    """Zwraca (końcowy URL, content-type, treść)."""
    url = urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%~")
    check_public(url)
    headers = {"User-Agent": UA, "Accept-Language": "en"}
    if "youtu" in urllib.parse.urlsplit(url).hostname:
        headers["Cookie"] = "SOCS=CAI"  # pomija ekran zgody na cookies
    req = urllib.request.Request(url, headers=headers)
    with opener.open(req, timeout=timeout) as resp:
        body = resp.read(MAX_BYTES).decode("utf-8", "replace")
        return resp.geturl(), resp.headers.get("Content-Type", "").lower(), body


def fetch_json(url):
    return json.loads(fetch(url)[2])


# --- pomocnicze -------------------------------------------------------------

class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.feeds, self.title, self._in_title = [], "", False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "link" and a.get("href") and "alternate" in (a.get("rel") or "").lower() \
                and (a.get("type") or "").strip().lower() in FEED_TYPES:
            self.feeds.append(a["href"])
        elif tag == "title" and not self.title:
            self._in_title = True

    def handle_data(self, data):
        if self._in_title:
            self.title += data

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False


def looks_like_feed(ctype, text):
    head = text[:1000].lower()
    return "<rss" in head or "<feed" in head or "<rdf:rdf" in head or \
        ("json" in ctype and "jsonfeed.org" in head)


def og_title(text):
    m = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]*)"', text)
    return html.unescape(m.group(1)) if m else ""


def squash(text):
    return " ".join(html.unescape(text).split()).casefold()


def match_podcast(title, episode=""):
    """Spotify i Deezer nie udostępniają RSS – szukamy tego samego podcastu w katalogu Apple.

    Jeśli znamy tytuł najnowszego odcinka, potwierdzamy trafienie jego obecnością w feedzie.
    """
    query = urllib.parse.urlencode({"media": "podcast", "entity": "podcast", "limit": 10, "term": title})
    results = [r for r in fetch_json("https://itunes.apple.com/search?" + query).get("results", [])
               if r.get("feedUrl")]
    if not results:
        raise Fail("Nie znaleziono podcastu „%s” w katalogu Apple Podcasts." % title)
    exact = [r for r in results if squash(r.get("collectionName", "")) == squash(title)]
    if episode:
        for r in (exact or results)[:3]:
            try:
                if squash(episode) in squash(fetch(r["feedUrl"])[2]):
                    return {"title": r["collectionName"], "feeds": [{"url": r["feedUrl"]}]}
            except Exception:
                continue
    feeds = [{"url": r["feedUrl"], "label": "%s – %s" % (r.get("collectionName", ""), r.get("artistName", ""))}
             for r in (exact or results)[:5]]
    return {"title": title, "feeds": feeds, "note": TITLE_NOTE if exact else SIMILAR_NOTE}


# --- źródła -----------------------------------------------------------------

def apple(url):
    m = re.search(r"/id(\d+)", url)
    if not m:
        return website(url)
    results = fetch_json("https://itunes.apple.com/lookup?entity=podcast&id=" + m.group(1)).get("results", [])
    if not results or not results[0].get("feedUrl"):
        raise Fail("Apple Podcasts nie podaje RSS dla tego podcastu.")
    return {"title": results[0].get("collectionName", ""), "feeds": [{"url": results[0]["feedUrl"]}]}


def spotify(url):
    m = re.search(r"/show/(\w+)", url)
    if not m:
        raise Fail("Wklej link do podcastu (open.spotify.com/show/…).")
    # strona osadzania pokazuje najnowszy odcinek; nazwa podcastu jest w polu "subtitle"
    text = fetch("https://open.spotify.com/embed/show/" + m.group(1))[2]
    show = re.search(r'"subtitle":("(?:[^"\\]|\\.)*")', text)
    episode = re.search(r'"title":("(?:[^"\\]|\\.)*")', text)
    if not show:
        raise Fail("Nie udało się odczytać nazwy podcastu ze Spotify.")
    return match_podcast(json.loads(show.group(1)), json.loads(episode.group(1)) if episode else "")


def deezer(url):
    m = re.search(r"/show/(\d+)", url)
    if not m:
        raise Fail("Wklej link do podcastu (deezer.com/show/…).")
    title = og_title(fetch("https://www.deezer.com/show/" + m.group(1))[2])
    if not title:
        raise Fail("Nie udało się odczytać nazwy podcastu z Deezera.")
    return match_podcast(title)


def youtube(url):
    base = "https://www.youtube.com/feeds/videos.xml?"
    parts = urllib.parse.urlsplit(url)
    playlist = urllib.parse.parse_qs(parts.query).get("list")
    if parts.path.startswith("/playlist") and playlist:
        return {"title": "", "feeds": [{"url": base + "playlist_id=" + playlist[0]}]}
    m = re.match(r"/channel/(UC[\w-]{22})", parts.path)
    if m:
        return {"title": "", "feeds": [{"url": base + "channel_id=" + m.group(1)}]}
    text = fetch(url)[2]
    m = re.search(r'feeds/videos\.xml\?channel_id=(UC[\w-]{22})', text) or \
        re.search(r'"(?:channelId|externalId)":"(UC[\w-]{22})"', text)
    if not m:
        raise Fail("Nie udało się ustalić kanału YouTube.")
    return {"title": og_title(text), "feeds": [{"url": base + "channel_id=" + m.group(1)}]}


def soundcloud(url):
    text = fetch(url)[2]
    m = re.search(r"soundcloud://users:(\d+)", text)
    if not m:
        raise Fail("Nie udało się ustalić profilu SoundCloud.")
    return {"title": og_title(text),
            "feeds": [{"url": "https://feeds.soundcloud.com/users/soundcloud:users:%s/sounds.rss" % m.group(1)}]}


def reddit(url):
    parts = urllib.parse.urlsplit(url)
    return {"title": "", "feeds": [{"url": "https://www.reddit.com%s/.rss" % parts.path.rstrip("/")}]}


def github(url):
    path = [p for p in urllib.parse.urlsplit(url).path.split("/") if p]
    if not path:
        raise Fail("Wklej link do repozytorium lub użytkownika GitHub.")
    if len(path) == 1:
        return {"title": path[0], "feeds": [{"url": "https://github.com/%s.atom" % path[0], "label": "Aktywność"}]}
    repo = "https://github.com/%s/%s" % (path[0], path[1])
    return {"title": "%s/%s" % (path[0], path[1]),
            "feeds": [{"url": repo + "/releases.atom", "label": "Wydania"},
                      {"url": repo + "/tags.atom", "label": "Tagi"},
                      {"url": repo + "/commits.atom", "label": "Commity"}]}


def google_news(url):
    parts = urllib.parse.urlsplit(url)
    path = parts.path if parts.path.startswith("/rss") else "/rss" + parts.path
    return {"title": "", "feeds": [{"url": urllib.parse.urlunsplit(("https", "news.google.com", path, parts.query, ""))}]}


def website(url):
    final, ctype, text = fetch(url)
    if looks_like_feed(ctype, text):
        return {"title": "", "feeds": [{"url": final}]}
    parser = LinkParser()
    parser.feed(text)
    feeds = list(dict.fromkeys(urllib.parse.urljoin(final, f) for f in parser.feeds))
    if not feeds:  # brak deklaracji w <head> – próbujemy typowych ścieżek
        for path in COMMON_PATHS:
            candidate = urllib.parse.urljoin(final, path)
            try:
                found, ctype, body = fetch(candidate, timeout=5)
            except Exception:
                continue
            if looks_like_feed(ctype, body):
                feeds = [found]
                break
    if not feeds:
        raise Fail("Na tej stronie nie znaleziono kanału RSS.")
    return {"title": " ".join(parser.title.split()), "feeds": [{"url": f} for f in feeds]}


SOURCES = (("podcasts.apple.com", apple), ("itunes.apple.com", apple), ("open.spotify.com", spotify),
           ("youtube.com", youtube), ("youtu.be", youtube), ("soundcloud.com", soundcloud),
           ("deezer.com", deezer), ("reddit.com", reddit), ("github.com", github),
           ("news.google.com", google_news))


def find_feed(url):
    url = url.strip()
    if not url or " " in url:
        raise Fail("Podaj adres URL.")
    if not re.match(r"https?://", url, re.I):
        url = "https://" + url
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    for domain, source in SOURCES:
        if host == domain or host.endswith("." + domain):
            return source(url)
    return website(url)


def lookup(url):
    try:
        return dict(find_feed(url), ok=True)
    except Fail as e:
        return {"ok": False, "error": str(e)}
    except Exception:
        return {"ok": False, "error": "Nie udało się pobrać tej strony."}


# --- HTTP -------------------------------------------------------------------

PAGE = """<!doctype html>
<html lang="pl"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>feedfinder</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><rect width='16' height='16' rx='4' fill='rgb(194,65,12)'/><circle cx='5' cy='11' r='1.4' fill='white'/><path d='M4 7.2a4.8 4.8 0 0 1 4.8 4.8M4 4a8 8 0 0 1 8 8' fill='none' stroke='white' stroke-width='1.6' stroke-linecap='round'/></svg>">
<style>
:root{--bg:oklch(.99 .003 75);--fg:oklch(.23 .01 60);--muted:oklch(.48 .012 60);--line:oklch(.89 .006 70);
--field:oklch(1 0 0);--accent:oklch(.55 .17 42);--on-accent:oklch(1 0 0);--err:oklch(.5 .19 27);--warn:oklch(.5 .11 70)}
@media (prefers-color-scheme:dark){:root{--bg:oklch(.18 .006 60);--fg:oklch(.93 .006 75);--muted:oklch(.7 .01 70);
--line:oklch(.32 .008 60);--field:oklch(.22 .006 60);--accent:oklch(.74 .15 52);--on-accent:oklch(.2 .02 50);
--err:oklch(.75 .14 25);--warn:oklch(.8 .11 80)}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;
-webkit-font-smoothing:antialiased;caret-color:var(--accent)}
::selection{background:color-mix(in oklch,var(--accent) 28%%,transparent)}
main{max-width:40rem;margin:0 auto;padding:12vh 1rem 4rem}
h1{display:flex;align-items:center;gap:.5rem;margin:0 0 2rem;font-size:1.125rem;font-weight:650;letter-spacing:-.01em}
h1 svg{color:var(--accent)}
label{display:block;margin-bottom:.75rem;font-size:1.25rem;font-weight:550;letter-spacing:-.015em;line-height:1.35;text-wrap:balance}
.field{position:relative;display:flex;gap:.375rem;padding:.3125rem;background:var(--field);border:1px solid var(--line);
border-radius:.75rem;transition:border-color .15s,box-shadow .15s;overflow:hidden}
.field:focus-within{border-color:var(--accent);box-shadow:0 0 0 3px color-mix(in oklch,var(--accent) 22%%,transparent)}
input{flex:1;min-width:0;padding:0 .5rem;border:0;background:none;color:inherit;font:inherit;outline:none}
.field input:focus-visible{outline:none}
input::placeholder{color:var(--muted)}
button,.open{font:inherit;font-size:.9375rem;font-weight:550;border-radius:.5rem;cursor:pointer;white-space:nowrap}
.field button{padding:.5rem 1.125rem;border:0;background:var(--accent);color:var(--on-accent)}
.field button:hover{filter:brightness(1.08)}
button:disabled{cursor:progress;opacity:.75}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.hint{margin:.75rem 0 0;color:var(--muted);font-size:.875rem}
.bar{position:absolute;left:0;right:0;bottom:0;height:2px;background:var(--accent);transform:scaleX(0);transform-origin:left}
.busy .bar{animation:load 8s cubic-bezier(.16,1,.3,1) forwards}
.busy #out{opacity:.4;transition:opacity .2s}
@keyframes load{to{transform:scaleX(.92)}}
@media (prefers-reduced-motion:reduce){.busy .bar{animation:none;transform:scaleX(1);opacity:.5}}
#out{margin-top:3rem}
h2{margin:0 0 .25rem;font-size:1rem;font-weight:650;overflow-wrap:anywhere}
.note{margin:.25rem 0 0;color:var(--warn);font-size:.875rem}
.err{margin:0;color:var(--err)}
ul{list-style:none;margin:1rem 0 0;padding:0}
li{display:flex;flex-wrap:wrap;align-items:center;gap:.5rem 1rem;padding:.875rem 0;border-top:1px solid var(--line)}
li:last-child{border-bottom:1px solid var(--line)}
.feed{flex:1 1 16rem;min-width:0}
.feed small{display:block;color:var(--muted);font-size:.8125rem;font-weight:550}
code{font:.875rem/1.45 ui-monospace,"SF Mono",Menlo,monospace;overflow-wrap:anywhere}
.act{display:flex;gap:.25rem}
.copy{display:inline-grid;padding:.375rem .75rem;border:1px solid var(--line);background:var(--field);color:inherit}
.copy:hover{border-color:var(--muted)}
.copy span{grid-area:1/1}
.copy span+span,.copy.done span:first-child{visibility:hidden}
.copy.done span+span{visibility:visible;color:var(--accent)}
.open{padding:.375rem .75rem;color:var(--muted);text-decoration:none}
.open:hover{color:var(--fg);text-decoration:underline;text-underline-offset:3px}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%%)}
</style>
<main>
<h1><svg width="20" height="20" viewBox="0 0 16 16" aria-hidden="true"><circle cx="3" cy="13" r="1.6" fill="currentColor"/><path d="M2 7.5A6.5 6.5 0 0 1 8.5 14M2 2.5A11.5 11.5 0 0 1 13.5 14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>feedfinder</h1>
<form action="/" role="search">
<label for="url">Wklej adres strony, podcastu albo kanału – znajdę jego RSS.</label>
<div class="field"><input id="url" name="url" type="text" inputmode="url" autocomplete="off" autocapitalize="off"
spellcheck="false" value="%s" placeholder="https://…" required%s><button>Szukaj</button><span class="bar"></span></div>
<p class="hint">Strony&nbsp;WWW, Apple&nbsp;Podcasts, Spotify, Deezer, YouTube, SoundCloud, Reddit, GitHub, Google&nbsp;News</p>
</form>
<section id="out">%s</section>
<p id="status" class="sr" aria-live="polite"></p>
</main>
<script>
const f = document.querySelector("form"), i = f.url, b = f.querySelector("button"), status = document.getElementById("status");
f.addEventListener("submit", () => {
  document.body.classList.add("busy");
  b.disabled = true;
  b.textContent = status.textContent = "Szukam…";
});
// po cofnięciu w historii przeglądarka przywraca stronę razem ze stanem "szukam"
addEventListener("pageshow", () => { document.body.classList.remove("busy"); b.disabled = false; b.textContent = "Szukaj"; });
// wklejenie całego adresu od razu uruchamia wyszukiwanie
i.addEventListener("paste", () => {
  const whole = i.selectionStart === 0 && i.selectionEnd === i.value.length;
  setTimeout(() => { if (whole && /\\S\\.\\S/.test(i.value)) f.requestSubmit(); });
});
function copy(text) {
  if (navigator.clipboard && isSecureContext) return navigator.clipboard.writeText(text);
  // zwykłe http (np. adres w sieci lokalnej) nie ma dostępu do navigator.clipboard
  const t = document.createElement("textarea");
  t.value = text;
  document.body.append(t);
  t.select();
  const ok = document.execCommand("copy");
  t.remove();
  return ok ? Promise.resolve() : Promise.reject();
}
document.addEventListener("click", e => {
  const c = e.target.closest(".copy");
  if (!c) return;
  copy(c.dataset.url).then(() => {
    c.classList.add("done");
    status.textContent = "Skopiowano do schowka";
    setTimeout(() => c.classList.remove("done"), 1600);
  }, () => getSelection().selectAllChildren(c.closest("li").querySelector("code")));
});
</script>
</html>"""


def render(url, result):
    out = ""
    if result and not result["ok"]:
        out = '<p class="err" role="alert">%s</p>' % html.escape(result["error"])
    elif result:
        feeds = result["feeds"]
        title = result.get("title") or ("Znaleziony kanał" if len(feeds) == 1 else "Znalezione kanały")
        out += "<h2>%s</h2>" % html.escape(title)
        if result.get("note"):
            out += '<p class="note">%s</p>' % html.escape(result["note"])
        out += "<ul>"
        for feed in feeds:
            href = html.escape(feed["url"], quote=True)
            label = "<small>%s</small>" % html.escape(feed["label"]) if feed.get("label") else ""
            out += ('<li><div class="feed">%s<code>%s</code></div><div class="act">'
                    '<button type="button" class="copy" data-url="%s"><span>Kopiuj</span><span>Skopiowano</span></button>'
                    '<a class="open" href="%s" target="_blank" rel="noopener noreferrer">Otwórz</a></div></li>'
                    % (label, href.replace("/", "/<wbr>"), href, href))
        out += "</ul>"
    return PAGE % (html.escape(url, quote=True), "" if result else " autofocus", out)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parts = urllib.parse.urlsplit(self.path)
        url = urllib.parse.parse_qs(parts.query).get("url", [""])[0][:2000]
        if parts.path == "/":
            self.reply(200, "text/html", render(url, lookup(url) if url else None))
        elif parts.path == "/api":
            self.reply(200, "application/json", json.dumps(lookup(url), ensure_ascii=False))
        else:
            self.reply(404, "text/plain", "Not found")

    def reply(self, status, ctype, body):
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", 8000))), Handler).serve_forever()
