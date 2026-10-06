"""CLI over :mod:`fieldplan` - discover and report custom fields.

    python discover_custom_fields.py                # summary for the key models
    python discover_custom_fields.py --refresh      # ignore the cache, re-probe
    python discover_custom_fields.py --model account.move --show 100
    python discover_custom_fields.py --include-heavy

Writes ``field_plan.json``, which ``export_data.py`` and
``export_migration.py`` both consume so that custom fields are exported.
"""

from __future__ import annotations

import argparse

import fieldplan
from pgre_client import OdooClient, OdooError

MODELS = ("account.move", "account.move.line", "account.payment",
          "account.journal", "account.account", "res.partner", "res.company",
          "product.product", "product.template", "res.users")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", action="append", default=None,
                    help="Only this model (repeatable)")
    ap.add_argument("--json-out", default=str(fieldplan.PLAN_PATH))
    ap.add_argument("--show", type=int, default=30,
                    help="Custom fields printed per model (0 = none)")
    ap.add_argument("--include-heavy", action="store_true",
                    help="Also include one2many/many2many fields")
    ap.add_argument("--refresh", action="store_true",
                    help="Re-probe the database instead of using the cache")
    args = ap.parse_args()

    try:
        client = OdooClient()
    except OdooError as exc:
        print(f"Cannot connect: {exc}")
        return 1

    models = tuple(args.model) if args.model else MODELS
    plan = fieldplan.build_plan(client, models, include_heavy=args.include_heavy)
    fieldplan.save_plan(plan, args.json_out)

    about = client.about()
    print("=" * 78)
    print("CUSTOM FIELD DISCOVERY")
    print("=" * 78)
    print(f"  database   : {plan['database']}")
    print(f"  version    : {plan.get('server_version')}")
    print(f"  modules    : {plan['installed_modules']} installed, "
          f"{len(plan['non_core_modules'])} non-core")
    print()
    print(f"Non-core modules installed ({len(plan['non_core_modules'])}):")
    for m in plan["non_core_modules"]:
        print(f"  {m}")
    print()

    print("=" * 78)
    print("PER-MODEL FIELD PLAN")
    print("=" * 78)
    for model, entry in plan["models"].items():
        n_exp = len(entry.get("exportable") or [])
        n_cus = entry.get("custom_count", 0)
        print(f"{model:<26} {entry.get('total_fields', 0):>4} total  "
              f"{n_exp:>4} exportable  {n_cus:>3} custom")
        if not n_cus:
            continue
        if args.show:
            print(f"    {'field':<44}{'type':<11}{'defined by':<26}label")
            for c in entry["custom_fields"][:args.show]:
                print(f"    {c['name']:<44}{str(c['type']):<11}"
                      f"{str(c['module'])[:24]:<26}{str(c['label'])[:28]}")
            if n_cus > args.show:
                print(f"    ... and {n_cus - args.show} more")
    print()
    print(f"TOTAL custom fields: {plan['total_custom_fields']}")
    print(f"Field plan written to {args.json_out}")
    print()
    print("The exporters request every 'exportable' column, so custom fields are")
    print("included by construction. Classification is annotation only.")
    print()
    print("NOTE: a core field that a custom module merely extends (for example")
    print("      account.move.state via vendor_bill_customization) is reported as")
    print("      'custom'. Harmless - nothing is dropped based on this label.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())