from odoo import _, api, fields, models

# Badges worth this many points or more (Platinum/Legendary) need HR
# confirmation before their karma is applied. Below this, the existing
# give-badge flow applies immediately and HR reconciles weekly instead.
PRE_APPROVAL_POINT_THRESHOLD = 100


class GamificationBadgeUser(models.Model):
    _inherit = 'gamification.badge.user'

    state = fields.Selection(
        [('draft', 'Pending Confirmation'), ('confirmed', 'Confirmed'), ('revoked', 'Revoked')],
        string='Status', default='confirmed', required=True, copy=False,
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            if record._is_auto_rule_badge():
                # calculated, not awarded manually -- always goes straight through
                record.state = 'confirmed'
                record._apply_karma()
            elif record.badge_id.point_value >= PRE_APPROVAL_POINT_THRESHOLD:
                record.state = 'draft'
            else:
                record.state = 'confirmed'
                record._apply_karma()
        return records

    def _is_auto_rule_badge(self):
        self.ensure_one()
        return bool(self.badge_id.challenge_ids)

    def _apply_karma(self):
        # a small number of badges (e.g. Revenue Generator's revenue-tier
        # ladder) are re-awarded repeatedly at escalating point values --
        # the triggering challenge passes the tier's points explicitly via
        # context rather than relying on the badge's flat point_value.
        override = self.env.context.get('karma_points_override')
        for record in self:
            points = override if override is not None else record.badge_id.point_value
            if points and record.user_id:
                record.user_id.sudo()._add_karma(
                    points,
                    reason=_('Badge: %s', record.badge_id.name),
                )

    def action_confirm(self):
        """HR confirms a pending high-value badge; karma is applied now."""
        for record in self:
            if record.state != 'draft':
                continue
            record.state = 'confirmed'
            record._apply_karma()

    def action_revoke(self):
        """HR revokes a badge (from the weekly reconcile, or a pending one
        that shouldn't have been given). Claws back any karma already
        applied; the negative karma.tracking entry is the durable audit
        trail, so the badge_user record itself is then removed."""
        for record in self:
            if record.state == 'confirmed' and record.badge_id.point_value and record.user_id:
                record.user_id.sudo()._add_karma(
                    -record.badge_id.point_value,
                    reason=_('Badge revoked: %s', record.badge_id.name),
                )
            record.state = 'revoked'
        self.unlink()
