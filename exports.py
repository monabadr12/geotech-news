"""
Excel workbooks for the archive: one per issue window, plus one for the whole
archive. Each has a colour-coded Dashboard (key figures, charts, a theme × use
heat map), a filterable Stories table and a Sources summary.
"""
import datetime as dt
from collections import Counter

from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, PieChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.chart.series import DataPoint
from openpyxl.formatting.rule import CellIsRule, ColorScaleRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

NAVY, ACCENT, INK, MUTED, LINE = "16324F", "C9A227", "1B2430", "5B6573", "D9DEE3"
USE_COLORS = {"Feature lead": "D38B00", "News brief": "2563D6", "Academia-to-Industry topic": "6B4FD6",
              "Regional insight": "1F9D63", "Watch only": "8A94A3", "": "B8C0CA"}
REL_COLORS = {5: "1E7B4F", 4: "4DA06E", 3: "D9A21B", 2: "C9CED6", 1: "C9CED6", 0: "B8C0CA"}
KPI_COLORS = [NAVY, "D38B00", "1E7B4F", "6B4FD6", "0B97A5"]
THIN = Side(style="thin", color=LINE)


def hexc(color):
    return color.lstrip("#").upper()


def tint(color, amount=0.82):
    c = hexc(color)
    rgb = [int(c[i:i + 2], 16) for i in (0, 2, 4)]
    return "".join(f"{round(v + (255 - v) * amount):02X}" for v in rgb)


def fill(color):
    return PatternFill("solid", start_color=hexc(color), end_color=hexc(color))


def as_date(iso):
    try:
        return dt.date.fromisoformat(iso[:10]) if iso else None
    except ValueError:
        return None


def section_title(ws, row, col, text, width=6):
    cell = ws.cell(row=row, column=col, value=text)
    cell.font = Font(bold=True, size=12, color=NAVY)
    for c in range(col, col + width):
        ws.cell(row=row, column=c).border = Border(bottom=Side(style="medium", color=ACCENT))


def header_row(ws, row, col, labels):
    for i, label in enumerate(labels):
        cell = ws.cell(row=row, column=col + i, value=label)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = fill(NAVY)
        cell.alignment = Alignment(horizontal="left" if i == 0 else "center", vertical="center", wrap_text=True)


def body_cell(ws, row, col, value, center=True):
    cell = ws.cell(row=row, column=col, value=value)
    cell.border = Border(bottom=THIN)
    cell.alignment = Alignment(horizontal="center" if center else "left", vertical="center")
    return cell


def labels(**show):
    """Data labels showing only what is asked (Excel and LibreOffice otherwise add names)."""
    opts = dict(showVal=False, showPercent=False, showSerName=False, showCatName=False, showLegendKey=False,
                showLeaderLines=False)
    opts.update(show)
    return DataLabelList(**opts)


def colour_points(series, colors):
    for i, color in enumerate(colors):
        pt = DataPoint(idx=i)
        pt.graphicalProperties.solidFill = hexc(color)
        pt.graphicalProperties.line.solidFill = hexc(color)
        series.dPt.append(pt)


def write_workbook(path, title, subtitle, stories, themes, theme_color, timeline, timeline_label):
    """stories carry _digest/_window like the site's; timeline is [(label, count)]."""
    wb = Workbook()
    dash = wb.active
    dash.title = "Dashboard"
    dash.sheet_view.showGridLines = False
    for col in range(1, 20):
        dash.column_dimensions[get_column_letter(col)].width = 13
    dash.column_dimensions["A"].width = 36
    dash.page_setup.orientation = "landscape"
    dash.page_setup.fitToWidth, dash.page_setup.fitToHeight = 1, 0
    dash.sheet_properties.pageSetUpPr.fitToPage = True

    # ---- banner
    dash.merge_cells("A1:N1")
    dash["A1"] = title
    dash["A1"].font = Font(bold=True, size=20, color="FFFFFF")
    dash["A1"].fill = fill(NAVY)
    dash["A1"].alignment = Alignment(vertical="center", indent=1)
    dash.row_dimensions[1].height = 40
    dash.merge_cells("A2:N2")
    dash["A2"] = f"{subtitle} · generated {dt.date.today():%d %b %Y}"
    dash["A2"].font = Font(italic=True, color="FFFFFF")
    dash["A2"].fill = fill("23466B")
    dash["A2"].alignment = Alignment(vertical="center", indent=1)
    dash.row_dimensions[2].height = 22
    for c in range(1, 15):
        dash.cell(row=3, column=c).fill = fill(ACCENT)
    dash.row_dimensions[3].height = 4

    # ---- key figures
    digests = {s["_digest"] for s in stories}
    kpis = [("Stories", len(stories)), ("Daily digests", len(digests)),
            ("Rated 5 / 5", sum(1 for s in stories if s.get("relevance") == 5)),
            ("Feature leads", sum(1 for s in stories if s.get("use") == "Feature lead")),
            ("Sources", len({s["source"] for s in stories}))]
    dash.row_dimensions[5].height = 36
    for i, (label, value) in enumerate(kpis):
        col = 1 if i == 0 else 2 + (i - 1) * 2
        span = 1 if i == 0 else 2
        if span > 1:
            dash.merge_cells(start_row=5, start_column=col, end_row=5, end_column=col + 1)
            dash.merge_cells(start_row=6, start_column=col, end_row=6, end_column=col + 1)
        v, lab = dash.cell(row=5, column=col, value=value), dash.cell(row=6, column=col, value=label.upper())
        v.font = Font(bold=True, size=22, color="FFFFFF")
        lab.font = Font(bold=True, size=9, color=KPI_COLORS[i])
        for c in range(col, col + span):
            dash.cell(row=5, column=c).fill = fill(KPI_COLORS[i])
            dash.cell(row=6, column=c).fill = fill(tint(KPI_COLORS[i], .85))
        v.alignment = lab.alignment = Alignment(horizontal="center", vertical="center")

    if not stories:
        dash["A9"] = "No stories in this period yet."
        _stories_sheet(wb, stories, theme_color)
        wb.save(path)
        return

    # ---- stories by theme (table + bar chart)
    row = 9
    section_title(dash, row, 1, "Stories by theme", 5)
    header_row(dash, row + 1, 1, ["Theme", "Stories", "Rated 5", "Rated 4", "Feature leads"])
    present = [t for t in themes if any(s["theme"] == t for s in stories)]
    for i, t in enumerate(present):
        r = row + 2 + i
        ts = [s for s in stories if s["theme"] == t]
        name = body_cell(dash, r, 1, t, center=False)
        name.fill = fill(tint(theme_color(t)))
        name.font = Font(bold=True, color=hexc(theme_color(t)))
        name.border = Border(left=Side(style="thick", color=hexc(theme_color(t))), bottom=THIN)
        body_cell(dash, r, 2, len(ts)).font = Font(bold=True)
        body_cell(dash, r, 3, sum(1 for s in ts if s.get("relevance") == 5))
        body_cell(dash, r, 4, sum(1 for s in ts if s.get("relevance") == 4))
        body_cell(dash, r, 5, sum(1 for s in ts if s.get("use") == "Feature lead"))
    last = row + 1 + len(present)
    chart = BarChart()
    chart.type, chart.style, chart.title = "bar", 10, "Stories by theme"
    chart.add_data(Reference(dash, min_col=2, min_row=row + 1, max_row=last), titles_from_data=True)
    chart.set_categories(Reference(dash, min_col=1, min_row=row + 2, max_row=last))
    chart.legend = None
    chart.y_axis.majorGridlines = None
    chart.x_axis.scaling.orientation = "maxMin"
    chart.dataLabels = labels(showVal=True)
    colour_points(chart.series[0], [theme_color(t) for t in present])
    chart.width, chart.height = 17, 8.5
    dash.add_chart(chart, "G9")

    # ---- suggested use (table + doughnut-style pie)
    row = max(last + 3, 28)
    section_title(dash, row, 1, "Suggested editorial use", 3)
    header_row(dash, row + 1, 1, ["Use", "Stories", "Share"])
    uses = Counter(s.get("use") or "Not rated" for s in stories).most_common()
    for i, (u, n) in enumerate(uses):
        r = row + 2 + i
        c = body_cell(dash, r, 1, u, center=False)
        c.font = Font(bold=True, color=USE_COLORS.get(u if u != "Not rated" else "", MUTED))
        body_cell(dash, r, 2, n)
        share = body_cell(dash, r, 3, n / len(stories))
        share.number_format = "0%"
    pie = PieChart()
    pie.title = "Suggested use"
    pie.add_data(Reference(dash, min_col=2, min_row=row + 1, max_row=row + 1 + len(uses)), titles_from_data=True)
    pie.set_categories(Reference(dash, min_col=1, min_row=row + 2, max_row=row + 1 + len(uses)))
    pie.dataLabels = labels(showPercent=True)
    colour_points(pie.series[0], [USE_COLORS.get(u if u != "Not rated" else "", MUTED) for u, _ in uses])
    pie.width, pie.height = 9, 7.5
    dash.add_chart(pie, f"G{row}")

    # ---- relevance distribution (column chart)
    header_row(dash, row + 1, 5, ["Relevance", "Stories"])
    levels = [5, 4, 3, 0]
    for i, lvl in enumerate(levels):
        r = row + 2 + i
        body_cell(dash, r, 5, f"{lvl} / 5" if lvl else "Keyword-ranked").font = Font(bold=True, color=REL_COLORS[lvl])
        body_cell(dash, r, 6, sum(1 for s in stories if (s.get("relevance") or 0) == lvl))
    col_chart = BarChart()
    col_chart.title, col_chart.style = "Geotechnical relevance", 10
    col_chart.add_data(Reference(dash, min_col=6, min_row=row + 1, max_row=row + 5), titles_from_data=True)
    col_chart.set_categories(Reference(dash, min_col=5, min_row=row + 2, max_row=row + 5))
    col_chart.legend = None
    col_chart.y_axis.majorGridlines = None
    col_chart.dataLabels = labels(showVal=True)
    colour_points(col_chart.series[0], [REL_COLORS[lvl] for lvl in levels])
    col_chart.width, col_chart.height = 8.5, 7.5
    dash.add_chart(col_chart, f"L{row}")

    # ---- timeline
    row += 17
    section_title(dash, row, 1, f"Stories per {timeline_label}", 2)
    header_row(dash, row + 1, 1, [timeline_label.capitalize(), "Stories"])
    for i, (label, n) in enumerate(timeline):
        body_cell(dash, row + 2 + i, 1, label, center=False)
        body_cell(dash, row + 2 + i, 2, n)
    line = LineChart() if len(timeline) > 1 else BarChart()
    line.title, line.style = f"Stories per {timeline_label}", 12
    line.add_data(Reference(dash, min_col=2, min_row=row + 1, max_row=row + 1 + len(timeline)), titles_from_data=True)
    line.set_categories(Reference(dash, min_col=1, min_row=row + 2, max_row=row + 1 + len(timeline)))
    line.legend = None
    line.y_axis.majorGridlines = None
    s0 = line.series[0]
    s0.graphicalProperties.line.solidFill = hexc(ACCENT)
    s0.graphicalProperties.line.width = 28000
    if isinstance(line, BarChart):
        s0.graphicalProperties.solidFill = hexc(ACCENT)
    line.width, line.height = 17, 7.5
    dash.add_chart(line, f"G{row}")

    # ---- theme × use heat map
    row = max(row + 2 + len(timeline), row + 16) + 2
    use_cols = [u for u in USE_COLORS if u] + ["Not rated"]
    section_title(dash, row, 1, "Theme × suggested use (heat map)", len(use_cols) + 1)
    header_row(dash, row + 1, 1, ["Theme"] + use_cols)
    for i, t in enumerate(present):
        r = row + 2 + i
        name = body_cell(dash, r, 1, t, center=False)
        name.font = Font(bold=True, color=hexc(theme_color(t)))
        for j, u in enumerate(use_cols):
            key = "" if u == "Not rated" else u
            body_cell(dash, r, 2 + j, sum(1 for s in stories if s["theme"] == t and (s.get("use") or "") == key))
    rng = f"B{row + 2}:{get_column_letter(1 + len(use_cols))}{row + 1 + len(present)}"
    dash.conditional_formatting.add(rng, ColorScaleRule(start_type="min", start_color="FFFFFF",
                                                        mid_type="percentile", mid_value=50, mid_color="F6E3A6",
                                                        end_type="max", end_color="D38B00"))
    dash.row_dimensions[row + 1].height = 32

    _stories_sheet(wb, stories, theme_color)
    _sources_sheet(wb, stories, theme_color)
    wb.save(path)


def _stories_sheet(wb, stories, theme_color):
    ws = wb.create_sheet("Stories")
    cols = [("Digest date", 13), ("Issue window", 11), ("Theme", 26), ("Relevance", 10), ("Suggested use", 18),
            ("Headline (English)", 52), ("Original headline", 36), ("Magazine angle", 52), ("Source", 22),
            ("Google News edition", 16), ("Published", 12), ("Keywords", 28), ("Link", 14)]
    for i, (name, width) in enumerate(cols, 1):
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.append([c[0] for c in cols])
    ordered = sorted(stories, key=lambda s: (s["_digest"], s.get("relevance") or 0, s["rank"]), reverse=True)
    for s in ordered:
        ws.append([as_date(s["_digest"]), s["_window"], s["theme"], s.get("relevance") or None, s.get("use", ""),
                   s.get("title_en") or s["title"], s["title"] if s.get("title_en") else "", s.get("angle", ""),
                   s["source"], s.get("_region", ""), as_date(s.get("published")),
                   ", ".join(s.get("keywords", [])), "Open article"])
        r = ws.max_row
        ws.cell(row=r, column=13).hyperlink = s["link"]
        ws.cell(row=r, column=13).font = Font(color="1D5A8A", underline="single")
        theme = ws.cell(row=r, column=3)
        theme.fill = fill(tint(theme_color(s["theme"])))
        theme.font = Font(bold=True, color=hexc(theme_color(s["theme"])))
        use = ws.cell(row=r, column=5)
        use.font = Font(bold=True, color=USE_COLORS.get(s.get("use", ""), MUTED))
        for c in (1, 11):
            ws.cell(row=r, column=c).number_format = "dd mmm yyyy"
        for c in range(1, 14):
            ws.cell(row=r, column=c).alignment = Alignment(vertical="top", wrap_text=c in (6, 7, 8, 12),
                                                           horizontal="center" if c == 4 else None)
        ws.row_dimensions[r].height = 48 if (s.get("angle") or len(s["title"]) > 90) else 30
    end = max(ws.max_row, 2)
    table = Table(displayName="Stories", ref=f"A1:M{end}")
    table.tableStyleInfo = TableStyleInfo(name="TableStyleLight9", showRowStripes=True)
    ws.add_table(table)
    for lvl, color in ((5, REL_COLORS[5]), (4, REL_COLORS[4]), (3, REL_COLORS[3])):
        ws.conditional_formatting.add(f"D2:D{end}", CellIsRule(operator="equal", formula=[str(lvl)],
                                                               fill=fill(color), font=Font(bold=True, color="FFFFFF")))
    for c in range(1, 14):
        h = ws.cell(row=1, column=c)
        h.font = Font(bold=True, color="FFFFFF")
        h.fill = fill(NAVY)
        h.alignment = Alignment(vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 30
    ws.freeze_panes = "D2"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = "1:1"


def _sources_sheet(wb, stories, theme_color):
    ws = wb.create_sheet("Sources")
    ws.sheet_view.showGridLines = False
    widths = [34, 10, 16, 32]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    header_row(ws, 1, 1, ["Source", "Stories", "Average relevance", "Most frequent theme"])
    by_source = {}
    for s in stories:
        by_source.setdefault(s["source"], []).append(s)
    for i, (src, items) in enumerate(sorted(by_source.items(), key=lambda kv: -len(kv[1])), 2):
        rated = [s["relevance"] for s in items if s.get("relevance")]
        top = Counter(s["theme"] for s in items).most_common(1)[0][0]
        body_cell(ws, i, 1, src, center=False).font = Font(bold=True)
        body_cell(ws, i, 2, len(items))
        avg = body_cell(ws, i, 3, round(sum(rated) / len(rated), 1) if rated else None)
        avg.number_format = "0.0"
        t = body_cell(ws, i, 4, top, center=False)
        t.font = Font(color=hexc(theme_color(top)), bold=True)
    end = max(ws.max_row, 2)
    ws.conditional_formatting.add(f"B2:B{end}", ColorScaleRule(start_type="min", start_color="FFFFFF",
                                                              end_type="max", end_color="7FB3E6"))
    ws.freeze_panes = "A2"
