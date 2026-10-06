# -*- coding: utf-8 -*-
# Copyright 2025 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models

# Keyword -> bundled fallback icon, used when no image has been uploaded
# on the amenity/connectivity record itself. Served as a static asset
# (not through /web/image) since these are SVGs and Odoo's binary image
# controller can only serve formats PIL can decode.
ICON_KEYWORD_MAP = [
    # Amenities (Tabler Icons, MIT license)
    (('surveillance', 'camera', 'cctv', 'security'), 'cctv.svg'),
    (('gym', 'fitness', 'workout'), 'gym.svg'),
    (('swimming', 'pool',), 'pool.svg'),
    (('parking',), 'parking.svg'),
    (('kid', 'play', 'playground', 'children'), 'playground.svg'),
    (('bbq', 'barbecue', 'grill'), 'bbq.svg'),
    (('botanical', 'flower',), 'botanical.svg'),
    (('garden', 'lawn'), 'garden.svg'),
    # Connectivity
    (('airport',), 'airport.svg'),
    (('beach', 'sea', 'marina'), 'beach.svg'),
    (('financial', 'bank', 'district'), 'financial.svg'),
    (('hospital', 'clinic', 'medical'), 'hospital-building.svg'),
    (('mall', 'shopping', 'supermarket'), 'mall.svg'),
    (('palm', 'jumeirah'), 'palm.svg'),
    (('park',), 'park.svg'),
    (('school', 'university', 'college', 'education'), 'school.svg'),
    (('train', 'metro', 'station', 'railway'), 'metro.svg'),
    (('tourist', 'destination', 'attraction'), 'tourist.svg'),
    (('prime', 'location',), 'location.svg'),
    (('highway', 'road', 'motorway'), 'highway.svg'),
    (('office', 'business'), 'office.svg'),
    (('city', 'downtown'), 'city.svg'),
    (('factory', 'industrial', 'plant'), 'factory-plant.svg'),
    (('connectivity', 'stone'), 'gem.svg'),
]
ICON_DEFAULT_FILE = 'building.svg'
ICON_STATIC_BASE = '/sgc_offplan_rental_property_management/static/src/img/'


def _match_icon_filename(text):
    text = (text or '').lower()
    for keywords, filename in ICON_KEYWORD_MAP:
        if any(keyword in text for keyword in keywords):
            return filename
    return ICON_DEFAULT_FILE


class PropertyAmenities(models.Model):
    _name = 'property.amenities'
    _inherit = ['sgc.critical.audit.mixin']
    _description = 'Property Amenities'
    _order = 'sequence, title'

    # Audit capture scope (Entry 51): the label shown in listings and the
    # display order. `image` is media (size marker only if it were watched) and
    # `icon_url` is computed, so neither is in scope.
    _audit_watched_fields = frozenset({
        'title',
        'sequence',
    })

    image = fields.Binary(string='Image')
    title = fields.Char(string='Title', required=True)
    sequence = fields.Integer(string='Sequence', default=10)
    icon_url = fields.Char(string='Icon URL', compute='_compute_icon_url')

    @api.depends('image', 'title')
    def _compute_icon_url(self):
        for record in self:
            record.icon_url = record.get_icon_url()

    def get_icon_url(self):
        self.ensure_one()
        if self.image:
            return '/web/image/property.amenities/%s/image' % self.id
        return ICON_STATIC_BASE + _match_icon_filename(self.title)
