"""The monthly ExCom pack: every management report for one period in one
document, each report a chapter of its own (owner 2026-11-07).

The pack holds no figures of its own. It runs the reports it lists and lays
their sections end to end, so a number in the pack is always the number the
report itself would show for the same period and scope.
"""
from .reports import kpi

# (report key, the headline figure from it that leads the pack)
CHAPTERS = [
    ("performance", 3), ("pnl", 2), ("revenue", 2), ("cost", 0),
    ("manpower", 0), ("progress", 3), ("variations", 1), ("aging", 0),
    ("cashflow", 3), ("exceptions", 0),
]


def build(ctx):
    from .reports import reports
    regs = reports()
    kpis, sections, notes = [], [], []
    for key, lead in CHAPTERS:
        if key not in regs:
            continue
        rep = regs[key]
        out = rep.build(ctx)
        if out["kpis"]:
            k = out["kpis"][min(lead, len(out["kpis"]) - 1)]
            kpis.append(kpi(f"{k['label']}", k["value"], k["kind"],
                            sub=rep.title))
        for i, s in enumerate(out["sections"]):
            s = dict(s)
            s["chapter"] = rep.title if i == 0 else ""
            sections.append(s)
        notes += [f"{rep.title}: {n}" for n in out.get("notes", [])]
    return {"kpis": kpis, "sections": sections, "notes": notes}
