# -*- coding: utf-8 -*-
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
"""Install / upgrade hooks for AML Compliance.

Sanctions screening uses PostgreSQL trigram similarity (``set_limit`` /
``similarity``) for fuzzy name matching, which requires the ``pg_trgm``
extension. It is created idempotently here so a fresh database works out of the
box; the same statement also runs from
``migrations/19.0.1.0.2/post-migrate.py`` so existing databases pick it up on
upgrade.
"""
import logging

_logger = logging.getLogger(__name__)


def _ensure_pg_trgm(env):
    try:
        with env.cr.savepoint():
            env.cr.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')
        _logger.info('AML: pg_trgm extension is present.')
    except Exception:  # never block install/upgrade on a DB privilege issue
        _logger.warning(
            'AML: could not create the pg_trgm extension automatically '
            '(the database owner may need to run it once). Fuzzy sanctions '
            'screening relies on it.', exc_info=True)


def post_init_hook(env):
    _ensure_pg_trgm(env)
