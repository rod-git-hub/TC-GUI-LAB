"""help_docs.py — the in-app Help: the same Markdown files GitHub shows.

They ship with every install, so Help always matches the version running and
works on a lab network with no internet access. Pages come from a fixed list —
the browser only ever names a page, never a file path. Raw HTML in the Markdown
is not passed through, links between the documents become in-app links, other
repository files link to GitHub at this version, and images are served only
from docs/img/.
"""
import os, posixpath, re, threading
from urllib.parse import urlsplit
from xml.etree import ElementTree as etree

import markdown
from markdown.extensions import Extension
from markdown.extensions.toc import TocExtension
from markdown.treeprocessors import Treeprocessor

ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT_URL = "https://github.com/rod-git-hub/TC-GUI-LAB"

PAGES = [   # id, title, file relative to the install
    ("overview",  "Overview",            "README.md"),
    ("guide",     "Using TC Lab",        "docs/user-guide.md"),
    ("install",   "Install & configure", "docs/deployment.md"),
    ("upgrade",   "Upgrading",           "docs/upgrading.md"),
    ("users",     "Users & security",    "docs/users-and-security.md"),
    ("security",  "Security policy",     "SECURITY.md"),
    ("whatsnew",  "What's new",          "RELEASE_NOTES.md"),
    ("changelog", "Changelog",           "CHANGELOG.md"),
]
_TITLE = {pid: title for pid, title, _ in PAGES}
_FILE = {pid: path for pid, _, path in PAGES}
_PAGE_OF = {path: pid for pid, _, path in PAGES}
_PAGE_OF["docs/README.md"] = "overview"          # the docs index: Help has its own

IMG_DIR = os.path.join(ROOT, "docs", "img")
IMG_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]*\.(png|jpe?g|gif|webp)$")   # never SVG
ANCHOR_PREFIX = "h-"      # heading ids must not collide with the dashboard's own


def _github_slug(value, separator="-"):
    """Heading anchors the way GitHub makes them — lower case, punctuation
    dropped, every space a hyphen (not collapsed) — so a link written for
    GitHub, like deployment.md#4-configuration, lands on the same heading."""
    return re.sub(r"[^\w\- ]", "", value.lower()).replace(" ", separator)


def _drop(parent, el):
    """Remove `el`, keeping the text that followed it."""
    tail = el.tail or ""
    kids = list(parent)
    i = kids.index(el)
    if i:
        kids[i - 1].tail = (kids[i - 1].tail or "") + tail
    else:
        parent.text = (parent.text or "") + tail
    parent.remove(el)


def _outside(a):
    a.set("target", "_blank")
    a.set("rel", "noopener noreferrer")


class _HelpLinks(Treeprocessor):
    def __init__(self, md, src, page, version):
        super().__init__(md)
        self.src, self.page, self.version = src, page, version

    def run(self, root):
        for el in root.iter():
            if el.get("id"):
                el.set("id", ANCHOR_PREFIX + el.get("id"))
        for parent in list(root.iter()):
            for el in list(parent):
                if el.tag == "a":
                    self._link(el)
                elif el.tag == "img":
                    self._image(parent, el)

    def _resolve(self, path):
        return posixpath.normpath(posixpath.join(posixpath.dirname(self.src), path))

    def _link(self, a):
        u = urlsplit(a.get("href", ""))
        if u.scheme in ("http", "https", "mailto"):
            _outside(a)
            return
        if u.scheme or u.netloc:                       # javascript:, data:, //host
            a.attrib.pop("href", None)
            return
        if not u.path:                                 # #heading on this page
            page, anchor = self.page, u.fragment
        else:
            target = self._resolve(u.path)
            if target.startswith(".."):
                a.attrib.pop("href", None)
                return
            page, anchor = _PAGE_OF.get(target), u.fragment
            if page is None:                           # LICENSE, CONTRIBUTING.md, ...
                a.set("href", f"{PROJECT_URL}/blob/v{self.version}/{target}")
                _outside(a)
                return
        a.set("href", "#")
        a.set("data-help", page)
        if anchor:
            a.set("data-anchor", anchor)

    def _image(self, parent, img):
        u = urlsplit(img.get("src", ""))
        if u.scheme or u.netloc:
            # Hosted elsewhere: the dashboard only loads its own images, and a
            # lab network may have no internet. Badges are decoration; anything
            # else becomes a link to open it online.
            if u.netloc == "img.shields.io":
                _drop(parent, img)
                return
            a = etree.Element("a", {"href": img.get("src")})
            _outside(a)
            a.text = f"{img.get('alt') or 'Image'} (opens online)"
            a.tail = img.tail
            parent.insert(list(parent).index(img), a)
            parent.remove(img)
            return
        target = self._resolve(u.path)
        name = posixpath.basename(target)
        if posixpath.dirname(target) == "docs/img" and IMG_NAME.match(name):
            img.set("src", f"/help/img/{name}")
            img.set("loading", "lazy")
        else:
            _drop(parent, img)


class _HelpExtension(Extension):
    def __init__(self, src, page, version):
        super().__init__()
        self.src, self.page, self.version = src, page, version

    def extendMarkdown(self, md):
        # Raw HTML is shown as text, never passed through.
        md.preprocessors.deregister("html_block")
        md.inlinePatterns.deregister("html")
        # After "toc" (priority 5), so heading ids exist to be prefixed.
        md.treeprocessors.register(_HelpLinks(md, self.src, self.page, self.version),
                                   "tc_lab_help_links", 1)


_cache, _lock = {}, threading.Lock()


def render(page, version):
    """(title, html) for a Help page. KeyError for an unknown page; OSError if
    its file is missing from the install."""
    title, rel = _TITLE[page], _FILE[page]
    path = os.path.join(ROOT, rel)
    key = (os.path.getmtime(path), version)
    with _lock:
        hit = _cache.get(page)
    if hit and hit[0] == key:
        return title, hit[1]
    md = markdown.Markdown(extensions=[
        "tables", "fenced_code",
        TocExtension(slugify=_github_slug),
        _HelpExtension(rel, page, version)])
    with open(path, encoding="utf-8") as f:
        html = md.convert(f.read())
    with _lock:
        _cache[page] = (key, html)
    return title, html
