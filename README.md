# do_more_reading

*when you need to read...*

A collection of Python scripts for academic research workflows.

---

## Scripts

### `doi_network.py` — Citation Network Builder

Give it a DOI, get a PDF.

This script takes a paper's DOI and generates a formatted PDF report containing:
- **The focal paper** — full metadata and abstract
- **Part A: References** — all papers cited by this paper, sorted by citation count
- **Part B: Citations** — all papers that have cited this paper, sorted by citation count

Each entry includes title, authors, journal, year, citation count, URL, and abstract.

**Abstract coverage** is maximized through a three-source fallback chain:
1. Semantic Scholar API
2. CrossRef API (recovers publisher-suppressed abstracts)
3. OpenAlex API (catches what CrossRef misses)

Similarly, **references** suppressed by publishers are recovered automatically via CrossRef.

---

## Requirements

- Python 3.10+
- Two packages (the script will tell you if either is missing):

```bash
pip install requests fpdf
```

- A **Semantic Scholar API key** (free) — [get one here](https://www.semanticscholar.org/product/api)
  - You can also skip this and use the free unauthenticated tier, but it is slower and more rate-limited

---

## Usage

1. Open a terminal and run:

```bash
python doi_network.py
```

2. The script will prompt you interactively:

```
Enter DOI (e.g. 10.1017/S0003055421000150):
Semantic Scholar API key (press Enter to skip — free tier, slower):
Max papers to retrieve per section [default 300]:
```

3. The PDF is saved in the **same folder as the script**, named automatically:
```
citation_network_10.1017_S0003055421000150.pdf
```

4. After each run, you can choose to process another DOI or exit.

**Tip:** To avoid entering your API key every time, open `doi_network.py` and paste it directly into the script:

```python
SEMANTIC_SCHOLAR_API_KEY = "your_key_here"
```

---

## Output Example

```
============================================================
  Citation Network Builder
  Yifan (Frank) Xu
  Washington University in St. Louis
  frank.x@wustl.edu
============================================================

Enter DOI: 10.1177/0022002715603097

Fetching focal paper ...
  Found: When Security Dominates the Agenda
  Year: 2016  |  Citations: 47

Fetching references (up to 300) ...
  Publisher suppressed references in S2. Falling back to CrossRef ...
  Found 70 reference DOIs in CrossRef. Looking up in S2 ...
  Retrieved 65 references.
  Fetching 60 missing abstract(s) from CrossRef / OpenAlex ...

Fetching citing papers (up to 300) ...
  Retrieved 47 citing papers.

Building PDF ...
PDF saved to: C:\Users\...\citation_network_10.1177_0022002715603097.pdf
```

---

## Notes

- The script respects API rate limits automatically (Semantic Scholar: ~1 req/sec; CrossRef and OpenAlex: 0.3 sec between calls)
- Papers not indexed in Semantic Scholar will still appear if their DOI is found via CrossRef, but may have less metadata
- A small number of very old papers may genuinely have no abstract available in any database

---

## Author

**Yifan (Frank) Xu**
Washington University in St. Louis
frank.x@wustl.edu
