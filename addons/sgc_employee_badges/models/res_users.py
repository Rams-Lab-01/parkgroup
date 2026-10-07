from odoo import models


class ResUsers(models.Model):
    _inherit = 'res.users'

    def _rank_changed(self):
        super()._rank_changed()
        badge = self.env.ref('sgc_employee_badges.badge_rank_promotion', raise_if_not_found=False)
        if not badge:
            return
        for user in self:
            # skip the very first rank assignment (0 karma -> starting rank);
            # only real promotions deserve the badge
            if user.karma <= 0:
                continue
            self.env['gamification.badge.user'].sudo().create({
                'badge_id': badge.id,
                'user_id': user.id,
            })
