from odoo import api, SUPERUSER_ID


def post_init_hook(env):
    """Ensure project_id / property_id on account.move are back-computed
    after install/upgrade."""
    cr = env.cr
    offset = 0
    batch = 200
    while True:
        cr.execute(
            """SELECT id FROM account_move
               WHERE (sold_id IS NOT NULL OR tenancy_id IS NOT NULL)
               ORDER BY id LIMIT %s OFFSET %s""",
            (batch, offset),
        )
        ids = [r[0] for r in cr.fetchall()]
        if not ids:
            break
        moves = env["account.move"].browse(ids)
        moves._compute_property_unit_links()
        env.cr.commit()
        offset += batch
