# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
"""Idempotent importer for the escrow allocation register.

Built specifically to absorb ``escrow_deferred.json`` -- the 226-unit deferred
escrow ledger produced by the 2026-10-05 reconciliation, which was deliberately
*not* written to the database pending this module.

Source payload shape::

    {"project": "BR2", "unit": "101", "client": "MACHIEL DE VRIES",
     "escrow_pct": 0.2586424322, "escrow_allocated": 571491.43,
     "sold": 2209581.1, "collected": 867736.93}

Note ``escrow_pct`` arrives as a *fraction* (0.2586 = 25.86%). It is stored
here as a percentage (25.86), matching the field's label and Odoo convention.

Re-running is safe. Records are matched on ``(project, unit)``; a re-import
updates the source facts and the derived columns follow. Rows whose unit cannot
be resolved are reported, never guessed.
"""

import base64
import csv
import io
import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

_FLAG_NOTES = {
    'BREAKDOWN_EXCEEDS_COLLECTED': _(
        'Source 10%%/20%% breakdown exceeds the collected figure; collapsed to a '
        'single collection bucket.'),
    'OVERPAYMENT': _(
        'Source shows a negative balance due; no pending line exists. Verify the '
        'overpayment with finance.'),
}


class EscrowAllocationImport(models.TransientModel):
    """Load per-unit escrow allocation facts from JSON or CSV."""

    _name = 'escrow.allocation.import'
    _description = 'Import Escrow Allocations'

    source_file = fields.Binary(
        string='Source File',
        required=True,
        attachment=False,
        help='JSON array or CSV with the columns project, unit, client, escrow_pct, '
             'escrow_allocated, sold, collected.',
    )
    source_filename = fields.Char(string='File Name')
    dry_run = fields.Boolean(
        string='Dry Run (check only)',
        default=True,
        help='Report what would be written without touching the database.',
    )
    flag_file = fields.Binary(
        string='Flags File (optional)',
        attachment=False,
        help='JSON array of reconciliation flags to stamp onto the matching units, '
             'e.g. the deferred flags.json.',
    )
    flag_filename = fields.Char(string='Flags File Name')

    created_count = fields.Integer(string='Created', readonly=True)
    updated_count = fields.Integer(string='Updated', readonly=True)
    skipped_count = fields.Integer(string='Unresolved', readonly=True)
    flagged_count = fields.Integer(string='Flagged', readonly=True)
    report_line_ids = fields.One2many(
        'escrow.allocation.import.line',
        'import_id',
        string='Report',
    )
    state = fields.Selection(
        [('draft', 'Ready'), ('done', 'Completed')],
        default='draft',
        readonly=True,
    )

    # -- Actions ---
    def action_run(self):
        """Parse, resolve, and (unless dry run) write the allocation register."""
        self.ensure_one()
        self.mapped('report_line_ids').unlink()
        self.write({'state': 'draft'})

        try:
            payload = json.loads(self._decode(self.source_file))
            records = self._normalise_json(payload)
        except (ValueError, json.JSONDecodeError):
            records = self._normalise_csv(self._decode(self.source_file))

        if not records:
            raise UserError(_(
                'No allocation rows found in %(filename)s. Expected a JSON array '
                'or a CSV with the columns project, unit, client, escrow_pct, '
                'escrow_allocated, sold, collected.'
            ) % {'filename': self.source_filename or _('the uploaded file')})

        flags = self._load_flags()

        report = self.env['escrow.allocation.import.line']
        created = updated = unresolved = flagged = 0

        for record in records:
            project = self._resolve_project(record.get('project'))
            unit = self._resolve_unit(project, record.get('unit'))
            if not project or not unit:
                unresolved += 1
                report |= self.env['escrow.allocation.import.line'].create({
                    'import_id': self.id,
                    'project_label': record.get('project') or '',
                    'unit_label': record.get('unit') or '',
                    'client_label': record.get('client') or '',
                    'outcome': 'unresolved',
                    'detail': _(
                        'No project/unit match for %(project)s/%(unit)s. Left out '
                        'rather than guessed.'
                    ) % {'project': record.get('project'), 'unit': record.get('unit')},
                })
                continue

            allocation = self.env['escrow.allocation'].search([
                ('project_id', '=', project.id),
                ('unit_id', '=', unit.id),
            ], limit=1)
            exists = bool(allocation)

            flag = flags.get((project.code, unit.unit_number))
            values = self._to_values(project, unit, record, flag)

            if exists:
                updated += 1
                outcome = 'updated'
                detail = _('Source figures refreshed.')
            else:
                created += 1
                outcome = 'created'
                detail = _('New allocation row created from source.')

            if not self.dry_run:
                if exists:
                    allocation.write(values)
                else:
                    allocation = self.env['escrow.allocation'].create(values)

            if flag:
                flagged += 1

            report |= self.env['escrow.allocation.import.line'].create({
                'import_id': self.id,
                'project_label': project.code or project.name,
                'unit_label': unit.unit_number or unit.display_name,
                'client_label': record.get('client') or '',
                'outcome': outcome,
                'detail': detail,
            })

        self.write({
            'created_count': created,
            'updated_count': updated,
            'skipped_count': unresolved,
            'flagged_count': flagged,
            'state': 'done',
        })

        return {
            'type': 'ir.actions.act_window',
            'name': _('Escrow Allocation Import Report'),
            'res_model': 'escrow.allocation.import',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # -- Parsing ---
    def _decode(self, payload):
        if not payload:
            return ''
        if isinstance(payload, str):
            return payload
        return base64.b64decode(payload).decode('utf-8-sig')

    def _normalise_json(self, payload):
        """Accept either a bare list or a {'records': [...]} wrapper."""
        if isinstance(payload, dict):
            payload = payload.get('records') or payload.get('rows') or []
        if not isinstance(payload, list):
            raise ValueError('JSON payload is not a list of allocation records.')
        return [row for row in payload if isinstance(row, dict)]

    def _normalise_csv(self, text):
        reader = csv.DictReader(io.StringIO(text))
        return [
            {(k or '').strip(): (v or '').strip() for k, v in row.items()}
            for row in reader
        ]

    def _load_flags(self):
        """Return ``{(project_code, unit_number): flag_dict}``."""
        if not self.flag_file:
            return {}
        try:
            payload = json.loads(self._decode(self.flag_file))
        except (ValueError, json.JSONDecodeError):
            _logger.warning('sgc_escrow: flags file is not valid JSON, ignoring.')
            return {}
        if isinstance(payload, dict):
            payload = payload.get('flags') or []
        flags = {}
        for row in payload if isinstance(payload, list) else []:
            if not isinstance(row, dict):
                continue
            key = ((row.get('project') or '').strip(),
                   (row.get('unit') or '').strip())
            if all(key):
                flags[key] = row
        return flags

    # -- Resolution ---
    @api.model
    def _resolve_project(self, code):
        if not code:
            return self.env['property.project']
        code = str(code).strip()
        project = self.env['property.project'].search([
            ('code', '=', code),
        ], limit=1)
        if project:
            return project
        return self.env['property.project'].search([
            ('name', '=ilike', code),
        ], limit=1)

    @api.model
    def _resolve_unit(self, project, unit_number):
        if not unit_number:
            return self.env['property.details']
        unit_number = str(unit_number).strip()
        unit = self.env['property.details']
        if project:
            unit = unit.search([
                ('project_id', '=', project.id),
                ('unit_number', '=', unit_number),
            ], limit=1)
            if unit:
                return unit
        # Fall back to a global search on the unit number, then verify the
        # project actually holds it -- a wrong-project match is worse than none.
        candidates = self.env['property.details'].search([
            ('unit_number', '=', unit_number),
        ], limit=10)
        if len(candidates) == 1 and (not project or candidates.project_id == project):
            return candidates
        return self.env['property.details']

    # -- Mapping ---
    def _to_values(self, project, unit, record, flag=None):
        """Translate one source row into escrow.allocation values."""
        pct = self._as_float(record.get('escrow_pct'))
        # Sources carry escrow_pct as a fraction; the field stores a percentage.
        pct = pct * 100.0 if pct is not None and pct <= 1.0 else (pct or 0.0)

        contract = self.env['sale.contract'].search([
            ('property_id', '=', unit.id),
        ], order='id desc', limit=1)

        values = {
            'project_id': project.id,
            'unit_id': unit.id,
            'contract_id': contract.id or False,
            'company_id': project.company_id.id or self.env.company.id,
            'currency_id': project.escrow_currency_id.id or self.env.company.currency_id.id,
            'escrow_pct': round(pct, 8),
            'sale_price_snapshot': self._as_float(record.get('sold')) or 0.0,
            'collected_amount': self._as_float(record.get('collected')) or 0.0,
            # A missing allocation stays missing: None (not 0.0) so the
            # create/write sync marks has_source_data False. Zero would read as
            # a fact -- the source explicitly saying "nothing allocated".
            'allocated_amount': self._as_float(record.get('escrow_allocated')),
            'source_reference': self.source_filename or _('Escrow allocation import'),
        }
        if flag:
            values['flag_code'] = (flag.get('kind') or '').strip() or False
            values['flag_note'] = (flag.get('info') or '').strip() or False
            values['reconciliation_note'] = _FLAG_NOTES.get(
                values['flag_code'], _('Flagged during reconciliation; finance sign-off required.'))
        return values

    @api.model
    def _as_float(self, value):
        """Tolerant numeric coercion: '' and None mean *no figure supplied*."""
        if value is None or value == '':
            return None
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(str(value).replace(',', '').strip())
        except (TypeError, ValueError):
            return None


class EscrowAllocationImportLine(models.TransientModel):
    """One row of the import report."""

    _name = 'escrow.allocation.import.line'
    _description = 'Escrow Allocation Import Report Line'
    _order = 'id'

    import_id = fields.Many2one(
        'escrow.allocation.import',
        string='Import',
        required=True,
        ondelete='cascade',
    )
    project_label = fields.Char(string='Project')
    unit_label = fields.Char(string='Unit')
    client_label = fields.Char(string='Client')
    outcome = fields.Selection(
        [
            ('created', 'Created'),
            ('updated', 'Updated'),
            ('unresolved', 'Unresolved'),
        ],
        string='Outcome',
        required=True,
    )
    detail = fields.Text(string='Detail')