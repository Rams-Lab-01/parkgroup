from odoo import fields, models


class _PdcLinkMixin(models.AbstractModel):
    """Shared smart-button helpers for models a cheque can be linked to."""
    _name = 'sgc.pdc.link.mixin'
    _description = 'PDC link helpers'

    pdc_count = fields.Integer(string='Cheques', compute='_compute_pdc_count')

    def _pdc_link_field(self):
        raise NotImplementedError

    def _compute_pdc_count(self):
        field = self._pdc_link_field()
        counts = {}
        if self.ids:
            groups = self.env['sgc.pdc.cheque'].sudo()._read_group(
                [(field, 'in', self.ids)], [field], ['__count'])
            counts = {rec.id: n for rec, n in groups}
        for rec in self:
            rec.pdc_count = counts.get(rec.id, 0)

    def action_view_pdc(self):
        self.ensure_one()
        field = self._pdc_link_field()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'sgc_pdc_management.action_sgc_pdc_cheque_all')
        action['domain'] = [(field, '=', self.id)]
        action['context'] = {'default_%s' % field: self.id}
        return action

    def action_register_pdc(self):
        self.ensure_one()
        field = self._pdc_link_field()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'sgc_pdc_management.action_sgc_pdc_cheque_all')
        action.update({'view_mode': 'form', 'views': [(False, 'form')], 'target': 'current',
                       'context': {'default_%s' % field: self.id}})
        return action


class SaleContractInstallment(models.Model):
    _name = 'sale.contract.installment'
    _inherit = ['sale.contract.installment', 'sgc.pdc.link.mixin']

    def _pdc_link_field(self):
        return 'installment_id'


class TenancyDetails(models.Model):
    _name = 'tenancy.details'
    _inherit = ['tenancy.details', 'sgc.pdc.link.mixin']

    def _pdc_link_field(self):
        return 'tenancy_id'


class RentInvoice(models.Model):
    _name = 'rent.invoice'
    _inherit = ['rent.invoice', 'sgc.pdc.link.mixin']

    def _pdc_link_field(self):
        return 'rent_invoice_id'


class SaleContract(models.Model):
    _name = 'sale.contract'
    _inherit = ['sale.contract', 'sgc.pdc.link.mixin']

    def _pdc_link_field(self):
        return 'sale_contract_id'
