from odoo import fields, models


class SgcPdcBounceWizard(models.TransientModel):
    _name = 'sgc.pdc.bounce.wizard'
    _description = 'PDC Bounce Wizard'

    cheque_id = fields.Many2one('sgc.pdc.cheque', required=True, ondelete='cascade')
    reason = fields.Text(string='Reason', required=True)

    def action_confirm(self):
        self.ensure_one()
        self.cheque_id._do_bounce(self.reason)
        return {'type': 'ir.actions.act_window_close'}
