"""
doi_network.py
--------------
Given a DOI, retrieves:
  (1) Papers cited by this paper (references)
  (2) Papers that cite this paper (citations)
from Semantic Scholar API, then writes a formatted PDF report.

Run with:  python doi_network.py
"""

import importlib.util
import os
import re
import sys
import time
import unicodedata

# ---------------------------------------------------------------------------
# Dependency check — runs before anything else
# ---------------------------------------------------------------------------
_REQUIRED = {"requests": "requests", "fpdf": "fpdf"}
_missing = [pkg for mod, pkg in _REQUIRED.items() if importlib.util.find_spec(mod) is None]
if _missing:
    print("The following required packages are not installed:")
    for pkg in _missing:
        print(f"  {pkg}")
    print(f"\nPlease run:  pip install {' '.join(_missing)}")
    input("\nPress Enter to close...")
    sys.exit(1)

import requests
from fpdf import FPDF

# ---------------------------------------------------------------------------
# *** PASTE YOUR SEMANTIC SCHOLAR API KEY HERE (or leave blank) ***
# Get a free key at: https://www.semanticscholar.org/product/api
# ---------------------------------------------------------------------------
SEMANTIC_SCHOLAR_API_KEY = ""  # paste your key here, or leave blank to enter it interactively

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_URL = "https://api.semanticscholar.org/graph/v1/paper"
PAPER_FIELDS = "title,authors,year,citationCount,abstract,tldr,venue,journal,externalIds,url"
REF_FIELDS   = "title,authors,year,citationCount,abstract,venue,journal,externalIds,url"
PAGE_SIZE    = 500   # max allowed by S2 API per request
RATE_SLEEP   = 1.5   # seconds between API calls (free tier: ~100 req/5 min)

# ---------------------------------------------------------------------------
# Text cleaning (latin-1 safe, mirrors create_lit_pdfs.py)
# ---------------------------------------------------------------------------
REPLACEMENTS = {
    "\u2014": "--",   # em-dash
    "\u2013": "-",    # en-dash
    "\u2018": "'",    # left single quote
    "\u2019": "'",    # right single quote
    "\u201c": '"',    # left double quote
    "\u201d": '"',    # right double quote
    "\u2026": "...",  # ellipsis
    "\u00e1": "a", "\u00e9": "e", "\u00ed": "i", "\u00f3": "o", "\u00fa": "u",
    "\u00c1": "A", "\u00c9": "E", "\u00cd": "I", "\u00d3": "O", "\u00da": "U",
    "\u00e0": "a", "\u00e8": "e", "\u00ec": "i", "\u00f2": "o", "\u00f9": "u",
    "\u00e2": "a", "\u00ea": "e", "\u00ee": "i", "\u00f4": "o", "\u00fb": "u",
    "\u00e4": "a", "\u00eb": "e", "\u00ef": "i", "\u00f6": "o", "\u00fc": "u",
    "\u00e6": "ae", "\u00f8": "o", "\u00e5": "a", "\u00df": "ss",
    "\u0144": "n", "\u0143": "N", "\u0142": "l", "\u0141": "L",
    "\u010d": "c", "\u0161": "s", "\u017e": "z",
}

def clean(text: str) -> str:
    if not text:
        return ""
    for src, dst in REPLACEMENTS.items():
        text = text.replace(src, dst)
    # Decompose remaining accented chars, drop combining marks
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    # Drop anything still outside latin-1
    return text.encode("latin-1", errors="replace").decode("latin-1")


# ---------------------------------------------------------------------------
# Semantic Scholar API
# ---------------------------------------------------------------------------
def make_headers(api_key: str | None) -> dict:
    if api_key:
        return {"x-api-key": api_key}
    return {}


def api_get(url: str, params: dict, headers: dict, retries: int = 3) -> dict:
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=30)
            if r.status_code == 404:
                return {"_not_found": True}
            if r.status_code == 429:
                wait = 10 * (attempt + 1)
                print(f"  Rate limited. Waiting {wait}s ...", flush=True)
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            if attempt == retries - 1:
                print(f"  Error: {e}", flush=True)
                return {}
            print(f"  Request error ({e}), retrying ...", flush=True)
            time.sleep(3)
    return {}


def fetch_paper(doi: str, headers: dict) -> dict:
    """Fetch metadata for the focal paper."""
    url = f"{BASE_URL}/DOI:{doi}"
    data = api_get(url, {"fields": PAPER_FIELDS}, headers)
    time.sleep(RATE_SLEEP)
    return data


def fetch_all_pages(endpoint: str, headers: dict, max_results: int) -> tuple[list[dict], bool]:
    """Paginate through references or citations endpoint.
    Returns (raw_results, suppressed) where suppressed=True means publisher blocked it."""
    results = []
    offset = 0
    suppressed = False
    while len(results) < max_results:
        limit = min(PAGE_SIZE, max_results - len(results))
        data = api_get(endpoint, {"fields": REF_FIELDS, "limit": limit, "offset": offset}, headers)
        if data.get("data") is None and "citingPaperInfo" in data:
            suppressed = True
            break
        batch = data.get("data") or []
        if not batch:
            break
        results.extend(batch)
        offset += len(batch)
        if len(batch) < limit:
            break
        time.sleep(RATE_SLEEP)
    return results, suppressed


def parse_paper(raw: dict) -> dict:
    """Normalise a paper dict (handles both top-level and nested citedPaper/citingPaper)."""
    p = raw.get("citedPaper") or raw.get("citingPaper") or raw
    authors = ", ".join(a.get("name", "") for a in p.get("authors", []))
    journal = (
        (p.get("journal") or {}).get("name")
        or p.get("venue")
        or ""
    )
    doi_id = (p.get("externalIds") or {}).get("DOI", "")
    url = p.get("url") or (f"https://doi.org/{doi_id}" if doi_id else "")
    abstract = p.get("abstract") or ""
    tldr = (p.get("tldr") or {}).get("text", "") if isinstance(p.get("tldr"), dict) else ""
    if abstract and tldr:
        summary = f"{abstract}\n\n[Auto-summary]: {tldr}"
    elif abstract:
        summary = abstract
    elif tldr:
        summary = f"[Auto-summary]: {tldr}"
    else:
        summary = "No abstract available."
    return {
        "title":      p.get("title") or "Untitled",
        "authors":    authors or "Unknown",
        "journal":    journal,
        "year":       str(p.get("year") or "n.d."),
        "citations":  p.get("citationCount") or 0,
        "abstract":   summary,
        "url":        url,
        "doi":        doi_id,
    }


# ---------------------------------------------------------------------------
# CrossRef fallback for publisher-suppressed abstracts
# ---------------------------------------------------------------------------
CROSSREF_HEADERS = {"User-Agent": "doi_network/1.0 (mailto:research@scholar.com)"}

def strip_jats(text: str) -> str:
    """Remove JATS XML tags and any leading section labels (e.g. 'Abstract') from CrossRef abstracts."""
    text = re.sub(r"<[^>]+>", "", text)          # strip all tags
    text = re.sub(r"^\s*Abstract\s*", "", text, flags=re.IGNORECASE)  # drop leading "Abstract" label
    return text.strip()

def fetch_crossref_abstract(doi: str) -> str:
    """Try CrossRef API for abstract. Returns empty string on failure."""
    try:
        r = requests.get(
            f"https://api.crossref.org/works/{doi}",
            headers=CROSSREF_HEADERS,
            timeout=10,
        )
        if r.status_code == 200:
            raw = r.json().get("message", {}).get("abstract", "")
            return strip_jats(raw) if raw else ""
    except Exception:
        pass
    return ""


def fetch_openalex_abstract(doi: str) -> str:
    """Try OpenAlex API for abstract (stored as inverted index). Returns empty string on failure."""
    try:
        r = requests.get(
            f"https://api.openalex.org/works/doi:{doi}",
            headers=CROSSREF_HEADERS,
            timeout=10,
        )
        if r.status_code == 200:
            inv = r.json().get("abstract_inverted_index") or {}
            if not inv:
                return ""
            # Reconstruct abstract from inverted index: {word: [positions]}
            word_pos = [(pos, word) for word, positions in inv.items() for pos in positions]
            word_pos.sort()
            return " ".join(w for _, w in word_pos)
    except Exception:
        pass
    return ""


def enrich_abstracts(papers: list[dict]) -> None:
    """Fill in missing abstracts from CrossRef then OpenAlex. Modifies list in-place."""
    missing = [p for p in papers if p["abstract"] == "No abstract available." and p["doi"]]
    if not missing:
        return
    print(f"  Fetching {len(missing)} missing abstract(s) from CrossRef / OpenAlex ...", flush=True)
    for p in missing:
        abstract = fetch_crossref_abstract(p["doi"])
        time.sleep(0.3)
        if not abstract:
            abstract = fetch_openalex_abstract(p["doi"])
            time.sleep(0.3)
        if abstract:
            p["abstract"] = abstract


def fetch_crossref_references(doi: str) -> list[str]:
    """Fetch reference DOIs from CrossRef. Returns list of DOI strings."""
    try:
        r = requests.get(
            f"https://api.crossref.org/works/{doi}",
            headers=CROSSREF_HEADERS,
            timeout=10,
        )
        if r.status_code == 200:
            refs = r.json().get("message", {}).get("reference", [])
            return [ref["DOI"] for ref in refs if ref.get("DOI")]
    except Exception:
        pass
    return []


def batch_lookup_s2(dois: list[str], headers: dict) -> list[dict]:
    """Batch-lookup up to 500 DOIs in S2. Returns list of parsed papers."""
    results = []
    BATCH = 500
    fields = "title,authors,year,citationCount,abstract,venue,journal,externalIds,url"
    for i in range(0, len(dois), BATCH):
        chunk = [f"DOI:{d}" for d in dois[i:i + BATCH]]
        try:
            r = requests.post(
                "https://api.semanticscholar.org/graph/v1/paper/batch",
                params={"fields": fields},
                headers=headers,
                json={"ids": chunk},
                timeout=30,
            )
            if r.status_code == 200:
                for p in r.json():
                    if p:  # S2 returns null for DOIs it doesn't recognise
                        results.append(parse_paper(p))
        except Exception as e:
            print(f"  Batch lookup error: {e}", flush=True)
        time.sleep(RATE_SLEEP)
    return results


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
class NetworkPDF(FPDF):
    def __init__(self, focal_title: str, doi: str):
        super().__init__()
        self._focal_title = focal_title
        self._doi = doi

    def header(self):
        self.set_font("Helvetica", "B", 12)
        self.cell(0, 9, clean("Citation Network Report"), align="C", ln=True)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(80, 80, 80)
        self.multi_cell(0, 5, clean(f"Focal paper: {self._focal_title}"), align="C")
        self.set_text_color(0, 0, 0)
        self.ln(2)
        self.set_draw_color(80, 80, 80)
        self.set_line_width(0.5)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")
        self.set_text_color(0, 0, 0)

    def section_title(self, text: str):
        self.set_font("Helvetica", "B", 13)
        self.set_fill_color(30, 80, 160)
        self.set_text_color(255, 255, 255)
        self.cell(0, 10, clean(f"  {text}"), fill=True, ln=True)
        self.set_text_color(0, 0, 0)
        self.ln(4)

    def focal_paper_box(self, paper: dict, doi: str):
        self.set_fill_color(240, 245, 255)
        self.set_draw_color(30, 80, 160)
        self.set_line_width(0.5)
        x, y = self.get_x(), self.get_y()
        # Draw filled rect (approximate height, we'll just use multi_cell flow)
        self.set_font("Helvetica", "B", 11)
        self.set_fill_color(240, 245, 255)
        self.multi_cell(0, 7, clean(paper["title"]), fill=True)
        self.set_font("Helvetica", "I", 9)
        self.set_text_color(50, 50, 50)
        self.multi_cell(0, 5, clean(f"Authors: {paper['authors']}"), fill=True)
        self.set_font("Helvetica", "", 9)
        self.set_text_color(30, 80, 160)
        jy = f"{paper['journal']}  ({paper['year']})" if paper["journal"] else paper["year"]
        self.cell(0, 5, clean(jy), ln=True, fill=True)
        self.set_text_color(0, 0, 0)
        self.cell(0, 5, clean(f"DOI: {doi}"), ln=True, fill=True)
        self.cell(0, 5, clean(f"Cited by: {paper['citations']:,} papers"), ln=True, fill=True)
        self.ln(3)
        self.set_font("Helvetica", "B", 9)
        self.cell(0, 5, "Abstract:", ln=True, fill=True)
        self.set_font("Helvetica", "", 9)
        self.multi_cell(0, 5, clean(paper["abstract"]), fill=True)
        self.ln(6)

    def add_paper(self, number: int, paper: dict, section_color: tuple):
        r, g, b = section_color
        # Number badge + title background
        self.set_fill_color(r, g, b)
        self.set_text_color(255, 255, 255)
        self.set_font("Helvetica", "B", 10)
        self.cell(0, 7, clean(f"  [{number}]  {paper['title']}"), fill=True, ln=True)
        self.set_text_color(0, 0, 0)
        self.ln(1)

        # Authors
        self.set_font("Helvetica", "I", 9)
        self.set_text_color(50, 50, 50)
        self.multi_cell(0, 5, clean(f"Authors: {paper['authors']}"))

        # Journal | Year | Citations
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(30, 80, 160)
        jy = f"{paper['journal']}  ({paper['year']})" if paper["journal"] else paper["year"]
        self.cell(0, 5, clean(jy), ln=True)
        self.set_text_color(60, 60, 60)
        self.set_font("Helvetica", "", 9)
        cite_line = f"Cited by: {paper['citations']:,}"
        if paper["url"]:
            cite_line += f"  |  URL: {paper['url']}"
        self.multi_cell(0, 5, clean(cite_line))
        self.set_text_color(0, 0, 0)
        self.ln(1)

        # Abstract
        self.set_font("Helvetica", "B", 9)
        self.cell(0, 5, "Abstract:", ln=True)
        self.set_font("Helvetica", "", 9)
        self.multi_cell(0, 5, clean(paper["abstract"]))
        self.ln(5)

        # Divider
        self.set_draw_color(200, 200, 200)
        self.set_line_width(0.3)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(5)


def build_pdf(
    focal: dict,
    doi: str,
    references: list[dict],
    citations: list[dict],
    out_path: str,
):
    pdf = NetworkPDF(focal_title=focal["title"], doi=doi)
    pdf.set_margins(18, 20, 18)
    pdf.set_auto_page_break(auto=True, margin=20)

    # ---- Page 1: Focal paper summary ----
    pdf.add_page()
    pdf.section_title("Focal Paper")
    pdf.focal_paper_box(focal, doi)

    # Stats summary
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(245, 245, 245)
    pdf.cell(0, 7, clean(
        f"  References retrieved: {len(references)}   |   "
        f"Citing papers retrieved: {len(citations)}"
    ), fill=True, ln=True)
    pdf.ln(4)

    # ---- Section A: References (papers cited by this paper) ----
    pdf.add_page()
    pdf.section_title(f"Part A — Papers Cited by This Paper  ({len(references)} papers, sorted by citation count)")
    for i, p in enumerate(references, 1):
        pdf.add_paper(i, p, section_color=(50, 100, 180))

    # ---- Section B: Citations (papers that cite this paper) ----
    pdf.add_page()
    pdf.section_title(f"Part B — Papers Citing This Paper  ({len(citations)} papers, sorted by citation count)")
    for i, p in enumerate(citations, 1):
        pdf.add_paper(i, p, section_color=(160, 60, 40))

    pdf.output(out_path)
    print(f"\nPDF saved to: {os.path.abspath(out_path)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    # ---- DOI input ----
    doi_raw = input("Enter DOI (e.g. 10.1017/S0003055421000150): ").strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "http://dx.doi.org/", "https://dx.doi.org/"):
        if doi_raw.startswith(prefix):
            doi_raw = doi_raw[len(prefix):]
            break
    doi = doi_raw.strip()
    if not doi:
        sys.exit("No DOI entered. Exiting.")

    # ---- API key: check hardcoded value, else prompt ----
    api_key = SEMANTIC_SCHOLAR_API_KEY.strip()
    if not api_key:
        api_key = input(
            "Semantic Scholar API key (press Enter to skip — free tier, slower): "
        ).strip()

    # ---- Max results ----
    max_str = input("Max papers to retrieve per section [default 300]: ").strip()
    max_results = int(max_str) if max_str.isdigit() else 300

    script_dir = os.path.dirname(os.path.abspath(__file__))
    out_path = os.path.join(script_dir, f"citation_network_{doi.replace('/', '_')}.pdf")
    headers  = make_headers(api_key or None)

    # 1. Focal paper
    print(f"\nFetching focal paper: DOI:{doi} ...", flush=True)
    raw_focal = fetch_paper(doi, headers)
    if not raw_focal or raw_focal.get("_not_found"):
        print(f"\nError: Paper not found in Semantic Scholar for DOI '{doi}'.")
        print("Check that the DOI is correct and exists in Semantic Scholar.")
        return
    focal  = parse_paper(raw_focal)
    paper_id = raw_focal["paperId"]
    if focal["abstract"] == "No abstract available." and focal["doi"]:
        focal["abstract"] = (
            fetch_crossref_abstract(focal["doi"])
            or fetch_openalex_abstract(focal["doi"])
            or focal["abstract"]
        )
    print(f"  Found: {focal['title'][:80]}")
    print(f"  Year: {focal['year']}  |  Citations: {focal['citations']:,}")

    # 2. References
    print(f"\nFetching references (up to {max_results}) ...", flush=True)
    raw_refs, refs_suppressed = fetch_all_pages(f"{BASE_URL}/{paper_id}/references", headers, max_results)
    if refs_suppressed:
        print("  Publisher suppressed references in S2. Falling back to CrossRef ...", flush=True)
        ref_dois = fetch_crossref_references(doi)
        print(f"  Found {len(ref_dois)} reference DOIs in CrossRef. Looking up in S2 ...", flush=True)
        references = sorted(
            batch_lookup_s2(ref_dois[:max_results], headers),
            key=lambda p: p["citations"], reverse=True,
        )
    else:
        references = sorted(
            [parse_paper(r) for r in raw_refs],
            key=lambda p: p["citations"], reverse=True,
        )
    print(f"  Retrieved {len(references)} references.")
    enrich_abstracts(references)

    # 3. Citations
    print(f"\nFetching citing papers (up to {max_results}) ...", flush=True)
    raw_cits, _ = fetch_all_pages(f"{BASE_URL}/{paper_id}/citations", headers, max_results)
    citations = sorted(
        [parse_paper(c) for c in raw_cits],
        key=lambda p: p["citations"], reverse=True,
    )
    print(f"  Retrieved {len(citations)} citing papers.")
    enrich_abstracts(citations)

    # 4. Build PDF
    print("\nBuilding PDF ...", flush=True)
    build_pdf(focal, doi, references, citations, out_path)


if __name__ == "__main__":
    print("=" * 60)
    print("  Citation Network Builder")
    print("  Yifan (Frank) Xu")
    print("  Washington University in St. Louis")
    print("  frank.x@wustl.edu")
    print("=" * 60)
    print()
    while True:
        try:
            main()
        except Exception as e:
            print(f"\nUnexpected error: {e}")
        again = input("\nProcess another paper? (y/n): ").strip().lower()
        if again != "y":
            break
    print("Goodbye!")
    input("Press Enter to close...")
