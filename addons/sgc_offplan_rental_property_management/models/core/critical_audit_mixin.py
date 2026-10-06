"""sgc.critical.audit.mixin -- Channel 2 capture hooks (design §6, [C10]).

Applied model-level (in _inherit) on the critical models listed in the coverage
matrix ONLY; never inherited globally. All capture work is delegated to
SgcAuditInternalService; this mixin only detects what changed and enforces the
Tier-1 reason gate for special fields (company_id reassignment, commission
overrides, webhook activation) and for destructive unlink (design §3.1).
"""

from odoo import api, models
from odoo.exceptions import ValidationError


def _get_service(env):
    # Late import keeps the mixin import-safe while the services package is
    # loaded after models/core during module import (see models/__init__.py).
    from odoo.addons.sgc_offplan_rental_property_management.services import sgc_audit_internal_service
    return sgc_audit_internal_service.SgcAuditInternalService(env)


class CriticalAuditMixin(models.AbstractModel):
    _name = 'sgc.critical.audit.mixin'
    _description = 'Critical Change Audit Capture Mixin'

    # Fields that never produce field-change rows: ORM bookkeeping, computed
    # display values, and 'active' (archival is captured as its own operation).
    _audit_excluded_fields = frozenset({
        'id', 'display_name', '__last_update', 'create_uid', 'create_date',
        'write_uid', 'write_date', 'active',
    })

    # Whether deleting a record of this model is Tier-1 reason-gated.
    # ``True`` is the design default and preserves existing behaviour for
    # every wired model.  A model may declare ``False`` when its rows are
    # operational sub-records that users remove as ordinary editing (gallery
    # images, schedule lines): the unlink is still captured, at tier 2,
    # without a reason (Entry 44, operator decision 2026-09-20).
    _audit_unlink_requires_reason = True

    # Per-model field allowlist.  ``None`` keeps the original behaviour for
    # models already on the chain: every field except the bookkeeping set above
    # is attested.  A frozenset narrows capture to exactly those fields, so the
    # verification report can state which fields are attested instead of
    # implying that any change to the record is (Entry 28).
    _audit_watched_fields = None

    # R27: capture timing is DECLARED, not assumed. Every wired model inherits
    # this declaration; a model may override it. unlink snapshots the record
    # BEFORE the delete, because after super().unlink() the row is gone and any
    # relational read raises MissingError (the D6/D7/1.1 root class).
    _audit_capture_points = {
        'create': 'post-create, same transaction, stored values',
        'write': 'post-write, same transaction, stored values',
        'unlink': 'pre-delete snapshot of every attested field + company_id + '
                  'tenant_uuid; event written after the delete',
    }

    # Tier-1 special-field writes are rejected unless a Channel-1 wrapper owns
    # the reason-gated path (design §3.1: company reassignment §8.7, fee and
    # commission overrides, webhook activation on portal.connector).
    _audit_t1_commission_models = frozenset({
        'property.commission.line', 'rent.commission.line',
        'property.vendor.commission.line',
    })
    _audit_t1_commission_fields = frozenset({'commission_percentage', 'commission_amount'})
    _audit_t1_webhook_model = 'portal.connector'

    def _audit_candidate_fields(self, field_names):
        """Fields eligible for capture on this record."""
        watched = self._audit_watched_fields
        if watched is not None:
            return [f for f in field_names if f in watched and f in self._fields]
        return [f for f in field_names
                if f in self._fields and f not in self._audit_excluded_fields]

    def _audit_serialize(self, fname, value):
        """Serialize an arbitrary field value to a JSON-safe primitive.

        Never stores display names or binary payloads (P0-11): M2O becomes an
        integer id, M2M/O2M a sorted id list, dates ISO-8601 strings, binary a
        size marker only.
        """
        field = self._fields.get(fname)
        ftype = field.type if field else None
        if ftype == 'many2one':
            if isinstance(value, models.BaseModel):
                return value.id or False
            if isinstance(value, (tuple, list)):
                cmds = value if isinstance(value[0], tuple) else [value]
                cmd = cmds[0]
                if cmd[0] == 6:
                    return cmd[2][0] if cmd[2] else False
                if cmd[0] in (1, 4):
                    return cmd[1]
                return False
            return int(value) if value else False
        if ftype in ('many2many', 'one2many'):
            if isinstance(value, models.BaseModel):
                return sorted(value.ids or [])
            if isinstance(value, (tuple, list)) and value and isinstance(value[0], (tuple, list)):
                ids = set()
                for cmd in value:
                    if cmd[0] == 6:
                        ids.update(cmd[2] or [])
                    elif cmd[0] in (1, 2, 3, 4):
                        ids.add(cmd[1])
                return sorted(ids)
            return sorted(int(x) for x in (value or []))
        if ftype in ('datetime', 'date'):
            if not value:
                return False
            # The ORM hands this method a date/datetime object once the value is
            # stored.  A raw vals dict can still reach it - XML-RPC, JSON-RPC,
            # imports and the web client all pass dates as strings - so pass a
            # string through instead of calling .isoformat() on it.  Serialising
            # the stored value rather than the incoming one is the real fix:
            # it attests what actually changed (Entry 28).
            return value.isoformat() if hasattr(value, 'isoformat') else str(value)
        if ftype == 'binary':
            return '<binary:{0}>'.format(len(value) if value else 0)
        return value

    def _audit_t1_reason_required(self, rec, vals):
        """True when a Tier-1 special field is written outside a gated path."""
        if 'company_id' in rec._fields and 'company_id' in vals:
            new_company = self._audit_serialize('company_id', vals.get('company_id'))
            if (new_company or False) != (rec.company_id.id or False):
                return True
        if rec._name in self._audit_t1_commission_models and \
                self._audit_t1_commission_fields.intersection(vals):
            return True
        if rec._name == self._audit_t1_webhook_model and 'active' in vals:
            # Webhook activation AND deactivation are governed T1 ops (§3.1).
            return True
        if 'active' in rec._fields and 'active' in vals and bool(vals.get('active')) and not rec.active:
            # Unarchive is a governed Tier-1 operation (§3.1 action_unarchive).
            return True
        return False

    def _audit_check_t1_gated(self, service, vals):
        """Reject Tier-1 special-field writes that no Channel-1 wrapper owns."""
        for rec in self:
            if service.guard_active(rec._name, rec.id):
                continue
            if self._audit_t1_reason_required(rec, vals):
                raise ValidationError(
                    'This change is Tier-1 audited and requires an operator '
                    'reason. Use the reason-gated workflow for %s #%s.'
                    % (rec._name, rec.id))

    @api.model_create_multi
    def create(self, vals_list):
        if self._name.startswith('sgc.critical.audit'):
            # No self-recursion: audit models are outside Channel 2.
            return super().create(vals_list)
        records = super().create(vals_list)
        service = _get_service(self.env)
        for rec, vals in zip(records, vals_list):
            if service.guard_active(rec._name, rec.id):
                continue  # Channel-1 wrapper owns the capture (P0-5)
            candid = rec._audit_candidate_fields(vals)
            changes = [{'field_name': f, 'old_value': False,
                        'new_value': rec._audit_serialize(f, rec[f])}
                       for f in candid]
            if changes:
                service.capture_event(
                    tier='2', operation='create', operation_label='Record created',
                    model=rec._name, res_id=rec.id,
                    res_display_name=rec.display_name,
                    field_changes=changes, source='channel')
        return records

    def write(self, vals):
        if not vals or self._name.startswith('sgc.critical.audit'):
            return super().write(vals)
        service = _get_service(self.env)
        self._audit_check_t1_gated(service, vals)
        candid_fields = self._audit_candidate_fields(vals)
        old_snap = {rec.id: {f: rec[f] for f in candid_fields} for rec in self}
        # Defect A (Entry 41): `active` is in _audit_excluded_fields, so it is
        # never in candid_fields. Snapshot it before super().write so the
        # unarchive branch can attest the OLD value. Capture fires under a
        # guard as tier 1 with the reason attached.
        active_snapshot = {rec.id: rec.active for rec in self} if 'active' in vals else None
        result = super().write(vals)
        for rec in self:
            guard_cid = service.guard_correlation(rec._name, rec.id)
            guard_reason = service.get_reason(rec._name, rec.id) if guard_cid else None

            # --- Defect A: explicit capture for archive/unarchive ---
            # `active` is excluded from candid_fields, so without this branch a
            # False<->True write matches neither archive nor field-change and
            # captures nothing. A write under a guard IS Tier 1, so
            # capture_event stores a reason (R18 + Entry 40 fix at .53).
            active_changed = False
            if active_snapshot is not None and 'active' in vals:
                old_active = bool(active_snapshot[rec.id])
                new_active = bool(vals.get('active'))
                if old_active != new_active:
                    active_changed = True
                    op = 'unarchive' if new_active else 'archive'
                    label = 'Unarchived' if new_active else 'Archived'
                    service.capture_event(
                        tier='1' if guard_cid else '2',
                        operation=op, operation_label=label,
                        model=rec._name, res_id=rec.id,
                        res_display_name=rec.display_name,
                        field_changes=[{'field_name': 'active',
                                        'old_value': old_active,
                                        'new_value': new_active}],
                        source=op, correlation_uuid=guard_cid,
                        reason=(guard_reason or {}).get('reason'))
                    if guard_reason:
                        service.consume_reason(rec._name, rec.id)

            # --- existing field-change branch (kept) ---
            changes = []
            for f in candid_fields:
                old_prim = self._audit_serialize(f, old_snap[rec.id].get(f))
                new_prim = self._audit_serialize(f, rec[f])
                if old_prim != new_prim:
                    changes.append({'field_name': f,
                                    'old_value': old_prim,
                                    'new_value': new_prim})
            if changes:
                service.capture_event(
                    tier='1' if guard_cid else '2',
                    operation='field_change',
                    operation_label='Field change',
                    model=rec._name, res_id=rec.id,
                    res_display_name=rec.display_name,
                    field_changes=changes, source='channel',
                    correlation_uuid=guard_cid,
                    reason=(guard_reason or {}).get('reason'))
                if guard_reason:
                    service.consume_reason(rec._name, rec.id)

            # --- Defect B (Entry 41): independent guard assertion ---
            # Fire guard_note_change ONCE per record based on whether an
            # attested field actually changed (active or candid field). The
            # previous design fired it only inside the capture branches,
            # so a governed write that captured nothing never marked the
            # guard as changed and guard_end returned silently. The
            # Entry-38 assertion now catches Tier-1 guarded writes that
            # mutate an attested field but capture nothing.
            if active_changed or changes:
                service.guard_note_change(rec._name, rec.id, True)
        return result

    def copy(self, default=None):
        if self._name.startswith('sgc.critical.audit'):
            return super().copy(default)
        service = _get_service(self.env)
        new_recs = super().copy(default)
        for rec in new_recs:
            if service.guard_active(rec._name, rec.id):
                continue  # Channel-1 wrapper owns the capture (P0-5)
            service.capture_event(
                tier='2', operation='copy', operation_label='Record copied',
                model=rec._name, res_id=rec.id,
                res_display_name=rec.display_name, source='copy')
        return new_recs

    def unlink(self):
        if not self or self._name.startswith('sgc.critical.audit'):
            return super().unlink()
        service = _get_service(self.env)
        # Pre-flight: every record needs a registered operator reason. Reasons
        # are consumed only after a successful delete so a rolled-back capture
        # does not destroy the gate for a retry.
        for rec in self:
            if service.guard_active(rec._name, rec.id):
                continue  # Channel-1 wrapper owns the whole path
            if not rec._audit_unlink_requires_reason:
                continue  # exempt sub-record model: tier-2 capture, no gate
            if not service.has_reason(rec._name, rec.id):
                raise ValidationError(
                    'Deleting %s records is Tier-1 audited and requires an '
                    'operator reason. Use the Actions menu entry '
                    '"Delete with audit reason" on the record or the list '
                    'selection.' % self._name)
        # R27: snapshot EVERY attested field BEFORE the delete, plus company_id
        # and tenant_uuid. The event must attest what was deleted, read while
        # the row still exists; after super().unlink() any relational read on
        # the record raises MissingError (Wave 1.1 negative test).
        payload = []
        for rec in self:
            snap = []
            for fname in self._audit_candidate_fields(rec._fields):
                try:
                    snap.append({
                        'field_name': fname,
                        'old_value': rec._audit_serialize(fname, rec[fname]),
                        'new_value': False,
                    })
                except Exception:
                    continue
            company_id = (
                rec.company_id.id
                if 'company_id' in rec._fields and rec.company_id else False)
            payload.append((rec._name, rec.id, rec.display_name, company_id, snap,
                            rec._audit_unlink_requires_reason))
        result = super().unlink()
        for model_name, res_id, display_name, company_id, snap, gated in payload:
            guard_cid = service.guard_correlation(model_name, res_id)
            reason = service.consume_reason(model_name, res_id) if gated else None
            service.capture_event(
                tier='1' if gated else '2',
                operation='unlink', operation_label='Record deleted',
                model=model_name, res_id=res_id,
                res_display_name=display_name,
                company_id=company_id,
                field_changes=snap,
                reason=reason['reason'] if reason else None,
                correlation_uuid=(reason['correlation_uuid'] if reason else guard_cid),
                source='unlink')
            service.guard_note_change(model_name, res_id, True)
        return result