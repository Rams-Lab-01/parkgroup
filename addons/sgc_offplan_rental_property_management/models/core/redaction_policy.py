# -*- coding: utf-8 -*-
# Copyright 2025 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.

"""Critical-Change Audit — Runtime redaction baseline (policy_version = 1).

Implements the fail-closed redaction policy of SGC_RENT_AUDIT_REDACTION_POLICY.md
(Rev 3, [C6]).  This Python module is the RUNTIME baseline.  The Markdown
document is human documentation only — a divergence between the two is a
defect.  Per-company overrides live in ``sgc.critical.audit.redaction.override``
and take precedence over this baseline.  Every audit event records the
``policy_version`` it was captured under.
"""

import re

from odoo import models

# Redaction classes — exact strings used by the override Selection too.
REDACTED_FULL = 'REDACTED_FULL'
REDACTED_PARTIAL = 'REDACTED_PARTIAL'
NOT_REDACTED = 'NOT_REDACTED'
SECRET_SCAN = 'SECRET_SCAN'
DISPLAY_PII = 'DISPLAY_PII'

POLICY_VERSION = 1

_BASELINE = {
    # --- §3.1 PII — REDACTED_FULL -------------------------------------------
    'res.partner': {
        'email': REDACTED_FULL,
        'phone': REDACTED_FULL,
        'mobile': REDACTED_FULL,
        'vat': REDACTED_FULL,
        'street': REDACTED_FULL,
        'street2': REDACTED_FULL,
        'zip': REDACTED_FULL,
        'city': REDACTED_FULL,  # free-text field; property.res.city M2O is not PII
        'iban': REDACTED_PARTIAL,  # §3.2, keep last 4
    },
    'rent.contract': {
        'tenant_id': REDACTED_FULL,    # integer id stored, display name never
        'landlord_id': REDACTED_FULL,  # integer id stored, display name never
        'monthly_rent': NOT_REDACTED,
        'annual_rent': NOT_REDACTED,
        'security_deposit': NOT_REDACTED,
    },
    'sale.contract': {
        'buyer_id': REDACTED_FULL,  # integer id stored, display name never
        'total_amount': NOT_REDACTED,
    },
    'rent.invoice': {
        'partner_id': REDACTED_FULL,      # integer id stored, display name never
        'payment_reference': REDACTED_PARTIAL,  # §3.2, last 4 kept
    },
    'rent.bill': {
        'partner_id': REDACTED_FULL,  # integer id stored, display name never
    },
    'account.move': {
        'partner_id': REDACTED_FULL,  # inherited; integer id, display name never
    },
    'account.move.line': {
        'partner_id': REDACTED_FULL,  # inherited; integer id, display name never
    },
    'res.partner.bank': {
        'acc_number': REDACTED_PARTIAL,  # §3.2, last 4 kept for cross-reference
    },
    # --- §3.3 Confidential pricing — REDACTED_FULL --------------------------
    # commission_percentage is value-dependent: REDACTED_FULL only when its
    # value exceeds the per-company threshold (baseline default 0% => always
    # redact).  The effective classification is resolved by the service.
    'property.commission.line': {
        'commission_percentage': REDACTED_FULL,
        'commission_amount': REDACTED_FULL,
    },
    'rent.commission.line': {
        'commission_percentage': REDACTED_FULL,
        'commission_amount': REDACTED_FULL,
    },
    'property.vendor.commission.line': {
        'commission_percentage': REDACTED_FULL,
        'commission_amount': REDACTED_FULL,
    },
}

# Models whose records are treated as PII-bearing for the display-name rule
# (P0-11): a reference to such a record renders ``[REDACTED-PII] {model} #{res_id}``
# and never its display name.  Derived from §3.1/§3.2 targets.
_PII_MODELS = frozenset([
    'res.partner',
    'res.partner.bank',
    'rent.contract',  # carries tenant/landlord PII refs
    'sale.contract',  # carries buyer PII refs
    'rent.invoice',
    'rent.bill',
    'account.move',
    'account.move.line',
])

# Configurable secret patterns used for SECRET_SCAN masking -> [REDACTED-SECRET]
# (§3.4 [C5], design §8.8).  Overridable per deployment via ir.config_parameter
# ``sgc_offplan_rental_property_management.audit_secret_patterns`` (newline-separated
# regex list).  Shapes: Emirates ID, IBAN, credit card, phone, e-mail,
# AWS access key / GitHub token.
DEFAULT_SECRET_PATTERNS = [
    # Emirates ID: 784-YYYY-NNNNNNN-N
    r'\b784[-\s]\d{4}[-\s]\d{7}[-\s]\d\b',
    # IBAN (AE + 2 digits + 3-4 bank + 16-21 alnum)
    r'\b[A-Z]{2}\s?\d{2}\s?[A-Z0-9]{4}\s?[A-Z0-9]{4}\s?[A-Z0-9]{4}\s?[A-Z0-9]{4}\s?[A-Z0-9]{1,7}\b',
    # Credit card (13-19 digits, optional spaces/dashes)
    r'\b(?:\d[ -]*?){13,19}\b',
    # UAE phone variants
    r'(?:\+971|00971|0)?\s?[256]\s?\d{3}[-\s]?\d{4}\b',
    # E-mail
    r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',
    # AWS access key
    r'\b(?:AKIA|ASIA)[0-9A-Z]{16}\b',
    # GitHub token
    r'\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,255}\b',
]

# Control chars stripped from reasons (§8.8).
_CONTROL_CHAR_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')


class CriticalAuditRedactionPolicy(models.AbstractModel):
    _name = 'sgc.critical.audit.redaction.policy'
    _description = 'Critical Audit Redaction Policy (runtime baseline)'

    # ------------------------------------------------------------------ API
    @classmethod
    def baseline(cls):
        """Deep-copy of the static baseline map (model -> field -> class)."""
        return {model: dict(fields_map) for model, fields_map in _BASELINE.items()}

    @classmethod
    def pii_models(cls):
        return set(_PII_MODELS)

    @classmethod
    def is_pii_model(cls, model_name):
        return model_name in _PII_MODELS

    @classmethod
    def is_secret_scan_field(cls, model_name, field_name):
        entry = _BASELINE.get(model_name, {}).get(field_name)
        return entry == SECRET_SCAN

    @classmethod
    def control_char_re(cls):
        return _CONTROL_CHAR_RE

    @classmethod
    def secret_patterns(cls, env):
        """Effective secret patterns: config parameter override or defaults."""
        param = env['ir.config_parameter'].sudo().get_param(
            'sgc_offplan_rental_property_management.audit_secret_patterns'
        )
        if param:
            patterns = [ln.strip() for ln in param.splitlines() if ln.strip()]
            if patterns:
                return patterns
        return list(DEFAULT_SECRET_PATTERNS)

    @classmethod
    def commission_threshold(cls, env, company_id):
        """Per-company commission redaction threshold (baseline default 0%).

        ``commission_percentage`` values above this threshold are classified
        REDACTED_FULL at capture time (value-dependent rule, applied by the
        internal service).  A company that wants a higher threshold must add an
        explicit redaction override for ``commission_percentage`` on that
        company — the override then short-circuits the baseline class entirely
        via :meth:`_effective_class`.
        """
        return 0.0

    # ------------------------------------------------------- policy resolution
    def _effective_class(self, model_name, field_name, company_id):
        """Override -> baseline -> None.  None means 'no policy entry'."""
        override = self.env['sgc.critical.audit.redaction.override'].sudo().search(
            [('company_id', '=', company_id),
             ('model', '=', model_name),
             ('field_name', '=', field_name)],
            limit=1,
        )
        if override:
            return override.redaction_class, override.policy_version
        entry = _BASELINE.get(model_name, {}).get(field_name)
        if entry is not None:
            return entry, POLICY_VERSION
        return None, POLICY_VERSION

    def resolve_class(self, model_name, field_name, company_id, observed=False):
        """Fail-closed resolution (P0-10).

        :param observed: True when the field is a tracked/critical field for the
            model at capture time.  An observed field with no policy entry
            resolves to REDACTED_FULL — never silently NOT_REDACTED.
        :returns: (redaction_class, policy_version)
        """
        cls, version = self._effective_class(model_name, field_name, company_id)
        if cls is None:
            if observed:
                return REDACTED_FULL, version
            return NOT_REDACTED, version
        return cls, version

    def validate_policy_version(self, requested_version=None):
        """Fail-closed guard: a capture under a mismatched policy is refused."""
        if requested_version is None:
            return POLICY_VERSION
        if requested_version != POLICY_VERSION:
            raise ValueError(
                'Audit policy_version mismatch: configured %s, expected %s'
                % (requested_version, POLICY_VERSION)
            )
        return requested_version