"""20 seeded sections for spike S4. kind: title (title too long), body (items overflow), both."""
SOURCES = [
    ("S1", "workshop.vtt, 2026-08-28, transcript"),
    ("S2", "client-brief.pdf, Integrity programme scope, March 2026"),
    ("S3", "inspection-register.xlsx, export of 14 October 2026"),
]
def it(head, body, *cites):
    return {"head": head, "body": body, "citations": [{"key": k, "locator": l} for k, l in cites]}

LONG_ITEMS = [
    it("Inspection intervals", "were set in 2019 for all 14 offshore vessels and have never been revised, although the operating envelope changed twice since then", ("S1", "00:41")),
    it("Data quality", "the telemetry pipeline drops 12% of corrosion readings at Aberdeen and 7% at Esbjerg, mostly during the night shift handover", ("S2", "p.4")),
    it("Ownership", "no single team owns the inspection register; Asset Integrity and Operations both edit it, and 31 records disagree between the two copies", ("S3", "row 212")),
    it("Backlog", "1,240 work orders are open, of which 380 are older than 180 days and 46 are classed as safety critical by the 2024 standard", ("S3", "sheet 2")),
    it("Cost", "unplanned shutdowns cost an estimated EUR 4.2 million in 2025, against EUR 1.1 million in 2022", ("S2", "p.9")),
    it("Pilot", "Maria Jensen proposed a two-vessel pilot starting in January 2027 on the Nordic Star and the Baltic Wind", ("S1", "01:12")),
]
SHORT_ITEMS = [
    it("Intervals", "set in 2019, never revised", ("S1", "00:41")),
    it("Data", "12% of readings dropped", ("S2", "p.4")),
    it("Ownership", "31 records disagree", ("S3", "row 212")),
]
LONG_TITLES = [
    "Three integrity concerns that compound across the North Sea fleet and the onshore terminals",
    "Why the 2019 inspection intervals no longer match how the 14 vessels are actually operated today",
    "What a two-vessel pilot on the Nordic Star and the Baltic Wind would prove by the end of 2027",
    "How unplanned shutdowns grew from EUR 1.1 million in 2022 to an estimated EUR 4.2 million in 2025",
    "Where the inspection register breaks down between Asset Integrity, Operations and the contractors",
    "The backlog of 1,240 open work orders and the 46 safety critical items that need an owner this quarter",
    "Telemetry gaps at Aberdeen and Esbjerg and what they hide about corrosion on the oldest hulls",
    "A decision for the steering committee on 12 December 2026 about scope, budget and the pilot vessels",
    "From reactive repairs to planned inspection: the three changes Maria Jensen asked us to test first",
    "Before and after: what the programme measures in month one, month six and at the end of the pilot",
    "Risks we accept, risks we transfer to contractors, and the two risks only the board can decide on",
    "The case for a single owner of the inspection register, with the 31 conflicting records as evidence",
]
SHORT_TITLES = ["Three integrity concerns", "Inspection intervals", "The pilot", "Shutdown cost",
                "Register ownership", "The backlog", "Telemetry gaps", "Decision needed"]

def seeds():
    out = []
    for i in range(8):   # long title, body fits
        out.append(dict(id=f"t{i:02d}", kind="title", title=LONG_TITLES[i], items=SHORT_ITEMS))
    for i in range(8):   # body overflows, title fits
        rot = LONG_ITEMS[i % 6:] + LONG_ITEMS[:i % 6]
        out.append(dict(id=f"b{i:02d}", kind="body", title=SHORT_TITLES[i], items=rot[:5 + i % 2]))
    for i in range(4):   # both
        out.append(dict(id=f"x{i:02d}", kind="both", title=LONG_TITLES[8 + i], items=LONG_ITEMS[:6]))
    return out
