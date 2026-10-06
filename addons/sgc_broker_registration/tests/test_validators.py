from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

from ..models import broker_application as ba


@tagged('post_install', '-at_install')
class TestValidators(TransactionCase):

    def test_email(self):
        self.assertEqual(ba.normalize_email('  A.B@Example.COM '), 'a.b@example.com')
        for bad in ('', 'a@b', 'no-at.com', 'a b@c.com'):
            with self.assertRaises(ValidationError):
                ba.normalize_email(bad)

    def test_phone(self):
        self.assertEqual(ba.normalize_phone('+971 50 123 4567'), '+971501234567')
        self.assertEqual(ba.normalize_phone('0501234567'), '+971501234567')
        self.assertEqual(ba.normalize_phone('00971501234567'), '+971501234567')
        for bad in ('123', 'abc', '+1234567890123456789'):
            with self.assertRaises(ValidationError):
                ba.normalize_phone(bad)

    def test_emirates_id(self):
        self.assertEqual(ba.normalize_emirates_id('784199012345671'), '784-1990-1234567-1')
        self.assertEqual(ba.normalize_emirates_id('784-1990-1234567-1'), '784-1990-1234567-1')
        for bad in ('123456789012345', '78419901234567', '784-1990-1234567-A'):
            with self.assertRaises(ValidationError):
                ba.normalize_emirates_id(bad)

    def test_trn(self):
        self.assertEqual(ba.normalize_trn('100 1234 5678 9012'.replace(' ', '')), '100123456789012')
        for bad in ('12345', '10012345678901A', '1001234567890123'):
            with self.assertRaises(ValidationError):
                ba.normalize_trn(bad)

    def test_iban(self):
        self.assertEqual(ba.normalize_iban('AE07 0331 2345 6789 0123 456'), 'AE070331234567890123456')
        with self.assertRaises(ValidationError):
            ba.normalize_iban('AE07 0331 2345 6789 0123 457')      # bad check digits
        with self.assertRaises(ValidationError):
            ba.normalize_iban('AE12345')                            # too short

    def test_registration_numbers(self):
        self.assertEqual(ba.normalize_registration_no(' 12345 ', 'ORN'), '12345')
        for bad in ('12', 'ABC123', '12345678901'):
            with self.assertRaises(ValidationError):
                ba.normalize_registration_no(bad, 'ORN')
