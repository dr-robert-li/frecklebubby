import io
import os
import zipfile

import httpx
import pytest

from frecklebubby.knowledge import store, web_lookup
from frecklebubby.models import Family, KbSource

from .conftest import ctx_for, make_family

UPLOADS = "/api/v1/knowledge/uploads"


def make_pdf(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            "/Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def make_epub(html: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("OEBPS/ch1.xhtml", html)
    return buf.getvalue()


def family(s) -> Family:
    return s.query(Family).first()


@pytest.mark.parametrize("question,url", [
    ("how many wet nappies is normal", "https://www.nhs.uk/baby/"),
    ("baby has a fever 38.5", "https://www.nhs.uk/symptoms/fever-in-children/"),
    ("when can I start solids", "https://www.nhs.uk/baby/weaning-and-feeding/babys-first-solid-foods/"),
    ("safe sleep position", "https://www.cdc.gov/sudden-infant-death/sleep-safely/"),
    ("how much formula should my baby drink", "https://www.nhs.uk/baby/breastfeeding-and-bottle-feeding/bottle-feeding/"),
    ("how long should a 4 month old sleep", "https://aasm.org/"),
])
async def test_search_relevance(client, question, url):
    await make_family(client)
    s, ctx = ctx_for("a@example.com")
    hits = store.search(s, ctx.fam, question)
    assert len(hits) == 6
    assert any(h["url"].startswith(url) for h in hits[:3]), [h["url"] for h in hits[:3]]
    if "nappies" in question:
        assert any("6 wet nappies a day" in h["text"] for h in hits)
    s.close()


@pytest.mark.parametrize("question", ['" OR 1=1 --', "NEAR(a b)", "fever*", "^nappy", "a:b {c} (d", "AND OR NOT", "", "?"])
async def test_query_injection_is_safe(client, question):
    await make_family(client)
    s, ctx = ctx_for("a@example.com")
    store.search(s, ctx.fam, question)  # no FTS syntax error
    assert store.fts_query('ab" OR cd*') == '"ab" OR "cd"'
    s.close()


async def test_ingest_is_idempotent_and_reloads_on_change(client):
    await make_family(client)
    s, _ = ctx_for("a@example.com")
    store.ensure_bundled(s)
    count = s.query(KbSource).count()
    store._done.clear()
    store.ensure_bundled(s)
    assert s.query(KbSource).count() == count
    chunks = s.execute(store.text("SELECT count(*) FROM kb_chunk")).scalar()
    # A changed bundle (different hash in the marker) loads again, without duplicates.
    marker = store.get_settings().data_dir / "kb_bundle.sha256"
    marker.write_text("old")
    store._done.clear()
    store.ensure_bundled(s)
    assert s.query(KbSource).count() == count
    assert s.execute(store.text("SELECT count(*) FROM kb_chunk")).scalar() == chunks
    assert s.query(KbSource).filter_by(kind="link").count() > 40
    s.close()


async def test_uploads_private_and_deletable(client):
    ha, _ = await make_family(client)
    hb, _ = await make_family(client, email="b@example.com")
    files = {
        "notes.txt": b"Our grandmother says zebrafinch songs help the baby settle.",
        "guide.md": b"---\ntitle: Settling guide\nauthor: Dr Who\n---\n# Night\nUse a quokkalullaby at night.\n",
        "book.pdf": make_pdf("The wombatlantern method helps babies sleep."),
        "book.epub": make_epub("<html><body><nav>skip me</nav><h1>Chapter 1</h1><p>The platypusdream routine.</p>"
                               "<script>evil()</script></body></html>"),
    }
    ids = {}
    for name, data in files.items():
        r = await client.post(UPLOADS, headers=ha, files={"file": (name, data)})
        assert r.status_code == 201, r.text
        ids[name] = r.json()["id"]
        assert r.json()["chunks"] >= 1 and r.json()["own"] and r.json()["kind"] == "upload"
    assert r.json()["title"] == "book"

    sa, ca = ctx_for("a@example.com")
    sb, cb = ctx_for("b@example.com")
    for word in ("zebrafinch", "quokkalullaby", "wombatlantern", "platypusdream"):
        assert [h["kind"] for h in store.search(sa, ca.fam, word)] == ["upload"], word
        assert store.search(sb, cb.fam, word) == [], word  # family B never sees family A's uploads
    assert store.search(sa, ca.fam, "skip evil") == [] or all(
        "evil" not in h["text"] for h in store.search(sa, ca.fam, "evil"))
    md = store.search(sa, ca.fam, "quokkalullaby")[0]
    assert md["title"] == "Settling guide" and md["author"] == "Dr Who" and "Night" in md["heading"]

    listed_a = (await client.get("/api/v1/knowledge/sources", headers=ha)).json()
    listed_b = (await client.get("/api/v1/knowledge/sources", headers=hb)).json()
    assert sum(x["own"] for x in listed_a) == 4 and not any(x["own"] for x in listed_b)
    assert ids["notes.txt"] not in {x["id"] for x in listed_b}
    assert any(x["kind"] == "bundled" for x in listed_b) and any(x["kind"] == "link" for x in listed_b)

    assert (await client.delete(f"/api/v1/knowledge/sources/{ids['notes.txt']}", headers=hb)).status_code == 404
    bundled = next(x["id"] for x in listed_a if x["kind"] == "bundled")
    assert (await client.delete(f"/api/v1/knowledge/sources/{bundled}", headers=ha)).status_code == 404
    assert (await client.delete(f"/api/v1/knowledge/sources/{ids['notes.txt']}", headers=ha)).status_code == 204
    sa.expire_all()
    assert store.search(sa, ca.fam, "zebrafinch") == []
    sa.close()
    sb.close()


async def test_upload_limits(client, monkeypatch):
    h, _ = await make_family(client)
    r = await client.post(UPLOADS, headers=h, files={"file": ("x.exe", b"MZ")})
    assert r.status_code == 422 and "PDF, EPUB, TXT or MD" in r.json()["detail"]
    r = await client.post(UPLOADS, headers=h, files={"file": ("x.pdf", b"not a pdf")})
    assert r.status_code == 422 and "could not be read" in r.json()["detail"]
    monkeypatch.setattr("frecklebubby.knowledge.uploads.MAX_BYTES", 10)
    r = await client.post(UPLOADS, headers=h, files={"file": ("x.txt", b"a" * 11)})
    assert r.status_code == 422 and "50 MB" in r.json()["detail"]


# --- web lookup ---------------------------------------------------------------------------------------------------

PAGE = ("<html><head><style>x{}</style><script>bad()</script></head><body><nav>Menu</nav><h1>Teething</h1>"
        "<p>Some babies get a capybaratooth rash.</p><footer>Cookies</footer></body></html>")


def transport(routes: dict, calls: list):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        status, headers, body = routes.get(str(request.url), (404, {}, b""))
        return httpx.Response(status, headers={"content-type": "text/html", **headers}, content=body)

    return httpx.MockTransport(handler)


async def test_check_url():
    web_lookup.check_url("https://www.nhs.uk/conditions/colic/")
    for bad in ("http://www.nhs.uk/x", "https://evil.example/x", "https://www.nhs.uk.evil.example/x",
                "https://user@www.nhs.uk/x", "https://www.nhs.uk:8443/x", "file:///etc/passwd", "ftp://www.nhs.uk/"):
        with pytest.raises(web_lookup.Refused):
            web_lookup.check_url(bad)


async def test_fetch_rules():
    calls = []
    url = "https://www.nhs.uk/a"
    t = transport({url: (200, {}, PAGE.encode()),
                   "https://www.nhs.uk/moved": (301, {"location": "/a"}, b""),
                   "https://www.nhs.uk/away": (302, {"location": "https://evil.example/x"}, b""),
                   "https://www.nhs.uk/big": (200, {}, b"x" * (web_lookup.MAX_BYTES + 1)),
                   "https://www.nhs.uk/pdf": (200, {"content-type": "application/pdf"}, b"%PDF")}, calls)
    text = await web_lookup.fetch(url, t)
    assert "capybaratooth" in text
    assert "capybaratooth" in await web_lookup.fetch("https://www.nhs.uk/moved", t)  # same host: allowed
    for bad, why in (("https://www.nhs.uk/away", "another host"), ("https://www.nhs.uk/big", "too large"),
                     ("https://www.nhs.uk/pdf", "not a web page"), ("http://www.nhs.uk/a", "only https")):
        with pytest.raises(web_lookup.Refused, match=why):
            await web_lookup.fetch(bad, t)
    assert "https://evil.example/x" not in calls


def test_html_strip():
    from frecklebubby.knowledge.ingest import html_sections

    assert html_sections(PAGE) == [("Teething", "Some babies get a capybaratooth rash.")]


async def test_lookup_caches_and_is_used_when_on(client, monkeypatch):
    h, _ = await make_family(client)
    item = {"title": "Teething page", "publisher": "NHS", "url": "https://www.nhs.uk/teething/", "kind": "web",
            "topics": ["teething"], "summary": "About teething."}
    monkeypatch.setattr(web_lookup, "link_list", lambda: [item])
    calls = []
    t = transport({item["url"]: (200, {}, PAGE.encode())}, calls)
    s, ctx = ctx_for("a@example.com")
    assert web_lookup.candidates("my baby is teething") == [item]
    assert web_lookup.candidates("car seat") == []
    assert await web_lookup.lookup(s, "baby teething rash", t) == 1
    assert await web_lookup.lookup(s, "baby teething rash", t) == 0  # cached for 7 days
    assert len(calls) == 1
    assert store.search(s, ctx.fam, "capybaratooth") == []  # web_lookup is off for this family
    hits = store.search(s, ctx.fam, "capybaratooth", web=True)
    assert hits[0]["kind"] == "web" and hits[0]["url"] == item["url"]
    s.close()


@pytest.mark.network
@pytest.mark.skipif(not os.environ.get("NETWORK_TESTS"), reason="real network: set NETWORK_TESTS=1")
async def test_real_nhs_page():
    text = await web_lookup.fetch("https://www.nhs.uk/conditions/colic/")
    assert "colic" in text.lower()
