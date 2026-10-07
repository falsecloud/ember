"""Tools the agent can use on YOUR machine: files, shell, web, GitHub."""
import base64
import fnmatch
import html as _html
import os
import re
import subprocess
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import httpx

STATE = {"token": ""}
UA = {"User-Agent": "Mozilla/5.0 (ember-agent)"}
SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".idea", ".mypy_cache"}


def P(path) -> Path:
    return Path(os.path.expanduser(str(path or "."))).resolve()


def clip(s, n=8000):
    return s if len(s) <= n else s[: n // 2] + f"\n…[{len(s) - n} chars cut]…\n" + s[-n // 2:]


# ---------------------------------------------------------------- files
def list_dir(path="."):
    p = P(path)
    if not p.is_dir():
        return f"error: not a directory: {p}"
    items = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
    out = []
    for x in items[:300]:
        try:
            out.append(x.name + "/" if x.is_dir() else f"{x.name}  ({x.stat().st_size}b)")
        except OSError:
            out.append(x.name + "  (unreadable)")
    return f"{p}\n" + "\n".join(out) + (f"\n…{len(items) - 300} more" if len(items) > 300 else "")


def read_file(path, start=1, end=0):
    p = P(path)
    if not p.is_file():
        return f"error: not a file: {p}"
    data = p.read_bytes()
    if b"\0" in data[:2048]:
        return f"error: binary file ({len(data)} bytes)"
    lines = data.decode("utf-8", "replace").splitlines()
    s = max(int(start), 1)
    e = int(end) or len(lines)
    body = "\n".join(f"{i:>4}| {l}" for i, l in enumerate(lines[s - 1:e], start=s))
    return clip(f"{p} ({len(lines)} lines)\n{body}", 12000)


def write_file(path, content):
    p = P(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    return f"wrote {p} ({len(content.splitlines())} lines)"


def edit_file(path, old, new, replace_all=False):
    p = P(path)
    if not p.is_file():
        return f"error: not a file: {p}"
    text = p.read_text("utf-8", "replace")
    n = text.count(old)
    if n == 0:
        return "error: `old` text not found (must match exactly, including whitespace). Re-read the file."
    if n > 1 and not replace_all:
        return f"error: `old` matches {n} places; include more context or set replace_all=true"
    p.write_text(text.replace(old, new) if replace_all else text.replace(old, new, 1), "utf-8")
    return f"edited {p} ({n if replace_all else 1} replacement)"


def search_files(pattern, path=".", glob="*"):
    root = P(path)
    try:
        rx = re.compile(pattern)
    except re.error:
        rx = re.compile(re.escape(pattern))
    hits = []
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP]
        for fn in files:
            if not fnmatch.fnmatch(fn, glob):
                continue
            fp = Path(d) / fn
            try:
                if fp.stat().st_size > 1_000_000:
                    continue
                txt = fp.read_bytes()
                if b"\0" in txt[:1024]:
                    continue
                for i, line in enumerate(txt.decode("utf-8", "replace").splitlines(), 1):
                    if rx.search(line):
                        hits.append(f"{fp}:{i}: {line.strip()[:200]}")
                        if len(hits) >= 100:
                            return "\n".join(hits) + "\n…(100 match limit)"
            except OSError:
                pass
    return "\n".join(hits) or "no matches"


def run_shell(command, timeout=60):
    try:
        r = subprocess.run(command, shell=True, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=int(timeout), stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return f"error: timed out after {timeout}s"
    out = f"exit {r.returncode}\n{r.stdout}"
    if r.stderr:
        out += "\n[stderr]\n" + r.stderr
    return clip(out)


# ---------------------------------------------------------------- web
class _Text(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "pre"}

    def __init__(self):
        super().__init__()
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg"):
            self.skip += 1
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg"):
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_to_text(src):
    t = _Text()
    t.feed(src)
    text = "".join(t.out)
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()


def fetch_url(url, raw=False):
    r = httpx.get(url, headers=UA, follow_redirects=True, timeout=30)
    text = r.text
    if "html" in r.headers.get("content-type", "") and not raw:
        text = html_to_text(text)
    return clip(f"[{r.status_code}] {url}\n{text}", 12000)


def web_search(query, n=8):
    r = httpx.post("https://html.duckduckgo.com/html/", data={"q": query}, headers=UA,
                   timeout=20, follow_redirects=True)
    links = re.findall(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', r.text, re.S)
    snips = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', r.text, re.S)
    strip = lambda s: _html.unescape(re.sub(r"<.*?>", "", s)).strip()
    out = []
    for i, (href, title) in enumerate(links[: int(n)]):
        q = parse_qs(urlparse(href).query)
        if "uddg" in q:
            href = unquote(q["uddg"][0])
        out.append(f"{i + 1}. {strip(title)}\n   {href}\n   {strip(snips[i]) if i < len(snips) else ''}")
    return "\n".join(out) or "no results (search engine may have rate-limited; try fetch_url on a known page)"


def _stream_to(url, dest, headers=None):
    p = P(dest)
    p.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    with httpx.stream("GET", url, headers=headers or UA, follow_redirects=True, timeout=120) as r:
        r.raise_for_status()
        with open(p, "wb") as f:
            for c in r.iter_bytes(1 << 16):
                f.write(c)
                size += len(c)
    return p, size


def download_file(url, path):
    p, size = _stream_to(url, path)
    return f"saved {p} ({size} bytes)"


# ---------------------------------------------------------------- github
def _repo(r):
    r = r.strip().rstrip("/")
    if r.endswith(".git"):
        r = r[:-4]
    m = re.search(r"github\.com[/:]([^/]+/[^/]+)", r)
    return m.group(1) if m else r


def _gh(accept="application/vnd.github+json"):
    h = {"Accept": accept, "User-Agent": "ember-agent", "X-GitHub-Api-Version": "2022-11-28"}
    if STATE["token"]:
        h["Authorization"] = f"Bearer {STATE['token']}"
    return h


def _auth_args():
    if not STATE["token"]:
        return []
    b = base64.b64encode(f"x-access-token:{STATE['token']}".encode()).decode()
    return ["-c", f"http.extraheader=AUTHORIZATION: basic {b}"]


def _git(args, cwd=None, auth=False):
    cmd = ["git"] + (_auth_args() if auth else []) + args
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", stdin=subprocess.DEVNULL, timeout=600,
                           env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    except FileNotFoundError:
        return 127, "git is not installed (Arch: sudo pacman -S git | Windows: winget install Git.Git)"
    return r.returncode, (r.stdout + r.stderr).strip()


def github_list(repo, path="", ref=""):
    rp = _repo(repo)
    r = httpx.get(f"https://api.github.com/repos/{rp}/contents/{path.strip('/')}", headers=_gh(),
                  params={"ref": ref} if ref else None, timeout=30)
    if r.status_code != 200:
        return f"error {r.status_code}: {r.text[:300]}"
    j = r.json()
    if isinstance(j, dict):
        return f"{j['path']} is a file ({j['size']} bytes)"
    return "\n".join(f"{x['type']:<4} {x['path']}" + (f"  ({x['size']}b)" if x["type"] == "file" else "") for x in j)


def github_get_file(repo, path, dest="", ref=""):
    rp = _repo(repo)
    r = httpx.get(f"https://api.github.com/repos/{rp}/contents/{path.strip('/')}",
                  headers=_gh("application/vnd.github.raw+json"), params={"ref": ref} if ref else None,
                  follow_redirects=True, timeout=120)
    if r.status_code != 200:
        return f"error {r.status_code}: {r.text[:300]}"
    if r.text.lstrip().startswith("[") and "json" in r.headers.get("content-type", ""):
        return "that path is a directory; use github_list or github_clone"
    if dest:
        p = P(dest)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(r.content)
        return f"saved {p} ({len(r.content)} bytes)"
    return clip(r.text, 12000)


def github_clone(repo, dest="", branch=""):
    rp = _repo(repo)
    args = ["clone", "--depth", "1"] + (["-b", branch] if branch else [])
    args += [f"https://github.com/{rp}.git", dest or rp.split("/")[1]]
    code, out = _git(args, auth=True)
    return f"exit {code}\n{out}"


def github_release(repo, tag="latest", download=False, dest=".", match="*"):
    rp = _repo(repo)
    url = f"https://api.github.com/repos/{rp}/releases/" + ("latest" if tag == "latest" else f"tags/{tag}")
    r = httpx.get(url, headers=_gh(), timeout=30)
    if r.status_code != 200:
        return f"error {r.status_code}: {r.text[:300]}"
    j = r.json()
    assets = [a for a in j.get("assets", []) if fnmatch.fnmatch(a["name"], match)]
    lines = [f"release {j['tag_name']}"] + [f"- {a['name']} ({a['size']} bytes)" for a in assets]
    if download:
        for a in assets:
            p, size = _stream_to(a["browser_download_url"], Path(P(dest)) / a["name"], _gh("application/octet-stream"))
            lines.append(f"saved {p}")
    return "\n".join(lines)


def github_publish(path=".", repo="", private=True, message="Update from ember", description=""):
    if not STATE["token"]:
        return "error: no GitHub token. Ask the user to run `ember login` (token needs `repo` scope)."
    if not repo:
        repo = P(path).name
    me = httpx.get("https://api.github.com/user", headers=_gh(), timeout=30)
    if me.status_code != 200:
        return f"error: token rejected ({me.status_code})"
    login = me.json()["login"]
    owner, name = (repo.split("/", 1) if "/" in repo else (login, repo))
    name = name.removesuffix(".git") if hasattr(name, "removesuffix") else name
    if httpx.get(f"https://api.github.com/repos/{owner}/{name}", headers=_gh(), timeout=30).status_code == 404:
        api = "https://api.github.com/user/repos" if owner == login else f"https://api.github.com/orgs/{owner}/repos"
        c = httpx.post(api, headers=_gh(), timeout=30,
                       json={"name": name, "private": bool(private), "description": description})
        if c.status_code not in (200, 201):
            return f"error creating repo: {c.status_code} {c.text[:300]}"
    cwd = str(P(path))
    if not (Path(cwd) / ".git").exists():
        _git(["init"], cwd)
        _git(["checkout", "-B", "main"], cwd)
    gi = Path(cwd) / ".gitignore"
    if not gi.exists():
        gi.write_text("node_modules/\n__pycache__/\n.venv/\nvenv/\n.env\n*.log\ndist/\nbuild/\n", "utf-8")
    _git(["add", "-A"], cwd)
    ident = []
    if not _git(["config", "user.name"], cwd)[1]:
        ident = ["-c", "user.name=ember", "-c", "user.email=ember@localhost"]
    _git(ident + ["commit", "-m", message], cwd)
    url = f"https://github.com/{owner}/{name}.git"
    if _git(["remote", "get-url", "origin"], cwd)[0] == 0:
        _git(["remote", "set-url", "origin", url], cwd)
    else:
        _git(["remote", "add", "origin", url], cwd)
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)[1] or "main"
    code, out = _git(["push", "-u", "origin", branch], cwd, auth=True)
    if code != 0:
        return f"push failed:\n{out}"
    return f"pushed to https://github.com/{owner}/{name} (branch {branch})"


TOOLS = {f.__name__: f for f in (
    list_dir, read_file, write_file, edit_file, search_files, run_shell, fetch_url, web_search,
    download_file, github_list, github_get_file, github_clone, github_release, github_publish)}

DOCS = """list_dir(path=".")
read_file(path, start=1, end=0)   # end=0 means to the end
write_file(path, content)         # creates parent folders; overwrites
edit_file(path, old, new, replace_all=false)   # exact-text replacement
search_files(pattern, path=".", glob="*")      # regex search in files
run_shell(command, timeout=60)    # run any command on the user's PC
fetch_url(url)                    # read a web page as text
web_search(query)
download_file(url, path)
github_list(repo, path="", ref="")             # repo = "owner/name" or URL
github_get_file(repo, path, dest="", ref="")   # read a file, or save it to dest (assets, images, ...)
github_clone(repo, dest="", branch="")
github_release(repo, tag="latest", download=false, dest=".", match="*")  # release assets
github_publish(path=".", repo="name or owner/name", private=true, message="...", description="")  # create repo + commit + push"""

MUTATING = {"write_file", "edit_file", "run_shell", "download_file", "github_clone", "github_publish"}


def needs_confirm(name, args):
    return (name in MUTATING or (name == "github_get_file" and bool(args.get("dest")))
            or (name == "github_release" and bool(args.get("download"))))


def call(name, args):
    fn = TOOLS.get(name)
    if not fn:
        return f"error: unknown tool `{name}`. Available: {', '.join(TOOLS)}"
    try:
        return fn(**args)
    except TypeError as e:
        return f"error: bad arguments for {name}: {e}"
    except Exception as e:  # noqa
        return f"error: {type(e).__name__}: {e}"
