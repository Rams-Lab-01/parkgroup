# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class PropertyPublishWizard(models.TransientModel):
    _name = 'property.publish.wizard'
    _description = 'Property Publishing Wizard'

    property_id = fields.Many2one(
        'property.details',
        string='Property',
        required=True,
        readonly=True
    )

    # Publishing Options
    publish_to_website = fields.Boolean(
        string='Publish to Website',
        default=True,
        help='Make this property visible on your website'
    )

    def action_publish(self):
        """Execute the publishing process"""
        self.ensure_one()

        if not self.publish_to_website:
            raise UserError(_('Please select at least one publishing option'))

        property_obj = self.property_id
        messages = []

        # Publish to Website
        if self.publish_to_website:
            property_obj.write({
                'is_published_website': True,
                'website_published_date': fields.Datetime.now()
            })
            messages.append('Published to Website')

        # Show success notification
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Publishing Successful'),
                'message': '<br/>'.join(messages),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }
