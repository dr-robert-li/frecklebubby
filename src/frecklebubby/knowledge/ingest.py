"""Text extraction and chunking: Markdown with front matter, HTML, PDF, EPUB, plain text."""

import io
import re
import zipfile
from html.parser import HTMLParser

import yaml

CHUNK = 1000  # characters, spec section 10
Sections = list[tuple[str, str]]  # (heading, text)


def front_matter(text: str) -> tuple[dict, str]:
    """Split '---\\nyaml\\n---\\nbody'. No front matter gives ({}, text)."""
    m = re.match(r"---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        return {}, text
    return yaml.safe_load(m.group(1)) or {}, text[m.end():]


def md_sections(body: str) -> Sections:
    """One section per '#'/'##'/'###' heading."""
    out: Sections = []
    heading, lines = "", []
    for line in body.splitlines():
        m = re.match(r"#{1,3}\s+(.*)", line)
        if m:
            out.append((heading, "\n".join(lines)))
            heading, lines = m.group(1).strip(), []
        else:
            lines.append(line)
    out.append((heading, "\n".join(lines)))
    return [(h, t.strip()) for h, t in out if t.strip()]


class _Html(HTMLParser):
    SKIP = {"script", "style", "nav", "header", "footer", "noscript", "svg", "form", "aside", "template"}
    BLOCK = {"p", "div", "li", "br", "tr", "section", "article", "ul", "ol", "table", "dd", "dt"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sections: Sections = []
        self.heading, self.buf, self.skip, self.in_h, self.h_buf = "", [], 0, False, []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in ("h1", "h2", "h3"):
            self._flush()
            self.in_h, self.h_buf = True, []
        elif tag in self.BLOCK:
            self.buf.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in ("h1", "h2", "h3") and self.in_h:
            self.in_h = False
            self.heading = " ".join("".join(self.h_buf).split())
        elif tag in self.BLOCK:
            self.buf.append("\n")

    def handle_data(self, data):
        if self.skip:
            return
        (self.h_buf if self.in_h else self.buf).append(data)

    def _flush(self):
        text = "\n".join(" ".join(line.split()) for line in "".join(self.buf).splitlines())
        text = re.sub(r"\n{2,}", "\n", text).strip()
        if text:
            self.sections.append((self.heading, text))
        self.buf = []


def html_sections(html: str) -> Sections:
    p = _Html()
    p.feed(html)
    p.close()
    p._flush()
    return p.sections


def pdf_sections(data: bytes) -> tuple[Sections, str | None]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    title = (reader.metadata.title if reader.metadata else None) or None
    return [(f"Page {i}", (page.extract_text() or "").strip()) for i, page in enumerate(reader.pages, 1)], title


def epub_sections(data: bytes) -> Sections:
    # shortcut: chapters in file-name order, not the OPF spine order; read the spine if order matters for display.
    out: Sections = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in sorted(z.namelist()):
            if name.lower().endswith((".xhtml", ".html", ".htm")):
                out += html_sections(z.read(name).decode("utf-8", "replace"))
    return out


def chunks(sections: Sections, size: int = CHUNK) -> Sections:
    """Split each section into pieces of about `size` characters at line or sentence ends."""
    out: Sections = []
    for heading, text in sections:
        piece = ""
        for part in re.split(r"(?<=\n)|(?<=[.!?] )", text):
            if piece and len(piece) + len(part) > size:
                out.append((heading, piece.strip()))
                piece = ""
            piece += part
            while len(piece) > 2 * size:  # one long line with no sentence end
                out.append((heading, piece[:size].strip()))
                piece = piece[size:]
        if piece.strip():
            out.append((heading, piece.strip()))
    return out
