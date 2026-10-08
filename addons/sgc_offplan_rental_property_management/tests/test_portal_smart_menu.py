# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPortalSmartMenu(TransactionCase):
    """The /my property tiles only show when the account has related data."""

    def test_empty_account_sees_no_property_tiles(self):
        partner = self.env["res.partner"].create({"name": "Nobody Portal"})
        self.assertFalse(any(partner._portal_property_menu().values()))

    def test_favorite_makes_favorites_tile_visible(self):
        prop = self.env["property.details"].search([], limit=1)
        if not prop:
            self.skipTest("no property available")
        partner = self.env["res.partner"].create({"name": "Fan Portal", "favorite_property_ids": [(4, prop.id)]})
        menu = partner._portal_property_menu()
        self.assertTrue(menu["favorites"])
        self.assertFalse(menu["purchases"] or menu["lease"] or menu["portfolio"] or menu["inquiries"])
