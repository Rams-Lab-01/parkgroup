from odoo.tests.common import HttpCase, tagged

from .common import EoiCommon


@tagged('post_install', '-at_install', 'sgc_eoi_pdf')
class TestEoiPdf(EoiCommon, HttpCase):
    """Real wkhtmltopdf rendering (needs the HTTP layer for the report assets)."""

    def test_real_pdfs(self):
        eoi = self.new_eoi()
        eoi.action_confirm()
        _e = self.new_eoi()
        _e.action_confirm()
        _e.action_convert_to_booking()
        booking = _e.booking_id
        for xmlid, rec in (('sgc_property_eoi.action_report_property_eoi', eoi),
                           ('sgc_property_eoi.action_report_booking_confirmation', booking)):
            report = self.env.ref(xmlid).with_context(force_report_rendering=True)
            pdf, _t = report._render_qweb_pdf(report.report_name, rec.ids)
            self.assertTrue(pdf.startswith(b'%PDF'))
            self.assertGreater(len(pdf), 3000)

    def test_visual_scenarios(self):
        """Edge-case documents. Set SGC_EOI_PDF_DUMP=/dir to keep the PDFs for visual QA."""
        import os
        dump = os.environ.get('SGC_EOI_PDF_DUMP')
        long_name = 'Abdulrahman Mohammed Bin Rashid Al Maktoum Al Suwaidi Al Nuaimi ' * 2
        arabic = self.env['res.partner'].create({
            'name': 'عبدالله محمد الشامسي', 'street': 'شارع الشيخ زايد، دبي', 'email': 'a@example.ae',
            'phone': '+971 50 123 4567'})
        long_p = self.env['res.partner'].create({'name': long_name, 'street': 'Very long street name ' * 8})
        cases = {
            'minimal': dict(partner_id=self.customer.id, amount=0),
            'arabic': dict(partner_id=arabic.id, amount=25000, payment_mode='cheque',
                           payment_reference='CHQ-000123', joint_partner_id=long_p.id,
                           joint_nationality='UAE', joint_passport_no='X1234567'),
            'long': dict(partner_id=long_p.id, amount=987654321.55, notes='n ' * 200,
                         purchaser_address='Building 12, ' * 20),
        }
        company = self.env.company
        company.sgc_eoi_terms = '\n'.join('Clause %s: %s' % (i, 'The purchaser agrees to the stated terms. ' * 6)
                                          for i in range(1, 16))
        for key, vals in cases.items():
            unit = self.new_unit(name='Penthouse ' + key, parking='2 covered', view_description='Sea & Skyline')
            eoi = self.new_eoi(unit, **vals)
            eoi.action_confirm()
            if vals.get('amount'):
                self.pay(eoi, min(vals['amount'], 12345.5))
            eoi.action_convert_to_booking()
            for rec, xmlid in ((eoi, 'sgc_property_eoi.action_report_property_eoi'),
                               (eoi.booking_id, 'sgc_property_eoi.action_report_booking_confirmation')):
                report = self.env.ref(xmlid).with_context(force_report_rendering=True)
                pdf, _t = report._render_qweb_pdf(report.report_name, rec.ids)
                self.assertTrue(pdf.startswith(b'%PDF'))
                if dump:
                    with open('%s/%s_%s.pdf' % (dump, key, 'eoi' if rec._name == 'property.eoi' else 'booking'), 'wb') as f:
                        f.write(pdf)
