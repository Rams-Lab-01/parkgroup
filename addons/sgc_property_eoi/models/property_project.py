from odoo import fields, models


class PropertyProject(models.Model):
    _inherit = 'property.project'

    developer_id = fields.Many2one(
        'res.partner', string='Developer',
        help='Legal developer / seller named on EOI and booking documents. Empty = the company.')
    plot_number = fields.Char(string='Plot Number')
    eoi_unit_count = fields.Integer(string='Units under EOI', compute='_compute_sgc_counts')
    confirmed_sale_count = fields.Integer(string='Confirmed Sales', compute='_compute_sgc_counts')

    def _compute_sgc_counts(self):
        groups = self.env['property.details']._read_group(
            [('project_id', 'in', self.ids), ('state', 'in', ('eoi', 'confirmed_sale'))],
            groupby=['project_id', 'state'], aggregates=['__count'])
        data = {(project.id, state): count for project, state, count in groups}
        for rec in self:
            rec.eoi_unit_count = data.get((rec.id, 'eoi'), 0)
            rec.confirmed_sale_count = data.get((rec.id, 'confirmed_sale'), 0)
