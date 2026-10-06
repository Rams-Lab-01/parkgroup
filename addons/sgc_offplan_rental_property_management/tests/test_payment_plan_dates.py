# SPDX-License-Identifier: OPL-1
"""Payment-plan due dates are anchored to the first due date's day of month.

Operator-reported behaviour (20 Sept 2026): after the booking payment, a plan
whose first installment is due 10 Nov 2026 must continue on 10 Dec 2026,
10 Jan 2027, ... - the same day of every following month; likewise quarterly
(every 3 months), bi-annual (every 6) and annual (every 12). The previous
implementation added fixed day counts (30/90/180/365) to the contract date,
which drifts off the calendar: 30-day "months" move the day by one to two days
per year and 365-day "years" ignore leap years.

These tests assert the generated due dates themselves, including the
short-month clamp with the anchor day restored on the next step (31 Jan ->
28 Feb -> 31 Mar), and that single-installment lines keep their explicit
Days After Contract offset.
"""
from datetime import date

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install", "prop_payment_plan")
class TestPaymentPlanDates(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env["property.project"].create({
            "name": "PROP-PP Project",
            "company_id": cls.env.company.id,
        })
        cls.property = cls.env["property.details"].create({
            "name": "PROP-PP Property",
            "project_id": cls.project.id,
            "company_id": cls.env.company.id,
        })
        cls.buyer = cls.env["res.partner"].create({"name": "PROP-PP Buyer"})

    def _contract(self, contract_date, schedule_lines):
        schedule = self.env["payment.schedule"].create({
            "name": "PROP-PP Schedule",
            "schedule_type": "sale",
            "company_id": self.env.company.id,
            "schedule_line_ids": schedule_lines,
        })
        contract = self.env["sale.contract"].create({
            "name": "PROP-PP Contract",
            "property_id": self.property.id,
            "buyer_id": self.buyer.id,
            "sale_price": 1200000.0,
            "contract_date": contract_date,
            "payment_schedule_id": schedule.id,
        })
        contract.action_generate_installments()
        return contract

    def _dues(self, contract):
        return [i.due_date for i in contract.installment_ids.sorted("sequence")]

    # 1. Monthly: first due 10 Nov 2026 -> 10 Dec 2026, 10 Jan 2027, 10 Feb 2027.
    #    Under the old day-count arithmetic this was 10 Dec, 9 Jan, 8 Feb.
    def test_monthly_keeps_day_of_month(self):
        contract = self._contract(date(2026, 10, 10), [(0, 0, {
            "name": "Monthly", "percentage": 100.0, "days_after": 31,
            "installment_frequency": "monthly", "number_of_installments": 4,
        })])
        self.assertEqual(self._dues(contract), [
            date(2026, 11, 10), date(2026, 12, 10),
            date(2027, 1, 10), date(2027, 2, 10),
        ])

    # 2. Quarterly: every 3 calendar months on the same day (old: 90/180/270 days).
    def test_quarterly_keeps_day_of_month(self):
        contract = self._contract(date(2026, 10, 10), [(0, 0, {
            "name": "Quarterly", "percentage": 100.0, "days_after": 31,
            "installment_frequency": "quarterly", "number_of_installments": 4,
        })])
        self.assertEqual(self._dues(contract), [
            date(2026, 11, 10), date(2027, 2, 10),
            date(2027, 5, 10), date(2027, 8, 10),
        ])

    # 3. Bi-annual: every 6 calendar months on the same day (old: 180 days).
    def test_bi_annual_keeps_day_of_month(self):
        contract = self._contract(date(2026, 10, 10), [(0, 0, {
            "name": "Bi-Annual", "percentage": 100.0, "days_after": 31,
            "installment_frequency": "bi_annual", "number_of_installments": 2,
        })])
        self.assertEqual(self._dues(contract), [
            date(2026, 11, 10), date(2027, 5, 10),
        ])

    # 4. Annual: every 12 calendar months on the same day (old: 365 days, which
    #    drifts a day across a leap year).
    def test_annual_keeps_day_of_month(self):
        contract = self._contract(date(2026, 10, 10), [(0, 0, {
            "name": "Annual", "percentage": 100.0, "days_after": 31,
            "installment_frequency": "annual", "number_of_installments": 2,
        })])
        self.assertEqual(self._dues(contract), [
            date(2026, 11, 10), date(2027, 11, 10),
        ])

    # 5. Short months clamp to their last day and the anchor day is restored on
    #    the next step (day comes from the first due date, not the previous one).
    def test_short_month_clamps_and_anchor_restores(self):
        contract = self._contract(date(2027, 1, 1), [(0, 0, {
            "name": "Month-end", "percentage": 100.0, "days_after": 30,
            "installment_frequency": "monthly", "number_of_installments": 3,
        })])
        self.assertEqual(self._dues(contract), [
            date(2027, 1, 31), date(2027, 2, 28), date(2027, 3, 31),
        ])

    # 6. Single-installment lines are unchanged: due = contract_date + days_after.
    def test_single_installment_unchanged(self):
        contract = self._contract(date(2026, 10, 10), [(0, 0, {
            "name": "One time", "percentage": 100.0, "days_after": 45,
            "installment_frequency": "one_time", "number_of_installments": 1,
        })])
        self.assertEqual(self._dues(contract), [date(2026, 11, 24)])

    # 7. A plan line with a frequency but number_of_installments == 1 must be
    #    treated as a single installment on the anchor date (no phantom split).
    def test_frequency_with_single_installment_is_one_date(self):
        contract = self._contract(date(2026, 10, 10), [(0, 0, {
            "name": "Monthly once", "percentage": 100.0, "days_after": 31,
            "installment_frequency": "monthly", "number_of_installments": 1,
        })])
        self.assertEqual(self._dues(contract), [date(2026, 11, 10)])
