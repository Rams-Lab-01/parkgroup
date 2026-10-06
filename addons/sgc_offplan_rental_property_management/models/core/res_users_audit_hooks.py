"""res.users audit hooks (design §3.1, §3.2).

Privilege escalation -- membership changes to the audit-admin / rental-manager
/ rental-suite privilege groups -- is a governed Tier-1 operation: it is
rejected unless a Channel-1 reason-gated wrapper owns the path. Login and
password writes are auto-audited Tier 2. Password values are never read or
stored (they are declared as non-value field rows and redacted to null by the
service under the REDACTED_FULL default, P0-10).
"""

from odoo import api, models
from odoo.exceptions import ValidationError


def _get_service(env):
    # Late import keeps the hook import-safe while the services package is
    # loaded after models/core during module import (see models/__init__.py).
    from odoo.addons.sgc_offplan_rental_property_management.services import sgc_audit_internal_service
    return sgc_audit_internal_service.SgcAuditInternalService(env)


class ResUsersAuditHooks(models.Model):
    _inherit = 'res.users'

    # Candidate xmlids for the audit groups (exact id chosen in
    # security/critical_audit_groups.xml); a missing group means the security
    # XML is not loaded yet and the id is simply skipped.
    _audit_admin_group_xmlids = (
        'sgc_offplan_rental_property_management.group_sgc_audit_admin',
        'sgc_offplan_rental_property_management.sgc_audit_admin_group',
    )
    _audit_viewer_group_xmlids = (
        'sgc_offplan_rental_property_management.group_sgc_audit_viewer',
        'sgc_offplan_rental_property_management.sgc_audit_viewer_group',
    )
    # Group technical names that define rental-suite privilege escalation.
    _audit_protected_group_names = (
        'property_rental_manager',
        'res_groups_privilege_rental_suite',
    )
    _audit_touched_fields = frozenset({'password', 'login'})

    @classmethod
    def _audit_groups_field(cls, env):
        """The res.users groups field name for this Odoo version.

        Odoo 19 renamed ``groups_id`` to ``group_ids`` and removed the old
        name.  These hooks keyed on the removed name, so group grants were
        neither gated nor captured (defect found 2026-09-20 while fixing the
        Registry cache crash).  Resolve at runtime so both versions work.
        """
        return 'group_ids' if 'group_ids' in env['res.users']._fields else 'groups_id'

    @classmethod
    def _audit_protected_group_ids(cls, env):
        """Resolve protected res.groups ids, cached per registry."""
        if not hasattr(cls, '_audit_cache'):
            cls._audit_cache = {}
        # Odoo builds model classes per registry, so this class attribute is
        # already per-registry and a single slot is sufficient.  Keying by
        # ``env.registry`` raised TypeError: unhashable type: 'Registry' on
        # every user create carrying groups_id (defect found by the F7
        # concurrency setup, 2026-09-20: user creation was broken).
        entry = cls._audit_cache.get('ids')
        if entry is not None:
            return entry
        ids = set()
        for xmlid in (cls._audit_admin_group_xmlids + cls._audit_viewer_group_xmlids):
            try:
                ids.add(env.ref(xmlid).id)
            except ValueError:
                pass  # security XML not loaded yet
        for rec in env['ir.model.data'].search([
                ('model', '=', 'res.groups'),
                ('module', '=', 'sgc_offplan_rental_property_management'),
                ('name', 'in', list(cls._audit_protected_group_names))]):
            ids.add(rec.res_id)
        # The class is per registry, which is process-lifetime; so is the cache.
        cls._audit_cache['ids'] = ids
        return ids

    def _audit_groups_from_vals(self, vals):
        """Extract the resulting res.groups ids from the groups vals entry."""
        cmds = vals.get(self._audit_groups_field(self.env))
        if cmds is False or cmds is None:
            return set()
        if isinstance(cmds, models.BaseModel):
            return set(cmds.ids)
        if isinstance(cmds, int):
            return {cmds}
        if not isinstance(cmds, (tuple, list)):
            return set()
        if cmds and not isinstance(cmds[0], (tuple, list)):
            # Already a plain id list.
            return set(int(x) for x in cmds)
        ids = set()
        for cmd in cmds:
            if cmd[0] == 6:
                ids.update(cmd[2] or [])
            elif cmd[0] in (1, 4):
                ids.add(cmd[1])
        return ids

    def _audit_has_escalation(self, vals, current_ids=None):
        """True when the groups write grants a protected privilege group."""
        granted = self._audit_groups_from_vals(vals)
        if current_ids is not None:
            granted -= set(current_ids)
        return bool(granted & self._audit_protected_group_ids(self.env))

    @api.model_create_multi
    def create(self, vals_list):
        service = _get_service(self.env)
        # The event model not being registered yet means the addon is not
        # installed: the hooks are inert until then.
        groups_field = self._audit_groups_field(self.env)
        if ('sgc.critical.audit.event' in self.env.registry.models
                and not service.guard_active(self._name, None)):
            for vals in vals_list:
                if groups_field in vals and self._audit_has_escalation(vals):
                    raise ValidationError(
                        'Granting a rental-suite privilege group on user '
                        'creation is Tier-1 audited and requires an operator '
                        'reason. Use the reason-gated workflow.')
        return super().create(vals_list)

    def write(self, vals):
        service = _get_service(self.env)
        groups_field = self._audit_groups_field(self.env)
        if ('sgc.critical.audit.event' not in self.env.registry.models
                or not (self._audit_touched_fields.intersection(vals)
                        or groups_field in vals)):
            return super().write(vals)
        for rec in self:
            if service.guard_active(rec._name, rec.id):
                continue  # Channel-1 wrapper owns the whole path
            if (groups_field in vals
                    and self._audit_has_escalation(vals, current_ids=rec[groups_field].ids)):
                raise ValidationError(
                    'Granting a rental-suite privilege group is Tier-1 audited '
                    'and requires an operator reason. Use the reason-gated '
                    'workflow for %s #%s.' % (rec._name, rec.id))
        result = super().write(vals)
        for rec in self:
            if service.guard_active(rec._name, rec.id):
                continue
            changes = []
            if 'login' in vals:
                changes.append({'field_name': 'login',
                                'old_value': None, 'new_value': None})
            if 'password' in vals:
                # The password hash is never read; the row proves a change.
                changes.append({'field_name': 'password',
                                'old_value': None, 'new_value': None})
            if changes:
                service.capture_event(
                    tier='2', operation='field_change',
                    operation_label='Field change',
                    model=rec._name, res_id=rec.id,
                    res_display_name=rec.display_name,
                    field_changes=changes, source='channel')
        return result