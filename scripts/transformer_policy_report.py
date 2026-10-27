"""HTML report of the transformer-policy finalist runs, with the FLRL manuscript's reported results beside them.

Reads only saved files: the screen and finalist summaries that transformer_policy_screen.py
wrote to the journal, and the finalists' own metric and observation journals. The numbers taken
from the manuscript are not part of the repository: they are read from manuscript.json in the
journal directory, or from the file given with --manuscript.

  python scripts/transformer_policy_report.py --journal runs/transformer-screen-20261012/journal \
      --trial-files runs/workspace/workspace/trials --output runs/transformer-screen-20261012/report

Reading the journals takes a few minutes; the extracted numbers are kept in report-data.json
beside the page and reused unless --refresh is given. --page-body also writes the page without
its document wrapper, for hosts that supply their own.
"""
import argparse
import base64
import html
import io
import json
import time
from pathlib import Path

import numpy as np

from optimization_framework.execution.metrics import full_row, scalar_rows

# What the manuscript reports is not kept in the repository; main() reads it from a local JSON file:
# "citation"; "best_84", "best_21" (best designs, percent); "samples", "seeds"; "curve_84" (pairs of
# samples in thousands and percent); "end_63", "end_42", "end_21", "adjoint" (percent at 100,000
# samples); "band_84" (low, high); "bars" (label, best, average, low, high for each method).
MANUSCRIPT = {}
NAMES = {"frame-128x2-lr1e-3": ("Frame-token transformer", "frame"), "coef-128x4-lr3e-4": ("Coefficient-token transformer", "coef"),
         "reference": ("Reference CNN", "ref")}
CHECKPOINTS = (20_000, 40_000, 60_000, 80_000, 100_000)
SILICON, AIR = (47, 59, 74), (232, 237, 242)


def extract(journal, trials):
    """The finalists' curves, sampled-design statistics and best designs, from their journals."""
    finalists = []
    for row in json.loads((journal / "finalist-summary.json").read_text()):
        values, seconds, parts, offset = [], [], [], 0.0
        for trial_id in row["trial_ids"]:
            last = {}
            for _, _, last in scalar_rows(trials / trial_id / "metrics.jsonl"):
                values.append(last["objective"])
                seconds.append(offset + last["elapsed_seconds"])
            offset += last["elapsed_seconds"]
            manifest = json.loads((trials / trial_id / "execution-manifest.json").read_text())
            parts.append({"trial_id": trial_id, "evaluations": last["evaluations"], "solver_calls": last["solver_calls"],
                          "seconds": last["elapsed_seconds"], "source": manifest["scientific_digest"][:12]})
        values, seconds = np.array(values), np.array(seconds)
        best = np.maximum.accumulate(values)
        improved = np.flatnonzero(np.diff(best, prepend=-1.0) > 0)
        at_hour = lambda hours: int(np.searchsorted(seconds, hours * 3600, side="right"))
        windows = []
        for index in range(int(round(seconds[-1] / 1800))):
            window = values[(seconds >= index * 1800) & (seconds < (index + 1) * 1800)]
            windows.append({"median": float(np.median(window)), "top": float(np.quantile(window, .99)), "count": int(len(window))})
        # The design that set the final best: found again in the observation journal of its part.
        position, start = int(improved[-1]), 0
        for part in parts:
            if position < start + part["evaluations"]:
                break
            start += part["evaluations"]
        observations = trials / part["trial_id"] / "observations.jsonl"
        where = next(offset for offset, _, record in scalar_rows(observations)
                     if record.get("status") == "ok" and record["objectives"]["mean_plus1_transmission"] == values[position])
        observation = full_row(observations, where)
        mask = np.array(observation["candidate"], dtype=np.uint8).reshape(128, 256)
        finalists.append({
            "key": row["key"], "parts": parts, "evaluations": int(len(values)), "hours": float(seconds[-1] / 3600),
            "improvements": [[int(i) + 1, float(best[i])] for i in improved],
            "best_at": {str(count): float(best[count - 1]) for count in CHECKPOINTS if count <= len(values)},
            "by_hour": {str(hours): {"best": float(best[at_hour(hours) - 1]), "evaluations": at_hour(hours)} for hours in (3, 6, 9, 12)},
            "windows": windows,
            "best": {"evaluation": position + 1, "hours": float(seconds[position] / 3600), "trial_id": part["trial_id"],
                     "observation_id": observation["id"], "objectives": observation["objectives"],
                     "silicon_fraction": float(mask.mean()), "mask": base64.b64encode(np.packbits(mask).tobytes()).decode()},
            "last_hour_median": float(np.median(values[seconds >= seconds[-1] - 3600])),
        })
    return {"extracted_at": time.strftime("%Y-%m-%d %H:%M"), "finalists": finalists,
            "screen": json.loads((journal / "screen-summary.json").read_text())}


def percent(value, digits=2):
    return f"{100 * value:.{digits}f}%"


def clock(hours):
    whole, minutes = divmod(round(hours * 60), 60)
    return f"{whole} h {minutes:02d} min" if whole else f"{minutes} min"


def mask_image(encoded):
    """The unit cell twice in each direction, as an inline PNG."""
    from PIL import Image
    mask = np.unpackbits(np.frombuffer(base64.b64decode(encoded), dtype=np.uint8))[:128 * 256].reshape(128, 256)
    tiled = np.tile(mask, (2, 2)).astype(bool)
    pixels = np.where(tiled[..., None], np.array(SILICON, dtype=np.uint8), np.array(AIR, dtype=np.uint8))
    stream = io.BytesIO()
    Image.fromarray(pixels, "RGB").save(stream, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode()


class Plot:
    """One SVG chart: a linear scale on each axis, drawn in the page's color tokens."""

    def __init__(self, width, height, x_range, y_range, left=50, right=24, top=14, bottom=46):
        self.width, self.height, self.x_range, self.y_range = width, height, x_range, y_range
        self.left, self.right, self.top, self.bottom = left, right, top, bottom
        self.parts = []

    def x(self, value):
        low, high = self.x_range
        return self.left + (value - low) / (high - low) * (self.width - self.left - self.right)

    def y(self, value):
        low, high = self.y_range
        return self.height - self.bottom - (value - low) / (high - low) * (self.height - self.top - self.bottom)

    def axes(self, x_ticks, y_ticks, x_label, y_label, x_format=str, y_format=str):
        for tick in y_ticks:
            self.parts.append(f'<line class="grid" x1="{self.left}" x2="{self.width - self.right}" y1="{self.y(tick):.1f}" y2="{self.y(tick):.1f}"/>'
                              f'<text class="tick" x="{self.left - 8}" y="{self.y(tick) + 4:.1f}" text-anchor="end">{y_format(tick)}</text>')
        for tick in x_ticks:
            self.parts.append(f'<line class="grid" x1="{self.x(tick):.1f}" x2="{self.x(tick):.1f}" y1="{self.top}" y2="{self.height - self.bottom}"/>'
                              f'<text class="tick" x="{self.x(tick):.1f}" y="{self.height - self.bottom + 18}" text-anchor="middle">{x_format(tick)}</text>')
        self.parts.append(f'<line class="axis" x1="{self.left}" x2="{self.width - self.right}" y1="{self.height - self.bottom}" y2="{self.height - self.bottom}"/>'
                          f'<text class="label" x="{(self.left + self.width - self.right) / 2:.1f}" y="{self.height - 8}" text-anchor="middle">{x_label}</text>'
                          f'<text class="label" transform="translate(13 {(self.top + self.height - self.bottom) / 2:.1f}) rotate(-90)" text-anchor="middle">{y_label}</text>')

    def line(self, points, kind, steps=False):
        path, previous = [], None
        for x, y in points:
            if steps and previous is not None:
                path.append(f"L{self.x(x):.1f} {self.y(previous):.1f}")
            path.append(f"{'L' if path else 'M'}{self.x(x):.1f} {self.y(y):.1f}")
            previous = y
        self.parts.append(f'<path class="series {kind}" d="{" ".join(path)}"/>')

    def rule(self, value, kind):
        self.parts.append(f'<line class="series {kind}" x1="{self.left}" x2="{self.width - self.right}" y1="{self.y(value):.1f}" y2="{self.y(value):.1f}"/>')

    def text(self, x, y, content, kind="note", anchor="start"):
        self.parts.append(f'<text class="{kind}" x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}">{content}</text>')

    def ends(self, labels, x):
        """Labels at the right edge, moved apart where the lines end close together."""
        placed, floor = [], None
        for value, kind, content in sorted(labels, reverse=True):
            y = self.y(value) + 4 if floor is None else max(self.y(value) + 4, floor + 15)
            placed.append((y, kind, content))
            floor = y
        for y, kind, content in placed:
            self.parts.append(f'<text class="end {kind}" x="{x:.1f}" y="{y:.1f}">{content}</text>')

    def svg(self, title):
        return (f'<div class="chart"><svg viewBox="0 0 {self.width} {self.height}" role="img" aria-label="{html.escape(title)}">'
                + "".join(self.parts) + "</svg></div>")


def progress_chart(finalists):
    plot = Plot(900, 470, (0, 120), (0, 100), right=70)
    plot.axes(range(0, 121, 20), range(0, 101, 20), "Designs evaluated (thousands)", "Best mean TE/TM efficiency so far (%)")
    plot.rule(MANUSCRIPT["best_84"], "paper-best")
    plot.text(plot.x(1.5), plot.y(MANUSCRIPT["best_84"]) - 6, f"Manuscript's best design, found within 500,000 samples: {MANUSCRIPT['best_84']}%")
    plot.rule(MANUSCRIPT["adjoint"], "adjoint")
    plot.line(MANUSCRIPT["curve_84"], "paper")
    x, y = MANUSCRIPT["curve_84"][-1]
    plot.parts.append(f'<circle class="dot paper" cx="{plot.x(x):.1f}" cy="{plot.y(y):.1f}" r="3.5"/>')
    ends = []
    for finalist in finalists:
        kind = NAMES[finalist["key"]][1]
        points = [(count / 1000, 100 * value) for count, value in finalist["improvements"]]
        points.append((finalist["evaluations"] / 1000, points[-1][1]))
        plot.line(points, kind, steps=True)
        ends.append((points[-1][1], kind, f"{points[-1][1]:.2f}%"))
    plot.ends(ends, plot.x(120) + 8)
    legend = [(NAMES[f["key"]][1], f"{NAMES[f['key']][0]} (this campaign, one seed)") for f in finalists]
    legend += [("paper", "Manuscript Fig. 3a: CNN policy, mean of three seeds"),
               ("adjoint", f"Adjoint design of the manuscript's ref. [9]: about {MANUSCRIPT['adjoint']}%")]
    for index, (kind, content) in enumerate(legend):
        y = plot.y(47) + 19 * index
        plot.parts.append(f'<line class="series {kind}" x1="{plot.x(46):.1f}" x2="{plot.x(46) + 26:.1f}" y1="{y - 4:.1f}" y2="{y - 4:.1f}"/>')
        plot.text(plot.x(46) + 34, y, content, "legend")
    return plot.svg("Best efficiency against designs evaluated, for the three finalists and the manuscript's reported curve")


def sampling_chart(finalists):
    plot = Plot(900, 380, (0, 12), (0, 100), right=70)
    plot.axes(range(0, 13), range(0, 101, 20), "Hours of search", "Median efficiency of the designs sampled (%)")
    for hours, content in ((3, "extended by 3 h"), (6, "extended by 6 h")):
        plot.parts.append(f'<line class="mark" x1="{plot.x(hours):.1f}" x2="{plot.x(hours):.1f}" y1="{plot.top}" y2="{plot.height - plot.bottom}"/>')
        plot.text(plot.x(hours) + 5, plot.y(4), content)
    ends = []
    for finalist in finalists:
        kind = NAMES[finalist["key"]][1]
        medians = [100 * window["median"] for window in finalist["windows"]]
        plot.line([((index + .5) / 2, value) for index, value in enumerate(medians)], kind)
        ends.append((medians[-1], kind, f"{medians[-1]:.1f}%"))
        # The deepest fall below what the policy had already reached, if there is a marked one.
        falls = [(max(medians[:index]) - value, index) for index, value in enumerate(medians) if index]
        depth, index = max(falls)
        if depth > 8:
            plot.parts.append(f'<circle class="dot {kind}" cx="{plot.x((index + .5) / 2):.1f}" cy="{plot.y(medians[index]):.1f}" r="3.5"/>')
            plot.text(plot.x((index + .5) / 2), plot.y(medians[index]) + 18, f"falls {depth:.0f} points", "note", "middle")
    plot.ends(ends, plot.x(12) + 8)
    for index, finalist in enumerate(finalists):
        kind, y = NAMES[finalist["key"]][1], plot.y(30) + 19 * index
        plot.parts.append(f'<line class="series {kind}" x1="{plot.x(7.6):.1f}" x2="{plot.x(7.6) + 26:.1f}" y1="{y - 4:.1f}" y2="{y - 4:.1f}"/>')
        plot.text(plot.x(7.6) + 34, y, NAMES[finalist["key"]][0], "legend")
    return plot.svg("Median efficiency of the designs each policy sampled, per half hour")


LADDER = ((10, 5), (10, 8), (12, 10), (14, 12), (18, 14), (22, 18), (26, 22))
SEARCHED = (10, 8)   # the RCWA orders every experiment of the campaign evaluated at
STUDY_KEYS = {"frame": "frame-128x2-lr1e-3", "coef": "coef-128x4-lr3e-4", "reference": "reference", "es": "es"}


def convergence(journal):
    """Each best design evaluated again at higher RCWA orders.

    Two sources: the campaign's own convergence check (experiments of the campaign), and a wider
    sweep made by calling the same evaluator directly, which is not a campaign record.
    Returns {"checks": {key: verdict...}, "values": {key: {(x, y): {mean, te, tm, record}}}, "designs": {...}}.
    """
    checked = json.loads((journal / "convergence-campaign-20261013.json").read_text())
    study = json.loads((journal / "convergence-study-20261013.json").read_text())
    values = {key: {} for key in STUDY_KEYS.values()}
    for row in study["rows"]:
        if "mean" in row and row["design"] in STUDY_KEYS:
            values[STUDY_KEYS[row["design"]]][(row["x"], row["y"])] = {"mean": row["mean"], "te": row["te"], "tm": row["tm"], "record": False}
    for key, row in checked.items():
        for observation in row["observations"]:
            if observation["repeat"] == 0:
                order = (observation["fidelity"]["rcwa_order_x"], observation["fidelity"]["rcwa_order_y"])
                objectives = observation["objectives"]
                values[key][order] = {"mean": objectives["mean_plus1_transmission"], "te": objectives["te_plus1_transmission"],
                                      "tm": objectives["tm_plus1_transmission"], "record": True}
    return {"checks": {key: {name: row[name] for name in ("validation_trial_id", "numerical_status", "last_two_absolute_differences", "highest_fidelity")}
                       for key, row in checked.items()},
            "values": values, "designs": study["designs"],
            "sources": sorted({row["source"] for row in study["rows"] if row.get("source")})}


def convergence_chart(values):
    plot = Plot(900, 430, (-.35, len(LADDER) - 1), (0, 100), right=70)
    plot.axes(range(len(LADDER)), range(0, 101, 20), "RCWA orders (x, y)", "Efficiency of the same design (%)",
              x_format=lambda index: f"({LADDER[index][0]}, {LADDER[index][1]})")
    searched = LADDER.index(SEARCHED)
    plot.parts.append(f'<line class="mark" x1="{plot.x(searched):.1f}" x2="{plot.x(searched):.1f}" y1="{plot.top}" y2="{plot.height - plot.bottom}"/>')
    plot.text(plot.x(searched) + 6, plot.y(3), "orders of the searches")
    ends = []
    for key, (label, kind) in NAMES.items():
        for quantity in ("te", "mean"):
            points = [(index, 100 * values[key][order][quantity]) for index, order in enumerate(LADDER) if order in values[key]]
            plot.line(points, kind + (" te" if quantity == "te" else ""))
            for index, value in points:
                if quantity == "mean":
                    plot.parts.append(f'<circle class="dot {kind}" cx="{plot.x(index):.1f}" cy="{plot.y(value):.1f}" r="3"/>')
        ends.append((points[-1][1], kind, f"{points[-1][1]:.1f}%"))
    plot.ends(ends, plot.x(len(LADDER) - 1) + 10)
    for index, (kind, content) in enumerate([*((kind, label + ": mean of TE and TM") for label, kind in NAMES.values()), ("ref te", "Dashed, in each color: TE alone")]):
        y = plot.y(29) + 19 * index
        plot.parts.append(f'<line class="series {kind}" x1="{plot.x(-.2):.1f}" x2="{plot.x(-.2) + 26:.1f}" y1="{y - 4:.1f}" y2="{y - 4:.1f}"/>')
        plot.text(plot.x(-.2) + 34, y, content, "legend")
    return plot.svg("Efficiency of each best design evaluated again at increasing RCWA orders")


def table(head, rows, numeric=(), compact=False):
    cells = lambda tag, row: "".join(f'<{tag}{' class="num"' if index in numeric else ""}>{cell}</{tag}>' for index, cell in enumerate(row))
    return (f'<div class="scroll"><table{' class="compact"' if compact else ""}><thead><tr>' + cells("th", head) + "</tr></thead><tbody>"
            + "".join("<tr>" + cells("td", row) + "</tr>" for row in rows) + "</tbody></table></div>")


STYLE = """
/* One reading column; figures and tables take the column's full width, running text a narrower measure. */
:root {
  --bg: #f5f7f9; --panel: #ffffff; --fg: #18212c; --muted: #5b6979; --rule: #d7dde5;
  --frame: #0d7391; --coef: #b06a00; --ref: #485464; --paper: #b4261c;
  --display: "IBM Plex Sans Condensed", "Arial Narrow", "Helvetica Neue", Arial, sans-serif;
  --body: "IBM Plex Sans", "Helvetica Neue", Arial, sans-serif;
  --data: "IBM Plex Mono", ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) { --bg: #10151b; --panel: #171e26; --fg: #e5eaf0; --muted: #9ba8b6; --rule: #2b3643;
    --frame: #56bcdb; --coef: #e3a548; --ref: #b9c3cf; --paper: #ff8c82; color-scheme: dark }
}
:root[data-theme="dark"] { --bg: #10151b; --panel: #171e26; --fg: #e5eaf0; --muted: #9ba8b6; --rule: #2b3643;
  --frame: #56bcdb; --coef: #e3a548; --ref: #b9c3cf; --paper: #ff8c82; color-scheme: dark }
body { background: var(--bg); color: var(--fg); font-family: var(--body); font-size: 16px; line-height: 1.55; margin: 0 }
main { max-width: 940px; margin: 0 auto; padding-inline: 20px; padding-block: 40px 72px; display: flex; flex-direction: column; gap: 44px }
header, section { display: flex; flex-direction: column; gap: 16px; min-width: 0 }
h1, h2, h3 { font-family: var(--display); text-wrap: balance; margin: 0; line-height: 1.15 }
h1 { font-size: 2.3rem; font-weight: 600; letter-spacing: -.01em }
h2 { font-size: 1.5rem; font-weight: 600; padding-top: 14px; border-top: 2px solid var(--fg) }
h3 { font-size: 1.1rem; font-weight: 600 }
p, ul { margin: 0; max-width: 68ch }
ul { padding-left: 1.2em; display: flex; flex-direction: column; gap: 8px }
.lede { font-size: 1.15rem; max-width: 62ch }
.kicker { font-family: var(--display); text-transform: uppercase; letter-spacing: .08em; font-size: .82rem; color: var(--muted) }
.spec { display: flex; flex-wrap: wrap; gap: 6px 18px; font-family: var(--data); font-size: .8rem; color: var(--muted);
  border-block: 1px solid var(--rule); padding-block: 10px }
.spec b { color: var(--fg); font-weight: 500 }
.note, figcaption, .small { color: var(--muted); font-size: .88rem; max-width: 76ch }
td .small { font-size: .78rem }
table.compact th, table.compact td { padding: 8px 7px }
table.compact .name { white-space: normal }
figure { margin: 0; display: flex; flex-direction: column; gap: 10px; min-width: 0 }
.chart, .scroll { overflow-x: auto; background: var(--panel); border: 1px solid var(--rule) }
.chart svg { display: block; width: 100%; min-width: 680px; height: auto }
.chart text { font-family: var(--body); fill: var(--muted); font-size: 12.5px }
.chart .label { fill: var(--fg); font-size: 13px }
.chart .legend, .chart .end { fill: var(--fg) }
.chart .end { font-family: var(--data); font-size: 12.5px; font-weight: 500 }
.chart .grid { stroke: var(--rule); stroke-width: 1 }
.chart .axis { stroke: var(--fg); stroke-width: 1 }
.chart .mark { stroke: var(--muted); stroke-width: 1; stroke-dasharray: 2 4 }
.chart .series { fill: none; stroke-width: 2.2; stroke-linejoin: round }
.chart .series.frame { stroke: var(--frame) } .chart .series.coef { stroke: var(--coef) } .chart .series.ref { stroke: var(--ref) }
.chart .series.paper { stroke: var(--paper); stroke-dasharray: 7 4 }
.chart .series.te { stroke-width: 1.4; stroke-dasharray: 5 4 }
.chart .series.paper-best { stroke: var(--paper); stroke-width: 1.2; stroke-dasharray: 2 3 }
.chart .series.adjoint { stroke: var(--muted); stroke-width: 1.2; stroke-dasharray: 2 3 }
.chart .dot { stroke: none } .chart .dot.frame { fill: var(--frame) } .chart .dot.coef { fill: var(--coef) }
.chart .dot.ref { fill: var(--ref) } .chart .dot.paper { fill: var(--paper) }
.chart .end.frame { fill: var(--frame) } .chart .end.coef { fill: var(--coef) } .chart .end.ref { fill: var(--ref) }
table { border-collapse: collapse; width: 100%; font-size: .92rem; font-variant-numeric: tabular-nums }
th, td { text-align: left; padding: 9px 12px; border-bottom: 1px solid var(--rule); vertical-align: top }
th { font-family: var(--display); font-weight: 600; font-size: .86rem; letter-spacing: .02em; color: var(--muted); vertical-align: bottom }
.name { white-space: nowrap }
tbody tr:last-child td { border-bottom: 0 }
.num { text-align: right; white-space: nowrap }
td.num { font-family: var(--data); font-size: .86rem }
.key { display: inline-block; width: 10px; height: 10px; margin-right: 8px; border-radius: 50% }
.key.frame { background: var(--frame) } .key.coef { background: var(--coef) } .key.ref { background: var(--ref) } .key.paper { background: var(--paper) }
.designs { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 18px }
.designs figure img { display: block; width: 100%; aspect-ratio: 2174 / 1050; border: 1px solid var(--rule) }
code { font-family: var(--data); font-size: .84em; overflow-wrap: anywhere }
a { color: var(--frame) }
@media (max-width: 520px) { h1 { font-size: 1.8rem } main { padding-block: 24px 48px; gap: 36px } }
"""


def render(data):
    finalists = data["finalists"]
    by_key = {finalist["key"]: finalist for finalist in finalists}
    frame, coef, reference = by_key["frame-128x2-lr1e-3"], by_key["coef-128x4-lr3e-4"], by_key["reference"]
    name = lambda finalist: f'<span class="name"><span class="key {NAMES[finalist["key"]][1]}"></span>{NAMES[finalist["key"]][0]}</span>'
    best = lambda finalist: finalist["improvements"][-1][1]
    paper_at = dict(MANUSCRIPT["curve_84"])
    paper_end, (band_low, band_high) = paper_at[100], MANUSCRIPT["band_84"]
    spread = (band_high - band_low) / 2
    values, checks = data["convergence"]["values"], data["convergence"]["checks"]
    orders = lambda pair: f"({pair[0]}, {pair[1]})"
    common = [order for order in LADDER if all(order in values[f["key"]] for f in finalists)]
    checked, highest = (18, 14), common[-1]   # the top of the campaign's own check, and of every order all three were evaluated at
    again = lambda finalist, order, quantity="mean": values[finalist["key"]][order][quantity]
    above = [order for order in common if LADDER.index(order) >= LADDER.index(SEARCHED)]
    te_drop = [100 * (again(f, SEARCHED, "te") - again(f, highest, "te")) for f in finalists]
    tm_range = max(100 * (max(again(f, order, "tm") for order in above) - min(again(f, order, "tm") for order in above)) for f in finalists)
    spread_at = lambda order: 100 * (max(again(f, order) for f in finalists) - min(again(f, order) for f in finalists))
    leader = lambda order: max(finalists, key=lambda f: again(f, order))
    es = values["es"]
    es_label = '<span class="name">Evolution strategy</span><br><span class="small">another campaign, searched at (10, 5)</span>'
    cell = lambda entry: "–" if entry is None else f'{percent(entry["mean"])}<br><span class="small">{100 * entry["te"]:.1f} / {100 * entry["tm"]:.1f}</span>'
    ladder = table(["Design", *(orders(order) + ("<br>searched" if order == SEARCHED else "") for order in LADDER)], [
        *([name(f), *(cell(values[f["key"]].get(order)) for order in LADDER)] for f in (frame, coef, reference)),
        [es_label, *(cell(es.get(order)) for order in LADDER)]],
        numeric=range(1, len(LADDER) + 1), compact=True)
    verdicts = {"converged": "passes", "unconverged": "fails"}
    whose = {"frame-128x2-lr1e-3": "the frame-token transformer's", "coef-128x4-lr3e-4": "the coefficient-token transformer's", "reference": "the reference CNN's"}
    # Orders raised in one direction at a time, and in y alone with x at 14.
    ys = (12, 16, 22, 26, 30, 36)
    in_y = table(["Design", *(orders((14, y)) for y in ys)], [
        *([name(f), *(cell(values[f["key"]].get((14, y))) for y in ys)] for f in (frame, coef, reference)),
        [es_label, *(cell(es.get((14, y))) for y in ys)]], numeric=range(1, len(ys) + 1), compact=True)
    high = lambda finalist: [100 * entry["mean"] for order, entry in values[finalist["key"]].items() if min(order) >= 14]
    last_step = lambda finalist: 100 * (again(finalist, (14, 30)) - again(finalist, (14, 36)))
    difference = lambda finalist: 100 * checks[finalist["key"]]["last_two_absolute_differences"]["mean_plus1_transmission"]

    results = table(["Policy", "Best at 3 h", "at 6 h", "at 12 h", "TE", "TM", f"Same design<br>at {orders(checked)}", f"at {orders(highest)}",
                     "Designs<br>evaluated", "Last new best"], [
        [name(f), *(percent(f["by_hour"][hours]["best"]) for hours in ("3", "6", "12")),
         percent(f["best"]["objectives"]["te_plus1_transmission"]), percent(f["best"]["objectives"]["tm_plus1_transmission"]),
         percent(again(f, checked)), percent(again(f, highest)),
         f"{f['evaluations']:,}", f"{clock(f['best']['hours'])}<br>design {f['best']['evaluation']:,}"] for f in finalists], numeric=range(1, 10), compact=True)
    matched = table(["Designs evaluated", '<span class="name"><span class="key paper"></span>Manuscript CNN</span><br>mean of 3 seeds', *(name(f) for f in (reference, frame, coef))], [
        [f"{count:,}", f"about {paper_at[count // 1000]:.1f}%", *(percent(f["best_at"][str(count)]) for f in (reference, frame, coef))]
        for count in CHECKPOINTS] + [["End of run", f"best design {MANUSCRIPT['best_84']}%<br>in {MANUSCRIPT['samples']:,}",
                                      *(f"{percent(best(f))}<br>at {f['evaluations']:,}" for f in (reference, frame, coef))]], numeric=range(1, 5))
    reported = table(["Method and mode limits", "Best design", "Average of the runs' best", "Spread drawn"], [
        [label, f"{top}%", f"about {average}%", f"{low} to {high}%"] for label, top, average, low, high in MANUSCRIPT["bars"]], numeric=range(1, 4))
    setup = table(["", "Manuscript", "This campaign"], [
        ["Problem", "1050 nm, 75°, TE and TM, 325 nm Si on silica, 256 × 128 cells, Px = λ / sin θ, Py = λ / 2", "The same"],
        ["Search space", "Fourier level set, mode limits (2, 1) to (8, 4)", "Mode limits (8, 4) only: 85 real coefficients"],
        ["Policy input", "Current coefficients and three past steps", "The same (four stacked frames)"],
        ["Samples per run", "500,000 (Fig. 3a shows the first 100,000)", f"{min(f['evaluations'] for f in finalists):,} to {max(f['evaluations'] for f in finalists):,}"],
        ["Seeds", "Three", "One"],
        ["Environments", "Several workers sharing one policy (four, per the campaign charter)", "One"],
        ["PPO", "Stable-Baselines3", "The campaign's own PyTorch rollout loop with the released CNN and settings: learning rate 3e-3, "
                                      "γ 0.9, GAE 0.95, clip 0.4, three epochs, 128-step episodes, action scaling 0.01"],
        ["Solver", "MEENT (0.9.5 in the released code)", "MEENT 0.13.2, private GPU build, complex128"],
        ["RCWA orders", "(10, 5) in the released code", "(10, 8)"],
        ["Silicon index", "Wavelength-dependent; 3.5674 at 1050 nm in the released code, absorption ignored", "3.5674, from the released table"],
    ])
    ranking = data["screen"]["ranking"]
    screen = table(["Policy", "Seed 0", "Seed 1", "Mean", ""], [
        [html.escape(row["title"]), *(percent(value) for value in row["bests"]), percent(row["mean_best"]),
         "run long" if row["key"] in data["screen"]["finalists"] else ""]
        for row in sorted(ranking, key=lambda row: row["mean_best"], reverse=True)], numeric=range(1, 4))
    spread_screen = max(abs(row["bests"][0] - row["bests"][1]) for row in ranking)
    range_screen = max(row["mean_best"] for row in ranking) - min(row["mean_best"] for row in ranking)
    designs = "".join(
        f'<figure><img alt="Best design of the {NAMES[f["key"]][0].lower()}: silicon pattern, two periods in each direction" src="{mask_image(f["best"]["mask"])}">'
        f'<figcaption><b>{name(f)}</b><br>{percent(best(f))} mean · TE {percent(f["best"]["objectives"]["te_plus1_transmission"])} · '
        f'TM {percent(f["best"]["objectives"]["tm_plus1_transmission"])}<br>{percent(f["best"]["silicon_fraction"], 0)} silicon · '
        f'design {f["best"]["evaluation"]:,}</figcaption></figure>' for f in finalists)
    records = table(["Policy", "Experiment", "Designs", "Hours", "Solves per design", "Source"], [
        [name(f) if index == 0 else "", f'<code>{part["trial_id"]}</code>', f'{part["evaluations"]:,}', f'{part["seconds"] / 3600:.2f}',
         f'{part["solver_calls"] / part["evaluations"]:.2f}', f'<code>{part["source"]}</code>']
        for f in finalists for index, part in enumerate(f["parts"])], numeric=(2, 3, 4))
    rates = [part["evaluations"] / part["seconds"] for f in finalists for part in f["parts"]]
    gap = 100 * (best(frame) - best(reference))
    behind = paper_end - 100 * reference["best_at"]["100000"]

    return f"""<title>FLRL Transformer Policies</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Sans+Condensed:wght@500;600&display=swap">
<style>{STYLE}</style>
<main>
<header>
  <div class="kicker">Experiment report · 11 to 13 October 2026</div>
  <h1>Transformer policies for Fourier level-set reinforcement learning</h1>
  <p class="lede">Three PPO policies searched for a 2D dual-polarization beam deflector for twelve hours each. This report gives
  what they found, shows that those scores fall when the solver keeps more diffraction orders, and sets the results beside those
  reported in the FLRL manuscript.</p>
  <div class="spec"><span><b>λ</b> 1050 nm</span><span><b>θ</b> 75°</span><span><b>pol.</b> TE + TM</span>
  <span><b>Px × Py</b> 1087.04 × 525 nm</span><span><b>Si</b> 325 nm on silica</span><span><b>grid</b> 256 × 128</span>
  <span><b>(Nx, Ny)</b> (8, 4)</span><span><b>score</b> (TE + TM) / 2 into the +1 order</span></div>
</header>

<section>
  <h2>Findings</h2>
  <ul>
    <li><b>The scores hold only at the solver orders the searches used.</b> Every search evaluated its designs at RCWA orders
    {orders(SEARCHED)}. Evaluated again at {orders(checked)}, the best designs of the frame-token, coefficient-token and reference
    policies score {percent(again(frame, checked))}, {percent(again(coef, checked))} and {percent(again(reference, checked))}, against
    {percent(best(frame))}, {percent(best(coef))} and {percent(best(reference))}. At {orders(highest)} they score
    {percent(again(frame, highest))}, {percent(again(coef, highest))} and {percent(again(reference, highest))}. TM stays within
    {tm_range:.1f} points; TE falls by {min(te_drop):.0f} to {max(te_drop):.0f} points. No order tried is shown to be converged, so the
    true efficiency of these designs is not known.</li>
    <li><b>At the searched orders the frame-token transformer found the best design, {percent(best(frame))}</b>
    (TE {percent(frame["best"]["objectives"]["te_plus1_transmission"])}, TM {percent(frame["best"]["objectives"]["tm_plus1_transmission"])})
    after {frame["best"]["evaluation"]:,} designs, ahead of the coefficient-token transformer ({percent(best(coef))}) and the reference CNN
    ({percent(best(reference))}), which is the manuscript's policy as implemented in this campaign. At {orders(highest)} the three designs
    lie within {spread_at(highest):.1f} points of each other and {whose[leader(highest)["key"]]} is highest: the {gap:.1f}-point lead
    does not survive. The reference CNN's design is also the only one whose score settles, between {min(high(reference)):.1f} and
    {max(high(reference)):.1f}% at every setting with 14 or more orders in each direction.</li>
    <li><b>Against the manuscript's curve, at the searched orders, the reference CNN is behind and the frame transformer is level.</b>
    At 100,000 designs the manuscript's Figure 3a shows about {paper_end:.1f}% for its CNN policy (mean of three seeds). Here the reference
    CNN was at {percent(reference["best_at"]["100000"])}, about {behind:.0f} points lower, and the frame transformer at
    {percent(frame["best_at"]["100000"])}. No run approached the manuscript's best design of {MANUSCRIPT["best_84"]}%, reported for 500,000
    samples; these runs ended near 115,000.</li>
    <li><b>None of the comparisons is established.</b> The scores depend on the solver orders, as above; each policy ran with one seed;
    the solver setup differs from the manuscript's; and the manuscript's own runs spread by about ±{spread:.0f} points at 100,000 samples.
    Whether the manuscript's designs hold at higher orders was not tested here: its released code evaluates at (10, 5).</li>
  </ul>
  {results}
  <p class="note">Efficiency is the fraction of incident power sent into the transmitted (+1, 0) order, averaged over TE and TM. The first
  five columns are at the searched orders {orders(SEARCHED)}; TE and TM are those of each policy's best design. One seed per policy.</p>
</section>

<section>
  <h2>The same designs at higher RCWA orders</h2>
  <p>RCWA keeps a finite number of diffraction orders in each direction. The searches kept {orders(SEARCHED)}. Below, each policy's best
  design is evaluated again by the same evaluator with more orders; nothing else changes.</p>
  <figure>{convergence_chart(values)}
  <figcaption>Solid lines: mean of TE and TM. Dashed lines: TE alone. TM is not drawn; it changes by at most {tm_range:.1f} points
  from {orders(SEARCHED)} upwards.</figcaption></figure>
  {ladder}
  <p class="note">Mean efficiency, with TE / TM beneath. For the three policies, {orders(SEARCHED)} to {orders(checked)} are the campaign's own
  convergence check; the other cells are direct calls of the same evaluator on 13 October and are not campaign records.</p>
  <ul>
    <li><b>TM holds and TE does not.</b> TE of the three designs falls from {percent(again(frame, SEARCHED, "te"), 1)}, {percent(again(coef, SEARCHED, "te"), 1)}
    and {percent(again(reference, SEARCHED, "te"), 1)} at {orders(SEARCHED)} to {percent(again(frame, highest, "te"), 1)},
    {percent(again(coef, highest, "te"), 1)} and {percent(again(reference, highest, "te"), 1)} at {orders(highest)}.</li>
    <li><b>The campaign's check fails two designs of three.</b> It compares the two highest orders it ran, (14, 12) and {orders(checked)},
    and allows half a point. The frame-token design differs by {difference(frame):.1f} points and {verdicts[checks[frame["key"]]["numerical_status"]]};
    the reference design by {difference(reference):.1f} and {verdicts[checks[reference["key"]]["numerical_status"]]}; the coefficient-token
    design by {difference(coef):.2f} and {verdicts[checks[coef["key"]]["numerical_status"]]}, having already fallen from
    {percent(again(coef, SEARCHED))} to {percent(again(coef, (12, 10)))} one step above the searched orders.</li>
    <li><b>The designs end close together, in another order.</b> They are {spread_at(SEARCHED):.1f} points apart at {orders(SEARCHED)},
    {spread_at(checked):.1f} at {orders(checked)} and {spread_at(highest):.1f} at {orders(highest)}, where {whose[leader(highest)["key"]]}
    is highest. The frame-token design keeps its score longest and then falls furthest.</li>
    <li><b>A search can gain from the truncation.</b> In a later campaign that searched at (10, 5), a plain evolution strategy over the same
    85 coefficients reached {percent(es[(10, 5)]["mean"])} within 15 minutes. That design scores {percent(es[SEARCHED]["mean"])} at
    {orders(SEARCHED)} and {percent(es[highest]["mean"])} at {orders(highest)} (last row of the table).</li>
    <li><b>What this does not show.</b> Two of the three designs are still changing at the highest orders tried and no second solver was
    used, so these are not the designs' true efficiencies. The manuscript's designs were not evaluated here.</li>
  </ul>
  <h3>Where the orders are needed</h3>
  <p>Raising only the x orders of the frame-token design from 10 to 26, with y held at 8, moves it from {percent(again(frame, (10, 8)))} to
  {percent(again(frame, (26, 8)))}. Raising only the y orders from 8 to 22, with x held at 10, moves it to {percent(again(frame, (10, 22)))}.
  The orders the searches were short of are those in y, the direction of the 525 nm period. The table raises y alone with x held at 14.</p>
  {in_y}
  <p class="note">Mean efficiency, with TE / TM beneath; direct calls of the evaluator. Holding x at 14 is itself a truncation: at 22 orders
  in y the frame-token design scores {percent(again(frame, (14, 22)))} with 14 orders in x and {percent(again(frame, (26, 22)))} with 26.</p>
  <ul>
    <li><b>The reference CNN's design has settled.</b> From (14, 26) to (14, 36) it moves by
    {abs(100 * (again(reference, (14, 26)) - again(reference, (14, 36)))):.2f} points, and over all {len(high(reference))} settings with 14 or more
    orders in each direction it stays between {min(high(reference)):.1f} and {max(high(reference)):.1f}%.</li>
    <li><b>The two transformer designs have not.</b> Between (14, 30) and (14, 36) the frame-token design still loses {last_step(frame):.1f} points
    and the coefficient-token design {last_step(coef):.1f}.</li>
    <li><b>Orders (10, 5) and (10, 8) are far from enough for TE on this problem.</b> A check that a later search could apply to its
    best designs is agreement between two settings that differ in the y orders, at 20 or more.</li>
  </ul>
</section>

<section>
  <h2>Comparison with the manuscript</h2>
  <figure>{progress_chart(finalists)}
  <figcaption>Best efficiency found so far against the number of designs evaluated, each at its own solver orders: {orders(SEARCHED)} here,
  (10, 5) in the manuscript's released code. The dashed curve is the manuscript's (8, 4) result from its Figure 3a, read from the drawn
  curve to about half a point; it ends at 100,000 samples because the figure does.</figcaption></figure>
  {matched}
  <p>The reference CNN kept pace with the manuscript's curve for the first 50,000 designs and was ahead of it early on. The difference
  comes afterwards: the manuscript's curve keeps rising to about {paper_end:.1f}% at 100,000 samples, while the reference here set its last
  best at {reference["best"]["evaluation"]:,} designs and stayed there. The manuscript's shaded band at 100,000 samples runs from about
  {band_low} to {band_high}%, so a single run ending at {percent(reference["best_at"]["100000"], 1)} sits just below one standard deviation
  under its mean.</p>
  <p>The frame-token transformer stayed within about four points of the manuscript's curve throughout. It ended at {percent(best(frame))}
  after {frame["evaluations"]:,} designs; the manuscript's curve stops at about {paper_end:.1f}% at 100,000.</p>
  <h3>What the manuscript reports for this problem</h3>
  {reported}
  <p class="note">From the manuscript's Figure 3b, over 500,000 samples per method. The best-design figures are printed on the bars; the
  averages and spreads are read from the drawing. The manuscript also draws the adjoint design of its reference [9] (Sell et al., Nano
  Letters 2017) at about {MANUSCRIPT["adjoint"]}%, and at 100,000 samples its curves for mode limits (6, 3), (4, 2) and (2, 1) stand at about
  {MANUSCRIPT["end_63"]}, {MANUSCRIPT["end_42"]} and {MANUSCRIPT["end_21"]}%. Only (8, 4) was run here.</p>
  <h3>How the two setups differ</h3>
  {setup}
  <p class="note">The manuscript column combines its main text with what the campaign charter records about the supplementary methods and
  the released code (jLabKAIST/flrl, commit 7838e71). The released training configuration itself uses 100,000 timesteps and one environment.</p>
</section>

<section>
  <h2>What was run</h2>
  <p>Eight policies were screened first: the reference CNN and seven transformer feature extractors that differ in what a token is
  (a Fourier coefficient, a past frame, or both), in size and in learning rate. Everything else was the reference method. Each ran twice
  for 1,024 designs.</p>
  {screen}
  <p class="note">Best efficiency within 1,024 designs. The reference and the two transformers with the highest mean went on to long runs.</p>
  <p>The screen could not separate the policies. Two seeds of the same policy differed by up to {100 * spread_screen:.0f} points, while the
  means of all eight lie within {100 * range_screen:.0f} points of each other; 1,024 designs is seven policy updates. The five transformer
  variants that were dropped have not been tested at length.</p>
  <p>The three finalists then ran for three hours, were extended by three hours, and by six more. Each extension continued the same
  policy and optimizer state. All three shared one RTX 5090, and each evaluated between {min(rates):.1f} and {max(rates):.1f} designs per
  second depending on the solver code in use.</p>
</section>

<section>
  <h2>How the searches behaved</h2>
  <figure>{sampling_chart(finalists)}
  <figcaption>Median efficiency of the designs each policy sampled, per half hour. This follows the policy itself; the best-so-far curve
  above only follows its luckiest draw.</figcaption></figure>
  <ul>
    <li><b>Reference CNN: saturated.</b> Its typical design has stayed between 71 and 74% since hour 6
    (last hour: {percent(reference["last_hour_median"], 1)}), and its {percent(best(reference))} is a single draw well above what it normally samples.</li>
    <li><b>Frame-token transformer: still the strongest policy at the end.</b> Its typical design in the last hour scored
    {percent(frame["last_hour_median"], 1)}, above the reference's best design ever. It set its last best at {clock(frame["best"]["hours"])}
    and was flat for the final 90 minutes.</li>
    <li><b>Coefficient-token transformer: unsettled.</b> It was still recovering from a collapse when the run ended, and found its best
    design {clock(coef["hours"] - coef["best"]["hours"])} before the end.</li>
    <li><b>Both transformers collapsed once.</b> Within about 500 designs the efficiency of what they sampled fell sharply. The frame
    transformer was back at its earlier level two hours later; the coefficient transformer was not yet back after three and a half.
    The cause was not investigated. The reference CNN never did this.</li>
  </ul>
</section>

<section>
  <h2>Best designs</h2>
  <div class="designs">{designs}</div>
  <p class="note">Silicon is dark. Each panel shows the unit cell twice in x (horizontal, the deflection direction) and twice in y.</p>
  <p>The figures under the designs are at the searched orders {orders(SEARCHED)}. There the frame transformer's design is the only one that
  raises TE above 80%; at {orders(highest)} its TE is {percent(again(frame, highest, "te"), 1)}. None of the designs has been evaluated with
  another solver.</p>
</section>

<section>
  <h2>Limits of this comparison</h2>
  <ul>
    <li><b>One seed per policy.</b> The ranking of the three policies could change with another seed.</li>
    <li><b>The scores are not converged in RCWA order.</b> See the section above. A search at fixed low orders can raise its score by
    fitting the truncation, and nothing in these runs guarded against it.</li>
    <li><b>The solver setup is not the manuscript's.</b> RCWA orders are (10, 8) here against (10, 5) in the released code, and the MEENT
    versions differ. No cross-version check is recorded, so the same structure may score differently in the two setups by an unknown amount.</li>
    <li><b>The reference is an adaptation, not a reproduction.</b> It uses one environment and the campaign's own PPO loop, and it ran for
    less than a quarter of the manuscript's samples.</li>
    <li><b>The solver code changed during the runs.</b> The first three hours (1.5 for the coefficient-token transformer) solved each design
    twice; later parts solve once. Recorded designs from before the change reproduce under the later code to within 3.6e-15, and later
    ones exactly. Because the parts ran at different speeds, everything here is compared by designs evaluated, not by time.</li>
    <li><b>This operating condition is the one the manuscript reports.</b> Nothing was held back as an untouched test.</li>
  </ul>
</section>

<section>
  <h2>Records</h2>
  {records}
  <p class="note">Convergence checks (recipe <code>meent_2d_order_convergence:v1</code>, orders {orders(SEARCHED)} to {orders(checked)}):
  {", ".join(f'<code>{checks[f["key"]]["validation_trial_id"]}</code> for the {NAMES[f["key"]][0].lower()}' for f in finalists)}.
  The wider sweep is in <code>convergence-study-20261013.json</code>. When both ran, the solver checkout had uncommitted changes
  ({", ".join(f"<code>{source}</code>" for source in data["convergence"]["sources"])}); every score recorded at {orders(SEARCHED)} was reproduced
  to within 1e-13.</p>
  <p class="note">Campaign <code>campaign_738bf861-d57f-4667-a797-669fc1bb101f</code>, "2D dual-polarization beam deflector — Octavian FLRL
  paper". Each policy's row lists its successive experiments; together they are one run. Summaries are in
  <code>runs/transformer-screen-20261012/journal/</code> (<code>screen-summary.json</code>, <code>finalist-summary.json</code>), and this page is
  written by <code>scripts/transformer_policy_report.py</code>. Manuscript:
  {html.escape(MANUSCRIPT["citation"], quote=False)}. Data read {data["extracted_at"]}.</p>
</section>
</main>
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--trial-files", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--refresh", action="store_true", help="read the journals again instead of reusing report-data.json")
    parser.add_argument("--page-body", type=Path, help="also write the page without its document wrapper")
    parser.add_argument("--manuscript", type=Path, help="what the manuscript reports; default: manuscript.json in the journal directory")
    arguments = parser.parse_args()
    reported = arguments.manuscript or arguments.journal / "manuscript.json"
    if not reported.is_file():
        parser.error(f"{reported} is missing: what the manuscript reports is kept outside the repository; give --manuscript")
    MANUSCRIPT.update(json.loads(reported.read_text()))
    arguments.output.mkdir(parents=True, exist_ok=True)
    cache = arguments.output / "report-data.json"
    if arguments.refresh or not cache.is_file():
        cache.write_text(json.dumps(extract(arguments.journal, arguments.trial_files)))
    page = render({**json.loads(cache.read_text()), "convergence": convergence(arguments.journal)})
    (arguments.output / "index.html").write_text(
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        + page.replace("<main>", "</head>\n<body>\n<main>", 1) + "</body>\n</html>\n")
    if arguments.page_body:
        arguments.page_body.write_text(page)
    print(arguments.output / "index.html")


if __name__ == "__main__":
    main()
