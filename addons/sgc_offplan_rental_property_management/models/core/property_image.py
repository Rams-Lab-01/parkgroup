# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models
from odoo.tools.image import image_process

_logger = logging.getLogger(__name__)


class PropertyImage(models.Model):
    """Multi-image gallery for properties, projects, and sub-projects."""
    _name = 'property.image'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'sgc.critical.audit.mixin']
    _description = 'Property Image'
    _order = 'sequence, id'

    # Audit capture scope (Entry 44): the label and the polymorphic owner.
    # Image payloads and derived resizes are binary/derived (the serializer
    # stores size markers only); sequence is display.
    _audit_watched_fields = frozenset({
        'name',
        'property_id',
        'project_id',
        'sub_project_id',
    })

    # Images are removed as ordinary gallery editing (editable list, no UI
    # reason workflow); deletion is captured but not reason-gated (Entry 44).
    _audit_unlink_requires_reason = False

    name = fields.Char(string='Label')
    sequence = fields.Integer(string='Sequence', default=10)
    image_1920 = fields.Binary(string='Image (1920px)', attachment=True, required=True)
    image_1024 = fields.Binary(string='Image (1024px)', compute='_compute_images', store=True, attachment=True)
    image_512 = fields.Binary(string='Image (512px)', compute='_compute_images', store=True, attachment=True)
    image_256 = fields.Binary(string='Image (256px)', compute='_compute_images', store=True, attachment=True)
    active = fields.Boolean(string='Active', default=True)

    # Polymorphic link to parent records
    property_id = fields.Many2one('property.details', string='Property', ondelete='cascade', index=True)
    project_id = fields.Many2one('property.project', string='Project', ondelete='cascade', index=True)
    sub_project_id = fields.Many2one('property.sub.project', string='Sub Project', ondelete='cascade', index=True)

    @api.depends('image_1920')
    def _compute_images(self):
        for rec in self:
            if not rec.image_1920:
                rec.image_1024 = rec.image_512 = rec.image_256 = False
                continue
            try:
                rec.image_1024 = image_process(rec.image_1920, size=(1024, 1024))
                rec.image_512 = image_process(rec.image_1920, size=(512, 512))
                rec.image_256 = image_process(rec.image_1920, size=(256, 256))
            except Exception:
                _logger.warning('Could not process image_1920 for property.image id=%s; leaving resized images empty.', rec.id)
                rec.image_1024 = rec.image_512 = rec.image_256 = False


class PropertyDetails(models.Model):
    _inherit = 'property.details'

    image_ids = fields.One2many('property.image', 'property_id', string='Gallery Images',
                                copy=True, help='Additional property images for gallery display')


class PropertyProject(models.Model):
    _inherit = 'property.project'

    image_ids = fields.One2many('property.image', 'project_id', string='Gallery Images',
                                copy=True, help='Additional project images for gallery display')


class PropertySubProject(models.Model):
    _inherit = 'property.sub.project'

    image_ids = fields.One2many('property.image', 'sub_project_id', string='Gallery Images',
                                copy=True, help='Additional sub-project images for gallery display')
