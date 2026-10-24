"""
Word report on the website: current status, an automatic review of the latest
scan, source health, archive figures, the change log and open items.
Regenerated after every scan, so it is always up to date. The change log and
open items come from data/changelog.yaml.
"""
import datetime as dt
import json
from collections import Counter

import yaml
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

NAVY, ACCENT, MUTED = "16324F", "C9A227", "5B6573"


def rgb(hexstr):
    return RGBColor.from_string(hexstr.lstrip("#").upper())


def shade(cell, hexstr):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hexstr.lstrip("#").upper())
    tc_pr.append(shd)


def tint(hexstr, amount=0.85):
    c = hexstr.lstrip("#")
    return "".join(f"{round(int(c[i:i + 2], 16) + (255 - int(c[i:i + 2], 16)) * amount):02X}" for i in (0, 2, 4))


def table(doc, headers, rows, widths, first_col_colors=None):
    t = doc.add_table(rows=1, cols=len(headers))
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.style = "Table Grid"
    for i, h in enumerate(headers):
        cell = t.rows[0].cells[i]
        cell.text = ""
        run = cell.paragraphs[0].add_run(h)
        run.bold, run.font.size, run.font.color.rgb = True, Pt(9.5), rgb("FFFFFF")
        shade(cell, NAVY)
    for r, values in enumerate(rows):
        cells = t.add_row().cells
        for i, v in enumerate(values):
            cells[i].text = ""
            run = cells[i].paragraphs[0].add_run(str(v))
            run.font.size = Pt(9.5)
            if i == 0 and first_col_colors:
                run.bold = True
                run.font.color.rgb = rgb(first_col_colors[r])
                shade(cells[i], tint(first_col_colors[r]))
            elif r % 2:
                shade(cells[i], "F3F5F7")
    t.autofit = False
    for i, w in enumerate(widths):
        t.columns[i].width = Cm(w)
    for row in t.rows:
        for i, w in enumerate(widths):
            row.cells[i].width = Cm(w)
    doc.add_paragraph()
    return t


def bullet(doc, text, bold_prefix=""):
    p = doc.add_paragraph(style="List Bullet")
    if bold_prefix:
        p.add_run(bold_prefix).bold = True
    p.add_run(text)
    return p


def heading(doc, text, level=1):
    h = doc.add_heading(text, level=level)
    for run in h.runs:
        run.font.color.rgb = rgb(NAVY if level == 1 else "23466B")
    return h


def page_number_footer(section):
    p = section.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("Geotechnical News Desk · Site report · page ")
    run.font.size, run.font.color.rgb = Pt(8), rgb(MUTED)
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), "PAGE")
    r = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = "1"
    r.append(t)
    fld.append(r)
    p._p.append(fld)


def source_advice(error):
    e = error.lower()
    if "403" in e or "405" in e:
        return "The site blocks automated readers. Look for its RSS feed address, or rely on the Google News searches."
    if "no rss" in e:
        return "No feed at this address. Find the site's RSS feed (often /feed/ or an RSS icon) and update config.yaml."
    if "404" in e:
        return "The address has moved. Update it in config.yaml."
    if "timeout" in e or "max retries" in e:
        return "The site did not answer. If it fails again on the next scans, replace or remove it."
    return "Check the address in config.yaml."


def review_findings(latest, cfg, windows):
    """Automatic review of the latest scan: (level, text) pairs."""
    out = []
    if not latest:
        return [("info", "No scan has run yet.")]
    stories = latest["stories"]
    if latest.get("ai_used"):
        out.append(("ok", "Claude triage ran: stories are rated, themed, given an angle and translated."))
    else:
        note = next((n for n in latest.get("notes", []) if "AI triage" in n), "")
        out.append(("warn", "Claude triage did not run, so stories are ranked by keywords only. "
                    + (note or "Add the ANTHROPIC_API_KEY secret to enable it.")))
    feeds = len(cfg.get("feeds", []))
    failed = len(latest.get("failures", []))
    out.append(("warn" if failed > feeds / 4 else "ok",
                f"{feeds - failed} of {feeds} websites were read successfully; {failed} failed (see Source health)."))
    if stories:
        themes = Counter(s["theme"] for s in stories)
        top, n = themes.most_common(1)[0]
        share = n / len(stories)
        out.append(("warn" if share > 0.6 else "ok",
                    f"Theme balance: {len(themes)} themes covered; the largest is {top} with {n} of "
                    f"{len(stories)} stories ({share:.0%})."))
        sources = Counter(s["source"] for s in stories)
        out.append(("info", f"{len(sources)} different outlets contributed; the most frequent was "
                            f"{sources.most_common(1)[0][0]} ({sources.most_common(1)[0][1]} stories)."))
        foreign = sum(1 for s in stories if s.get("region") and s.get("region") not in ("GB", "US", "IN", "AU", "ZA", "SG", "AE"))
        out.append(("info", f"{foreign} stories came from non-English Google News editions."))
        if latest.get("ai_used"):
            strong = sum(1 for s in stories if s.get("relevance", 0) >= 4)
            out.append(("info", f"{strong} stories were rated 4 or 5 out of 5."))
    else:
        out.append(("warn", "The latest scan selected no stories."))
    return out


def write_report(path, cfg, digests, windows, theme_color, site_url, changelog_path):
    log = yaml.safe_load(changelog_path.read_text(encoding="utf-8")) if changelog_path.exists() else {}
    latest = digests[0] if digests else None
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    for side in ("left_margin", "right_margin"):
        setattr(section, side, Cm(2))
    section.top_margin = section.bottom_margin = Cm(1.8)
    page_number_footer(section)
    normal = doc.styles["Normal"]
    normal.font.name, normal.font.size = "Calibri", Pt(10.5)

    # ---- cover block
    p = doc.add_paragraph()
    run = p.add_run("GEOTECHNICAL NEWS DESK")
    run.bold, run.font.size, run.font.color.rgb = True, Pt(10), rgb("9A7B1C")
    title = doc.add_paragraph()
    run = title.add_run("Website report: updates and review")
    run.bold, run.font.size, run.font.color.rgb = True, Pt(24), rgb(NAVY)
    p = doc.add_paragraph()
    run = p.add_run(f"{(cfg.get('magazine') or {}).get('name', 'ISSMGE Magazine')} · generated "
                    f"{dt.datetime.now(dt.timezone.utc):%d %B %Y, %H:%M} UTC · updated automatically after every scan")
    run.font.size, run.font.color.rgb = Pt(9.5), rgb(MUTED)
    if site_url:
        p = doc.add_paragraph()
        run = p.add_run(f"Website: {site_url}")
        run.font.size, run.font.color.rgb = Pt(9.5), rgb("1D5A8A")
    bar = doc.add_paragraph()
    bar_pr = bar._p.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    for k, v in (("val", "single"), ("sz", "18"), ("space", "1"), ("color", ACCENT)):
        bottom.set(qn(f"w:{k}"), v)
    bdr.append(bottom)
    bar_pr.append(bdr)

    # ---- 1. at a glance
    heading(doc, "1. At a glance")
    total = sum(len(d["stories"]) for d in digests)
    rows = [("Latest scan", f"{latest['date']} ({latest.get('generated', '')[11:16]} UTC)" if latest else "none yet"),
            ("Stories in latest digest", len(latest["stories"]) if latest else 0),
            ("New items scanned", latest.get("new_items", 0) if latest else 0),
            ("Triage method", ("Claude AI" if latest.get("ai_used") else "Keywords only") if latest else "—"),
            ("Stories archived", total), ("Daily digests archived", len(digests)),
            ("Issue windows", len(windows)),
            ("Websites failing on latest scan", f"{len(latest.get('failures', []))} of {len(cfg.get('feeds', []))}" if latest else "—")]
    table(doc, ["Item", "Value"], rows, [8, 9])

    # ---- features
    if log.get("features"):
        heading(doc, "What the website does")
        for item in log["features"]:
            name, _, text = item.partition(":")
            bullet(doc, text.strip(), bold_prefix=name.strip() + ": ") if text else bullet(doc, item)

    # ---- 2. review
    heading(doc, "2. Review of the latest scan")
    marks = {"ok": ("✔ ", "1E7B4F"), "warn": ("⚠ ", "B5560E"), "info": ("• ", MUTED)}
    for level, text in review_findings(latest, cfg, windows):
        p = doc.add_paragraph()
        mark, color = marks[level]
        r = p.add_run(mark)
        r.bold, r.font.color.rgb = True, rgb(color)
        p.add_run(text)
        p.paragraph_format.space_after = Pt(3)
    if latest and latest.get("notes"):
        heading(doc, "Scanner notes", 2)
        for n in latest["notes"]:
            bullet(doc, n)

    # ---- 3. source health
    heading(doc, "3. Source health")
    if latest and latest.get("failures"):
        doc.add_paragraph("These websites could not be read on the latest scan. Their stories may still arrive "
                          "through the Google News searches.")
        table(doc, ["Source", "Problem", "Suggested action"],
              [(n, e[:90], source_advice(e)) for n, e in latest["failures"]], [4, 5.5, 7.5])
    else:
        doc.add_paragraph("All websites were read successfully on the latest scan.")

    # ---- 4. archive
    heading(doc, "4. Archive by issue window")
    table(doc, ["Window", "Months", "Digests", "Stories", "Rated 5/5", "Feature leads"],
          [(w["win"]["label"], w["win"]["span"], len(w["digests"]), len(w["stories"]),
            sum(1 for s in w["stories"] if s.get("relevance") == 5),
            sum(1 for s in w["stories"] if s.get("use") == "Feature lead")) for w in windows] or [("—",) * 6],
          [2.5, 4.5, 2, 2, 2.5, 3])

    if windows:
        w = windows[0]
        heading(doc, f"5. {w['win']['label']} by theme")
        counts = Counter(s["theme"] for s in w["stories"])
        themes = [t for t in list(cfg["themes"]) + ["General"] if counts.get(t)]
        table(doc, ["Theme", "Stories", "Share", "Rated 4–5"],
              [(t, counts[t], f"{counts[t] / len(w['stories']):.0%}",
                sum(1 for s in w["stories"] if s["theme"] == t and (s.get("relevance") or 0) >= 4)) for t in themes],
              [8, 2.5, 2.5, 3], first_col_colors=[theme_color(t) for t in themes])

    # ---- 6. research papers
    papers = [dict(pp, _digest=d["date"]) for w in windows[:1] for d in w["digests"] for pp in d.get("papers", [])]
    heading(doc, "6. Research papers" + (f" ({windows[0]['win']['label']})" if windows else ""))
    if papers:
        journals = Counter(pp.get("journal", "") for pp in papers)
        doc.add_paragraph(f"{len(papers)} new papers from {len(journals)} journals were picked up for Academia-to-Industry topics.")
        table(doc, ["Journal", "Papers"], journals.most_common(), [12, 3])
        best = sorted(papers, key=lambda pp: -(pp.get("relevance") or 0))[:8]
        for pp in best:
            bullet(doc, f" — {pp.get('journal', '')}, {pp.get('published', '')}" + (f". {pp['angle']}" if pp.get("angle") else ""),
                   bold_prefix=pp.get("title", ""))
    else:
        doc.add_paragraph("No research papers have been collected in this issue window yet.")

    # ---- 7. issue briefs
    heading(doc, "7. Issue briefs")
    briefs = []
    for f in sorted((changelog_path.parent / "briefs").glob("*.json"), reverse=True):
        try:
            b = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        briefs.append((f.stem, b.get("status", "draft"), str(b.get("generated", ""))[:16].replace("T", " "),
                       f"{b.get('stories_considered', b.get('n_stories', '—'))} stories"))
    if briefs:
        doc.add_paragraph("Claude drafts a brief for each issue window: a proposed line-up per theme, feature leads, "
                          "Academia-to-Industry topics, a regional-balance check and gaps worth covering.")
        table(doc, ["Issue window", "Status", "Generated (UTC)", "Drafted from"], briefs, [3.5, 2.5, 5, 6])
    else:
        doc.add_paragraph("No issue brief has been generated yet. Drafts appear automatically in the last weeks of each "
                          "quarter, a final brief right after it closes, and any time from the issue page.")

    # ---- 8. change log
    heading(doc, "8. Change log")
    for entry in log.get("changes", []):
        p = doc.add_paragraph()
        r = p.add_run(f"{entry['date']} · {entry['title']}")
        r.bold, r.font.color.rgb = True, rgb("23466B")
        p.paragraph_format.space_before = Pt(8)
        for item in entry.get("items", []):
            bullet(doc, item)

    # ---- 9. open items
    if log.get("open_items"):
        heading(doc, "9. Open items and recommendations")
        for item in log["open_items"]:
            bullet(doc, item)

    doc.save(path)
