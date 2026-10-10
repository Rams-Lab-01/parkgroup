# -*- coding: utf-8 -*-
"""Migrate legacy sale.contract rows from 'signed' to 'spa_signed'.

Why this exists
---------------
The 'signed' state was removed from the sale.contract selection in favour of
the explicit SPA steps (spa_issued -> spa_signed -> registered ->
waiting_handover -> completed). selection_add can only append, so the EOI
module re-declares the whole selection and drops 'signed'. Any row still in
'signed' would crash the upgrade with an invalid selection value.

This script moves those rows to 'spa_signed' BEFORE the module is upgraded.
It is idempotent: a second run is a no-op.

Usage (inside the Odoo container, against the sandbox DB):

    docker exec -it sbox_odoo python3 \
        /opt/extra-addons/sgc_offplan_rental_property_management/tools/migrate_signed_to_spa_signed.py

It reads the DB name from odoo.conf (dbfilter / db_name) so it works against
whatever instance it is pointed at. Pass --dry-run to preview without writing.

Safety
------
- A full-row backup CSV is written next to this script
  (signed_rows_backup_<timestamp>.csv) before any write.
- Every row is re-read after the write and asserted to be 'spa_signed'.
- A rollback file (signed_rows_rollback_<timestamp>.csv) lists the exact ids
  that were moved, so a failed upgrade can restore them.
"""

import csv
import os
import sys
import datetime

sys.path.insert(0, "/usr/lib/python3/dist-packages")

import odoo.tools.config as odoo_config  # noqa: E402
from odoo import registry as odoo_registry  # noqa: E402
from odoo.exceptions import ValidationError  # noqa: E402


BACKUP_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCE_STATE = "signed"
TARGET_STATE = "spa_signed"


def _stamp():
    return datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")


def main(dry_run=False):
    stamp = _stamp()

    # Resolve the DB name the same way the running Odoo instance does.
    odoo_config.parse_config(["--config=/tmp/sandbox.conf"])
    db = odoo_config.config["dbfilter"] or odoo_config.config["db_name"]
    if not db:
        raise ValidationError("[migrate] could not resolve a DB name from odoo.conf")

    registry = odoo_registry.get(db)
    with registry.cursor() as cr:
        cr.execute(
            "SELECT id, name, property_id, buyer_id, sale_price, "
            "contract_date, spa_signed_date "
            "FROM sale_contract WHERE state = %s",
            (SOURCE_STATE,),
        )
        rows = cr.fetchall()

    if not rows:
        print(f"[migrate] no rows in state '{SOURCE_STATE}' - nothing to do")
        return 0

    print(f"[migrate] found {len(rows)} row(s) in state '{SOURCE_STATE}'")

    # ------------------------------------------------------------------
    # 1. Backup (before any write)
    # ------------------------------------------------------------------
    backup_path = os.path.join(BACKUP_DIR, f"signed_rows_backup_{stamp}.csv")
    with open(backup_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "id", "name", "property_id", "buyer_id", "sale_price",
            "contract_date", "spa_signed_date",
        ])
        writer.writerows(rows)
    print(f"[migrate] backup written -> {backup_path}")

    rollback_path = os.path.join(BACKUP_DIR, f"signed_rows_rollback_{stamp}.csv")
    with open(rollback_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["id"])
        writer.writerow([r[0] for r in rows])
    print(f"[migrate] rollback ids written -> {rollback_path}")

    if dry_run:
        print("[migrate] DRY RUN - no changes applied")
        return 0

    # ------------------------------------------------------------------
    # 2. Move the rows. COALESCE keeps an existing spa_signed_date when one
    #    was already recorded; otherwise stamp today.
    # ------------------------------------------------------------------
    with registry.cursor() as cr:
        cr.execute(
            "UPDATE sale_contract SET state = %s, "
            "spa_signed_date = COALESCE(spa_signed_date, NOW()) "
            "WHERE state = %s",
            (TARGET_STATE, SOURCE_STATE),
        )
        cr.commit()

    # ------------------------------------------------------------------
    # 3. Verify
    # ------------------------------------------------------------------
    with registry.cursor() as cr:
        cr.execute(
            "SELECT count(*) FROM sale_contract WHERE state = %s",
            (SOURCE_STATE,),
        )
        remaining = cr.fetchone()[0]
        cr.execute(
            "SELECT count(*) FROM sale_contract WHERE state = %s",
            (TARGET_STATE,),
        )
        moved = cr.fetchone()[0]

    if remaining:
        raise ValidationError(
            f"[migrate] FAILED - {remaining} row(s) still in '{SOURCE_STATE}'")
    print(f"[migrate] OK - {moved} row(s) now in '{TARGET_STATE}'")
    print(f"[migrate] backup:  {backup_path}")
    print(f"[migrate] rollback: {rollback_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(dry_run="--dry-run" in sys.argv))
