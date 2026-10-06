"""workflow_rehearsal_2026-10-06.xlsx - proven workflows, samples and runbook."""
import sys
from pathlib import Path

from openpyxl import Workbook

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from reconcile import _add_sheet  # noqa: E402

workflows = [
    {"workflow": "Customer invoice - plain (no VAT)", "sample": "INV/2026/00008 (22352)",
     "result": "posted; totals exact; entity tag [PRES]; formal text OK"},
    {"workflow": "Customer invoice - 5% VAT (regenerated)", "sample": "INV/2025/00001 (191)",
     "result": "posted; VAT 5,868.35 reproduced exactly; totals exact"},
    {"workflow": "Customer invoice - linked to a unit", "sample": "INV/2026/00691 (25058), INV/2025/00500 (25091)",
     "result": "posted; sold property = BR1-401 / BR1-212 (written after posting)"},
    {"workflow": "Document number collides across companies", "sample": "1,643 renamed copies, e.g. INV/2026/00025 [PINV]",
     "result": "unique names kept with ' [TAG]' suffix; posted"},
    {"workflow": "Supplier bill - plain / VAT / line section", "sample": "BILL/2025/09/0003 (147), section bill (897)",
     "result": "posted; totals exact"},
    {"workflow": "Supplier bill - foreign currency (USD)", "sample": "BILL/2026/07/0004 (32060)",
     "result": "posted in USD; totals exact"},
    {"workflow": "Journal entry - misc and bank types", "sample": "MISC/2025/10/0001 (3), TA/.. (9), IFRS/.. (11)",
     "result": "posted; names preserved"},
    {"workflow": "Payment - inbound, unit-linked", "sample": "PBNK16/2026/00001 (106)",
     "result": "posted in-process; unit on ledger entry; old name kept in memo"},
    {"workflow": "Payment - inbound, no unit", "sample": "PBNK8/2025/00001 (35)",
     "result": "posted; amount exact"},
    {"workflow": "Payment - outbound", "sample": "PCSH1/2025/00001 (3)",
     "result": "posted; amount exact"},
    {"workflow": "Entity classification on every entry", "sample": "all imported records",
     "result": "ref '[TAG] ...', narration 'Legacy Entity: ... (Pgre Company #n)', payments in memo"},
    {"workflow": "Formal text style everywhere", "sample": "all text fields",
     "result": "no ALL-CAPS; identifiers and acronyms preserved; verified on live imports"},
    {"workflow": "Excluded by design (flagged, not migrated)", "sample": "18 held PARK I N V unit records; 49 canceled payments; 1,560 lines of unexported moves; empty refund sets",
     "result": "excluded and listed for review"},
]

notes = [
    {"note": "One-off data defects expected to surface as flagged errors at full scale: "
             "1 unbalanced entry and 7 moves where the tax base differs from line subtotals by >2 fils. "
             "These are recorded per record, never imported silently."},
    {"note": "Transient issues (Cloudflare 502, concurrent-update conflicts) are auto-retried; "
             "any record left unposted is flagged, and a resume/salvage pass mops up leftovers."},
    {"note": "Property sale consideration carries 0 VAT (verified, AED 118.56M) - see tax_review_2026-10-06.xlsx."},
    {"note": "Recoded account/journal codes and fuzzy account mappings await your review - see creation_review_2026-10-06.xlsx."},
]

runbook = [
    {"step": "1", "action": "Trust the four company bank accounts on production (allow_out_payment=True)",
     "command": "same write as applied on the rehearsal"},
    {"step": "2", "action": "Create reference records on production (accounts, journals, partners, users)",
     "command": "python create_reference_records.py --db sgc_mt_parkgroup --apply --allow-prod --map-out creation_map_sgc_mt_parkgroup.json"},
    {"step": "3", "action": "Import all moves + payments (~10.7k moves / ~3.4k payments, est. 2.5-3 h)",
     "command": "python import_moves.py --db sgc_mt_parkgroup --allow-prod --creation creation_map_sgc_mt_parkgroup.json --apply --all --threads 2 --batch 40"},
    {"step": "4", "action": "Idempotent text normalization pass",
     "command": "python normalize_text.py --db sgc_mt_parkgroup --creation creation_map_sgc_mt_parkgroup.json"},
    {"step": "5", "action": "Verification (counts, per-account totals vs source, tags, units) + salvage pass",
     "command": "python verify_import.py sgc_mt_parkgroup"},
    {"step": "6", "action": "Rebuild reconciliation states, then final report", "command": "next workstream"},
]

wb = Workbook()
wb.remove(wb.active)
_add_sheet(wb, "Workflows_Proven", workflows)
_add_sheet(wb, "Notes", notes)
_add_sheet(wb, "Production_Runbook", runbook)
out = ROOT / "workflow_rehearsal_2026-10-06.xlsx"
wb.save(out)
print("->", out.name)
