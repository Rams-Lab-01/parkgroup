# -*- coding: utf-8 -*-
# Copyright 2025 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
"""
File Upload Validation Mixin
Provides security validation for file uploads:
- File size limits
- MIME type validation
- Security checks
"""
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import base64
import logging

_logger = logging.getLogger(__name__)

# Maximum file size in bytes (10 MB by default)
MAX_FILE_SIZE_MB = 10
MAX_FILE_SIZE = MAX_FILE_SIZE_MB * 1024 * 1024

# Allowed MIME types for document uploads
ALLOWED_DOCUMENT_TYPES = [
    'application/pdf',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',  # .docx
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',  # .xlsx
    'text/plain',
    'text/csv',
]

# Allowed MIME types for images
ALLOWED_IMAGE_TYPES = [
    'image/jpeg',
    'image/jpg',
    'image/png',
    'image/gif',
    'image/bmp',
    'image/webp',
]

# All allowed types combined
ALL_ALLOWED_TYPES = ALLOWED_DOCUMENT_TYPES + ALLOWED_IMAGE_TYPES


class FileValidationMixin(models.AbstractModel):
    """
    Mixin to add file upload validation to models

    Usage:
        class MyModel(models.Model):
            _name = 'my.model'
            _inherit = ['file.validation.mixin']

            my_file = fields.Binary(string="Upload File")
    """
    _name = 'file.validation.mixin'
    _description = 'File Upload Validation Mixin'

    def _get_max_file_size(self):
        """Get maximum file size from configuration or default"""
        try:
            max_size_mb = int(self.env['ir.config_parameter'].sudo().get_param(
                'sgc_offplan_rental_property_management.max_file_upload_size', MAX_FILE_SIZE_MB))
            return max_size_mb * 1024 * 1024
        except (ValueError, TypeError):
            return MAX_FILE_SIZE

    def _get_file_mime_type(self, file_data):
        """
        Detect MIME type of file data

        Args:
            file_data: Base64 encoded file data

        Returns:
            str: MIME type or None if detection fails
        """
        try:
            # Try to use python-magic if available
            try:
                import magic
                decoded_data = base64.b64decode(file_data)
                mime_type = magic.from_buffer(decoded_data, mime=True)
                return mime_type
            except ImportError:
                # Fallback: Basic MIME detection from first bytes
                decoded_data = base64.b64decode(file_data)

                # PDF
                if decoded_data.startswith(b'%PDF'):
                    return 'application/pdf'
                # PNG
                elif decoded_data.startswith(b'\x89PNG'):
                    return 'image/png'
                # JPEG
                elif decoded_data.startswith(b'\xff\xd8\xff'):
                    return 'image/jpeg'
                # GIF
                elif decoded_data.startswith(b'GIF8'):
                    return 'image/gif'
                # ZIP (DOCX/XLSX are ZIP files)
                elif decoded_data.startswith(b'PK\x03\x04'):
                    # Could be docx, xlsx, or zip
                    return 'application/zip'  # Accept as document
                else:
                    return None
        except Exception as e:
            _logger.warning(f"MIME type detection failed: {str(e)}")
            return None

    def _validate_file_size(self, file_data, field_name='file'):
        """
        Validate file size

        Args:
            file_data: Base64 encoded file data
            field_name: Name of the field (for error messages)

        Raises:
            ValidationError: If file is too large
        """
        if not file_data:
            return

        try:
            decoded_data = base64.b64decode(file_data)
            file_size = len(decoded_data)
            max_size = self._get_max_file_size()

            if file_size > max_size:
                max_size_mb = max_size / (1024 * 1024)
                file_size_mb = file_size / (1024 * 1024)
                raise ValidationError(_(
                    'File size for "%s" exceeds maximum allowed size of %.1f MB. '
                    'Your file is %.2f MB. Please upload a smaller file.'
                ) % (field_name, max_size_mb, file_size_mb))
        except base64.binascii.Error:
            raise ValidationError(_(
                'Invalid file data for "%s". The file may be corrupted.'
            ) % field_name)

    def _validate_file_mime_type(self, file_data, field_name='file', allowed_types=None):
        """
        Validate file MIME type

        Args:
            file_data: Base64 encoded file data
            field_name: Name of the field (for error messages)
            allowed_types: List of allowed MIME types (None = allow all in whitelist)

        Raises:
            ValidationError: If file type is not allowed
        """
        if not file_data:
            return

        if allowed_types is None:
            allowed_types = ALL_ALLOWED_TYPES

        mime_type = self._get_file_mime_type(file_data)

        if mime_type is None:
            # Undetectable MIME type — reject (fail closed for security)
            raise ValidationError(_(
                'Could not detect file type for "%s". '
                'The file may be corrupted or its type is not supported. '
                'Allowed types: %s'
            ) % (field_name, ', '.join(allowed_types)))

        # Special handling for ZIP files (DOCX/XLSX)
        if mime_type == 'application/zip':
            # Accept ZIP as it could be DOCX or XLSX
            return

        if mime_type not in allowed_types:
            raise ValidationError(_(
                'Invalid file type for "%s". '
                'Detected type: %s. '
                'Allowed types: %s'
            ) % (field_name, mime_type, ', '.join(allowed_types)))

    @api.constrains('document', 'sold_document', 'contract_agreement', 'file_name')
    def _validate_document_uploads(self):
        """Validate document field uploads (if model has these fields)"""
        for rec in self:
            # List of binary fields to validate
            binary_fields = {
                'document': ALLOWED_DOCUMENT_TYPES,
                'sold_document': ALLOWED_DOCUMENT_TYPES,
                'contract_agreement': ALLOWED_DOCUMENT_TYPES,
            }

            for field_name, allowed_types in binary_fields.items():
                if not hasattr(rec, field_name):
                    continue

                file_data = getattr(rec, field_name, None)

                if file_data:
                    try:
                        # Validate size
                        rec._validate_file_size(file_data, field_name)

                        # Validate MIME type
                        rec._validate_file_mime_type(file_data, field_name, allowed_types)

                    except ValidationError:
                        # Re-raise validation errors
                        raise
                    except Exception as e:
                        # Log other errors but don't block (fail open)
                        _logger.error(
                            f"Error validating {field_name} for {rec._name}: {str(e)}",
                            exc_info=True
                        )

    @api.constrains('image')
    def _validate_image_uploads(self):
        """Validate image field uploads (if model has image field)"""
        for rec in self:
            if not hasattr(rec, 'image'):
                continue

            file_data = getattr(rec, 'image', None)

            if file_data:
                try:
                    # Validate size
                    rec._validate_file_size(file_data, 'image')

                    # Validate MIME type (images only)
                    rec._validate_file_mime_type(file_data, 'image', ALLOWED_IMAGE_TYPES)

                except ValidationError:
                    # Re-raise validation errors
                    raise
                except Exception as e:
                    # Log other errors but don't block (fail open)
                    _logger.error(
                        f"Error validating image for {rec._name}: {str(e)}",
                        exc_info=True
                    )
