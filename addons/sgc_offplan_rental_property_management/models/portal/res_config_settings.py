# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    portal_feed_base_url = fields.Char(
        string="Portal Feed Base URL",
        config_parameter="rental_portal_syndication.feed_base_url",
        help="Override base URL used to build feed links (defaults to web.base.url).",
    )
    portal_default_token = fields.Char(
        string="Default Feed Token",
        config_parameter="rental_portal_syndication.default_feed_token",
    )
