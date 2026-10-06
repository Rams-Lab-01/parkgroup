"""Import pgre moves + payments into a target DB from migration_out CSVs.

Entity classification (user requirement): every created record carries its old
company/entity in machine-readable form -
  moves:  ref  = "[CODE] <orig ref>"          narration = "Legacy entity: NAME (pgre company #n)"
  payments: memo = "[CODE] <orig memo> | Legacy entity: NAME (pgre company #n)"
Unit link: old property_id -> target move.sold_property_id (all target units are sale);
payment unit refs -> same field on the payment's ledger move + memo text.
Taxes: 'recompute' (default) applies the move's single mapped tax to its product
lines and lets Odoo regenerate tax lines; 'raw' imports exported tax lines as-is.

Safety: dry-run by default. --apply writes. Refuses db without 'rehearsal' or
'test' in its name unless --allow-prod. Resume-safe via import_map_<db>.json.
"""
import argparse
import csv
import json
import re
import sys
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from sgc_target_read import load_creds, rpc  # noqa: E402

MOVE_DATASETS = ["invoices", "bills", "journal_entries",
                 "customer_refunds", "vendor_refunds", "receipts"]

COMPANY_TAGS = {1: "PHI", 2: "PGI", 3: "PRED", 4: "PBR", 5: "AIWA", 6: "PRES", 7: "PINV"}
COMPANY_NAMES = {
    1: "PARK HOMES INTERNATIONAL REAL ESTATE LLC",
    2: "PARK GROUP INVESTMENT LLC",
    3: "PARK REAL ESTATE DEVELOPMENT LLC OPC",
    4: "PBR REAL ESTATE DEVELOPMENT LLC OPC",
    5: "AIWA REAL ESTATE DEVELOPMENT LLC",
    6: "PARK RESIDENCY REAL ESTATE DEVELOPMENT LLC",
    7: "PARK I N V PROPERTIES LLC",
}


def oid(s):
    m = re.search(r"\((\d+)\)\s*$", str(s) or "")
    return int(m.group(1)) if m else None


SMALL_WORDS = {"a", "an", "and", "as", "at", "by", "for", "from", "in", "into",
               "of", "on", "or", "the", "to", "via", "vs", "per"}
KEEP_UPPER = {"AIWA", "VAT", "UAE", "EOI", "ACT", "GLAM", "PBR", "PGI", "PHI",
              "PRED", "PRES", "PINV", "FTA", "DLD", "GAC", "DWT", "NDA", "MOA",
              "OPC", "FMO", "UBL", "DEWA", "RERA", "PDC", "IFRS"}


def _formal_word(tok):
    core = re.sub(r"^[^A-Za-z0-9]+|[^A-Za-z0-9]+$", "", tok)
    if not core:
        return tok
    if re.fullmatch(r"[A-Za-z]", core):
        return tok
    if core.lower() in SMALL_WORDS:
        return tok.replace(core, core.lower())
    if any(c.isdigit() for c in core):
        return tok
    if any(c in core for c in "/\\@_"):
        return tok
    if core.upper() == core and core.upper() in KEEP_UPPER:
        return tok
    if core.upper() == core and not any(v in core.upper() for v in "AEIOU"):
        return tok
    if "." in core and core == core.lower():
        return tok
    return tok.replace(core, core[:1].upper() + core[1:].lower())


def formalize(text):
    """Standard formal writing style: no ALL-CAPS, no all-lowercase.
    Identifiers (codes, document numbers, emails, acronyms) are preserved;
    everything else is converted to standard title case."""
    if not text:
        return text
    text = re.sub(r"<[^<>]*>", " ", str(text))
    return " ".join(_formal_word(w) for w in text.split())


def clean(s):
    return "" if s in (None, "False", "") else str(s)


def fl(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


class Ctx:
    def __init__(self, args):
        self.args = args
        self.mapping = json.loads((ROOT / "target_mapping_2026-10-06.json").read_text(encoding="utf-8"))
        self.creation = json.loads((ROOT / args.creation).read_text(encoding="utf-8"))
        self.readiness = json.loads((ROOT / "readiness_2026-10-06.json").read_text(encoding="utf-8"))
        self.state_path = ROOT / (args.state or f"import_map_{args.db}.json")
        self.state = json.loads(self.state_path.read_text(encoding="utf-8")) if self.state_path.exists() else {}
        self.state.setdefault("maps", {})
        self.state.setdefault("verified", {})
        self.state.setdefault("errors", [])
        self.dry_errors = []
        self.lock = threading.Lock()
        self.creds = load_creds()
        self.rid = [1]

    def kw(self, model, method, args, kwargs=None, rid=None):
        try:
            return rpc(self.creds["ODOO_URL"], "object", "execute_kw",
                       [self.args.db, 2, self.creds["ODOO_API_KEY"], model, method, args, kwargs or {}],
                       rid or self.rid)
        except SystemExit as e:
            raise RuntimeError(str(e)) from None

    def res(self, kind, val):
        o = oid(val)
        if o is None:
            return None
        v = self.mapping.get(kind, {}).get(str(o))
        if isinstance(v, dict):
            v = v.get("new_id")
        if v:
            return int(v)
        v = self.creation["map"].get(kind, {}).get(str(o))
        return int(v) if isinstance(v, int) and v > 0 else None

    def unit(self, val):
        o = oid(val)
        if o is None:
            return None
        u = self.mapping.get("units", {}).get(str(o))
        return u.get("new_id") if isinstance(u, dict) else None

    def save(self):
        self.state_path.write_text(json.dumps(self.state, indent=1, ensure_ascii=False), encoding="utf-8")


def load_csv(name):
    p = ROOT / "migration_out" / f"{name}.csv"
    if not p.exists():
        return []
    with p.open(encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def payment_move_ids():
    ids = set()
    for p in load_csv("payments"):
        m = oid(p.get("move_id"))
        if m:
            ids.add(m)
    return ids


def dataset_move_type(ds):
    return {"invoices": "out_invoice", "bills": "in_invoice",
            "journal_entries": "entry", "customer_refunds": "out_refund",
            "vendor_refunds": "in_refund"}.get(ds)


def build_move(ctx, ds, r, lines):
    args = ctx.args
    old = int(r["old_id"])
    cid = oid(r["company_id"])
    if cid not in COMPANY_TAGS:
        return None, f"unknown company {r.get('company_id')}"
    tag, cname = COMPANY_TAGS[cid], COMPANY_NAMES[cid]
    journal = ctx.res("journals", r["journal_id"])
    if not journal:
        return None, f"journal unmapped: {r.get('journal_id')}"
    partner = ctx.res("partners", r.get("partner_id"))
    if clean(r.get("partner_id")) and not partner:
        return None, f"partner unmapped: {r.get('partner_id')}"
    currency = ctx.res("currencies", r.get("currency_id"))

    move_tax = None
    if args.tax_mode == "recompute":
        trefs = {oid(l["tax_line_id"]) for l in lines if l.get("display_type") == "tax"}
        trefs.discard(None)
        if len(trefs) > 1:
            return None, f"multiple tax refs on move: {sorted(trefs)}"
        if trefs:
            move_tax = ctx.res("taxes", f"t ({next(iter(trefs))})")
            if not move_tax:
                return None, f"tax unmapped: {next(iter(trefs))}"

    ref_orig = clean(r.get("ref"))
    orig_name = clean(r.get("name"))
    final_name = orig_name
    if orig_name and getattr(ctx, "name_counts", {}).get((journal, orig_name), 0) > 1:
        final_name = f"{orig_name} [{tag}]"
        if args.apply:
            ctx.state.setdefault("renamed", {}).setdefault(ds, {})[str(old)] = final_name
    narr = formalize(f"Legacy entity: {cname} (pgre company #{cid})")
    if clean(r.get("narration")):
        narr += "\n" + formalize(clean(r["narration"]))
    vals = {
        "move_type": r["move_type"],
        "journal_id": journal,
        "date": r["date"],
        "ref": f"[{tag}] {formalize(ref_orig)}".strip(),
        "narration": narr,
        "partner_id": partner or False,
    }
    if currency:
        vals["currency_id"] = currency
    if final_name:
        vals["name"] = final_name
    if clean(r.get("invoice_date")):
        vals["invoice_date"] = clean(r["invoice_date"])
    if clean(r.get("invoice_date_due")):
        vals["invoice_date_due"] = clean(r["invoice_date_due"])
    term = ctx.res("payment_terms", r.get("invoice_payment_term_id"))
    if term:
        vals["invoice_payment_term_id"] = term
    fpos = ctx.res("fiscal_positions", r.get("fiscal_position_id"))
    if fpos:
        vals["fiscal_position_id"] = fpos
    if clean(r.get("invoice_origin")):
        vals["invoice_origin"] = clean(r["invoice_origin"])
    unit = ctx.unit(r.get("property_id"))
    if unit:
        vals["_unit"] = unit  # written after posting (create-time value is dropped by post)
    if clean(r.get("property_id")) and not unit:
        return None, f"unit unresolved: {r.get('property_id')}"

    lines_vals = []
    for ln in lines:
        dt = clean(ln.get("display_type")) or "product"
        if dt == "tax" and args.tax_mode == "recompute":
            continue
        if dt == "line_section":
            lines_vals.append((0, 0, {"display_type": "line_section", "name": formalize(clean(ln.get("name"))) or "/"}))
            continue
        acc = ctx.res("accounts", ln["account_id"])
        if not acc:
            return None, f"account unmapped: {ln.get('account_id')} ({ln.get('name', '')[:20]})"
        lv = {"display_type": dt, "name": formalize(clean(ln.get("name"))) or "/", "account_id": acc}
        lp = ctx.res("partners", ln.get("partner_id"))
        if lp:
            lv["partner_id"] = lp
        if dt == "product" and vals["move_type"] in ("out_invoice", "in_invoice", "out_refund", "in_refund"):
            lv["quantity"] = fl(ln.get("quantity")) or 1.0
            lv["price_unit"] = fl(ln.get("price_unit"))
            if move_tax:
                lv["tax_ids"] = [(6, 0, [move_tax])]
            desc = formalize(clean(ln.get("name")))
            prod = clean(ln.get("product_id"))
            if prod and desc and prod.split("(")[0].strip().lower() not in desc.lower():
                lv["name"] = f"{desc} - {formalize(prod.split('(')[0].strip())}"
        else:
            lv["debit"] = fl(ln.get("debit"))
            lv["credit"] = fl(ln.get("credit"))
            if clean(ln.get("amount_currency")):
                lv["amount_currency"] = fl(ln["amount_currency"])
                lc = ctx.res("currencies", ln.get("currency_id"))
                if lc:
                    lv["currency_id"] = lc
            if clean(ln.get("date_maturity")):
                lv["date_maturity"] = clean(ln["date_maturity"])
        lines_vals.append((0, 0, lv))
    if not lines_vals:
        return None, "no importable lines"
    vals["line_ids"] = lines_vals
    return vals, None


def push_moves_batch(ctx, ds, batch, donemap, rid=None):
    payload = [{k: v for k, v in b.items() if not k.startswith("_")} for b in batch]
    try:
        ids = ctx.kw("account.move", "create", [payload], rid=rid)
    except Exception as e:  # noqa: BLE001
        if len(batch) > 1:
            for b in batch:
                push_moves_batch(ctx, ds, [b], donemap, rid)
        else:
            with ctx.lock:
                ctx.state["errors"].append({"dataset": ds, "old_id": batch[0]["_old"],
                                            "error": "create failed: " + str(e)[:350]})
        return
    if not isinstance(ids, list):
        ids = [ids]
    with ctx.lock:
        for b, mid in zip(batch, ids):
            donemap[str(b["_old"])] = mid
    posted = []
    try:
        ctx.kw("account.move", "action_post", [ids], rid=rid)
        posted = list(ids)
    except Exception:  # noqa: BLE001
        for mid in ids:
            try:
                ctx.kw("account.move", "action_post", [[mid]], rid=rid)
                posted.append(mid)
            except Exception as e1:  # noqa: BLE001
                with ctx.lock:
                    ctx.state["errors"].append({"dataset": ds, "new_id": mid,
                                                "flags": ["created but not posted: " + str(e1)[:250]]})
    if not posted:
        return
    back = {m["id"]: m for m in ctx.kw("account.move", "read", [posted],
                                       {"fields": ["name", "amount_total", "amount_tax", "state"]}, rid=rid)}
    with ctx.lock:
        for b, mid in zip(batch, ids):
            if mid not in back:
                continue
            m = back[mid]
            flags = []
            if m.get("state") != "posted":
                flags.append(f"state={m.get('state')}")
            if abs(fl(m.get("amount_total")) - b["_exp_total"]) > 0.02:
                flags.append(f"total {m.get('amount_total')} != {b['_exp_total']}")
            if abs(fl(m.get("amount_tax")) - b["_exp_tax"]) > 0.02:
                flags.append(f"tax {m.get('amount_tax')} != {b['_exp_tax']}")
            if b["_exp_name"] and m.get("name") != b["_exp_name"]:
                flags.append(f"name {m.get('name')} != {b['_exp_name']}")
            if flags:
                ctx.state["errors"].append({"dataset": ds, "old_id": b["_old"], "new_id": mid, "flags": flags})
            ctx.state["verified"].setdefault(ds, {})[str(b["_old"])] = flags or "ok"
    unit_writes = defaultdict(list)
    for b, mid in zip(batch, ids):
        if b.get("_unit") and mid in back:
            unit_writes[b["_unit"]].append(mid)
    for unit, move_ids in unit_writes.items():
        try:
            ctx.kw("account.move", "write", [move_ids, {"sold_property_id": unit}], rid=rid)
        except Exception as e:  # noqa: BLE001
            with ctx.lock:
                ctx.state["errors"].append({"dataset": ds, "unit_write": unit, "error": str(e)[:200]})


def import_moves(ctx, ds):
    args = ctx.args
    rows = load_csv(ds)
    if not rows:
        print(f"[{ds}] no rows, skipped")
        return
    if not hasattr(ctx, "name_counts"):
        pm_all = payment_move_ids()
        ctx.name_counts = Counter()
        for _ds in MOVE_DATASETS:
            s2 = {int(k) for k in ctx.readiness["skip"].get(_ds, {})}
            h2 = {int(k) for k in ctx.readiness["hold"].get(_ds, {})}
            for r2 in load_csv(_ds):
                o2 = int(r2["old_id"])
                if o2 in s2 or o2 in h2 or (_ds == "journal_entries" and o2 in pm_all):
                    continue
                nm2 = clean(r2.get("name"))
                if nm2:
                    ctx.name_counts[(ctx.res("journals", r2["journal_id"]), nm2)] += 1
        dup = sum(1 for v in ctx.name_counts.values() if v > 1)
        print(f"[names] {dup} move names collide across companies; copies get ' [TAG]' suffix")
    skip = {int(k): v for k, v in ctx.readiness["skip"].get(ds, {}).items()}
    hold = {int(k): v for k, v in ctx.readiness["hold"].get(ds, {}).items()}
    lines_by_move = defaultdict(list)
    for ln in load_csv("move_lines"):
        m = oid(ln["move_id"])
        if m:
            lines_by_move[m].append(ln)
    skip_lines = {int(k) for k in ctx.readiness["skip"].get("move_lines", {})}
    donemap = ctx.state["maps"].setdefault(ds, {})
    paymoves = payment_move_ids()
    todo = [r for r in rows
            if int(r["old_id"]) not in skip
            and int(r["old_id"]) not in hold
            and int(r["old_id"]) not in paymoves
            and str(r["old_id"]) not in donemap]
    counts = Counter()
    built = []
    for r in todo:
        old = int(r["old_id"])
        if args.old_ids and old not in args.old_ids:
            continue
        lns = [l for l in lines_by_move.get(old, [])
               if int(l["old_id"]) not in skip_lines]
        vals, err = build_move(ctx, ds, r, lns)
        if err:
            counts["held"] += 1
            e = {"dataset": ds, "old_id": old, "error": err}
            if args.apply:
                ctx.state["errors"].append(e)
            else:
                ctx.dry_errors.append(e)
            continue
        vals["_old"] = old
        vals["_exp_total"] = fl(r.get("amount_total"))
        vals["_exp_tax"] = fl(r.get("amount_tax"))
        vals["_exp_name"] = vals.get("name", "")
        built.append(vals)
        if args.limit and len(built) >= args.limit:
            break
    print(f"[{ds}] total rows {len(rows)} | skip {len(skip)} hold {len(hold)} "
          f"payment-moves {len([r for r in rows if int(r['old_id']) in paymoves])} already {len(donemap)}")
    print(f"[{ds}] to import now: {len(built)} | build errors: {counts['held']}")
    if not args.apply:
        agg = Counter(re.sub(r"\(.*?\)|\d+", "#", e["error"]) for e in ctx.dry_errors)
        for k, v in agg.most_common(12):
            print(f"   {v:6d}  {k[:110]}")
        return
    batch_size = args.batch
    batches = [built[i:i + batch_size] for i in range(0, len(built), batch_size)]
    if args.threads > 1 and len(batches) > 1:
        chunks = [batches[i::args.threads] for i in range(args.threads)]

        def worker(my_batches):
            rid = [0]
            for bt in my_batches:
                try:
                    push_moves_batch(ctx, ds, bt, donemap, rid)
                except Exception as e:  # noqa: BLE001
                    with ctx.lock:
                        ctx.state["errors"].append({"dataset": ds, "batch_start": bt[0]["_old"],
                                                    "error": "worker crash: " + str(e)[:300]})
                with ctx.lock:
                    ctx.save()
                print(f"[{ds}] {len(donemap)}/{len(built)} imported", flush=True)

        threads = [threading.Thread(target=worker, args=(c,)) for c in chunks if c]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    else:
        for bt in batches:
            push_moves_batch(ctx, ds, bt, donemap)
            ctx.save()
            print(f"[{ds}] {len(donemap)}/{len(built)} imported", flush=True)
    print(f"[{ds}] done. errors so far: {len(ctx.state['errors'])}")


def push_payments_batch(ctx, batch, donemap, rid=None):
    payload = [{k: x for k, x in v.items() if not k.startswith("_")} for _o, v, _u, _c in batch]
    try:
        ids = ctx.kw("account.payment", "create", [payload], rid=rid)
    except Exception as e:  # noqa: BLE001
        if len(batch) > 1:
            for one in batch:
                push_payments_batch(ctx, [one], donemap, rid)
        else:
            with ctx.lock:
                ctx.state["errors"].append({"dataset": "payments", "old_id": batch[0][0],
                                            "error": "create failed: " + str(e)[:350]})
        return
    if not isinstance(ids, list):
        ids = [ids]
    with ctx.lock:
        for (old, _v, _u, _c), pid in zip(batch, ids):
            donemap[str(old)] = pid
    posted = []
    try:
        ctx.kw("account.payment", "action_post", [ids], rid=rid)
        posted = list(ids)
    except Exception:  # noqa: BLE001
        for pid in ids:
            try:
                ctx.kw("account.payment", "action_post", [[pid]], rid=rid)
                posted.append(pid)
            except Exception as e1:  # noqa: BLE001
                with ctx.lock:
                    ctx.state["errors"].append({"dataset": "payments", "new_id": pid,
                                                "flags": ["created but not posted: " + str(e1)[:250]]})
    if not posted:
        return
    back = {m["id"]: m for m in ctx.kw("account.payment", "read", [posted],
                                       {"fields": ["name", "amount", "state", "memo", "move_id"]}, rid=rid)}
    unit_writes = defaultdict(list)
    with ctx.lock:
        for (old, v, unit, _c), pid in zip(batch, ids):
            m = back.get(pid)
            if not m:
                continue
            flags = []
            if m.get("state") not in ("paid", "in_process", "posted"):
                flags.append(f"state={m.get('state')}")
            if abs(fl(m.get("amount")) - v["amount"]) > 0.02:
                flags.append(f"amount {m.get('amount')} != {v['amount']}")
            if v.get("_old_name") and f"Old Name: {v['_old_name']}" not in (m.get("memo") or ""):
                flags.append(f"old name missing in memo ({m.get('name')})")
            if flags:
                ctx.state["errors"].append({"dataset": "payments", "old_id": old, "new_id": pid, "flags": flags})
            ctx.state["verified"].setdefault("payments", {})[str(old)] = flags or "ok"
            if unit and m.get("move_id"):
                unit_writes[unit].append(m["move_id"][0])
    for unit, move_ids in unit_writes.items():
        try:
            ctx.kw("account.move", "write", [move_ids, {"sold_property_id": unit}], rid=rid)
        except Exception as e:  # noqa: BLE001
            with ctx.lock:
                ctx.state["errors"].append({"dataset": "payments", "unit_write": unit, "error": str(e)[:200]})


def import_payments(ctx):
    args = ctx.args
    rows = load_csv("payments")
    if not rows:
        return
    skip = {int(k) for k in ctx.readiness["skip"].get("payments", {})}
    hold = {int(k) for k in ctx.readiness["hold"].get("payments", {})}
    void = {int(r["old_id"]) for r in rows if r.get("state") == "canceled"}
    donemap = ctx.state["maps"].setdefault("payments", {})
    mlines = ctx.kw("account.payment.method.line", "search_read", [[]],
                    {"fields": ["id", "journal_id", "payment_type"]})
    method = {(r["journal_id"][0], r["payment_type"]): r["id"] for r in mlines}
    todo = [r for r in rows if int(r["old_id"]) not in skip and int(r["old_id"]) not in hold
            and int(r["old_id"]) not in void and str(r["old_id"]) not in donemap]
    if args.old_ids:
        todo = [r for r in todo if int(r["old_id"]) in args.old_ids]
    print(f"[payments] total {len(rows)} | skip {len(skip)} hold {len(hold)} canceled-void {len(void)} already {len(donemap)} | to import: {len(todo)}")
    if not args.apply:
        return
    ctx.state.setdefault("void", {})["payments_canceled"] = sorted(void)
    built = []
    for r in todo:
        old = int(r["old_id"])
        cid = oid(r["company_id"])
        if cid not in COMPANY_TAGS:
            ctx.state["errors"].append({"dataset": "payments", "old_id": old, "error": f"company {r.get('company_id')}"})
            continue
        tag, cname = COMPANY_TAGS[cid], COMPANY_NAMES[cid]
        journal = ctx.res("journals", r["journal_id"])
        partner = ctx.res("partners", r.get("partner_id"))
        currency = ctx.res("currencies", r.get("currency_id"))
        if not journal or not partner:
            ctx.state["errors"].append({"dataset": "payments", "old_id": old,
                                        "error": f"journal {journal} partner {partner} unmapped"})
            continue
        ptype = clean(r.get("payment_type"))
        mline = method.get((journal, ptype))
        if not mline:
            ctx.state["errors"].append({"dataset": "payments", "old_id": old, "error": f"no method line for journal {journal} {ptype}"})
            continue
        unit = ctx.unit(r.get("property_id"))
        memo = f"[{tag}] {clean(r.get('memo'))}".strip()
        if unit:
            u = ctx.mapping["units"][str(oid(r["property_id"]))]
            memo += f" | Unit {u.get('project')}-{u.get('unit')}"
        memo += f" | Legacy entity: {cname} (pgre company #{cid})"
        v = {"payment_type": ptype, "partner_type": clean(r.get("partner_type")),
             "partner_id": partner, "amount": fl(r.get("amount")), "journal_id": journal,
             "date": clean(r.get("date")), "memo": memo, "payment_method_line_id": mline}
        if currency:
            v["currency_id"] = currency
        if clean(r.get("name")):
            v["memo"] += f" | Old name: {clean(r['name'])}"
            v["_old_name"] = clean(r["name"])
        v["memo"] = formalize(v["memo"])
        built.append((old, v, unit, cid))
        if args.limit and len(built) >= args.limit:
            break
    batch_size = args.batch
    batches = [built[i:i + batch_size] for i in range(0, len(built), batch_size)]
    if args.threads > 1 and len(batches) > 1:
        chunks = [batches[i::args.threads] for i in range(args.threads)]

        def worker(my_batches):
            rid = [0]
            for bt in my_batches:
                try:
                    push_payments_batch(ctx, bt, donemap, rid)
                except Exception as e:  # noqa: BLE001
                    with ctx.lock:
                        ctx.state["errors"].append({"dataset": "payments", "batch_start": bt[0][0],
                                                    "error": "worker crash: " + str(e)[:300]})
                with ctx.lock:
                    ctx.save()
                print(f"[payments] {len(donemap)}/{len(built)} imported", flush=True)

        threads = [threading.Thread(target=worker, args=(c,)) for c in chunks if c]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    else:
        for bt in batches:
            push_payments_batch(ctx, bt, donemap)
            ctx.save()
            print(f"[payments] {len(donemap)}/{len(built)} imported", flush=True)
    print(f"[payments] done. errors so far: {len(ctx.state['errors'])}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="sgc_mt_rehearsal")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--allow-prod", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--batch", type=int, default=30)
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--tax-mode", choices=["recompute", "raw"], default="recompute")
    ap.add_argument("--old-ids", default="")
    ap.add_argument("--creation", default="creation_map_rehearsal.json")
    ap.add_argument("--state", default="", help="state file override (parallel runs)")
    ap.add_argument("--payments", action="store_true", help="include payments")
    ap.add_argument("--all", action="store_true", help="moves + payments")
    args = ap.parse_args()
    if args.old_ids:
        args.old_ids = {int(x) for x in args.old_ids.split(",") if x.strip()}
    if args.apply and "rehearsal" not in args.db and "test" not in args.db and not args.allow_prod:
        print(f"REFUSED: {args.db} is not a rehearsal/test db. Use --allow-prod to override.")
        return
    ctx = Ctx(args)
    datasets = [d.strip() for d in args.only.split(",") if d.strip()] or MOVE_DATASETS
    t0 = time.time()
    for ds in datasets:
        import_moves(ctx, ds)
    if args.payments or args.all or (args.old_ids and "payments" in args.only):
        import_payments(ctx)
    ctx.save()
    ok = sum(1 for ds in ctx.state["verified"].values() if isinstance(ds, dict)
             for v in ds.values() if v == "ok")
    print(f"elapsed {time.time() - t0:.0f}s | verified ok {ok} | errors {len(ctx.state['errors'])}")
    print(f"state: {ctx.state_path.name}")


if __name__ == "__main__":
    main()
