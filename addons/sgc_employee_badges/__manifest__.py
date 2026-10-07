# -*- coding: utf-8 -*-
{
    "name": "SGC Employee Achievement Badges",
    "version": "19.0.1.2.0",
    "summary": "72 premium navy-and-gold milestone badges for employee recognition",
    "description": """
SGC Employee Achievement Badges
===============================
Adds 72 ready-to-award gamification badges for recognising employee milestones
across Sales, Performance, Teamwork, Skills, Operations, Analytics, Technology,
Leadership and Tenure. Grant them from Employees > Gamification > Badges or from
an employee's profile (Send Badge).

Also wires badges to real karma points (point_value on gamification.badge,
added to the recipient's karma on grant), auto-awards a Rank Promotion badge
when a user's karma rank changes, tracks lead revival (x_revived_by_id /
x_revived_date on crm.lead) for the Growth Driver badge, and computes a
gamification start date for new hires (next Monday on/after date_start) so
weekly/monthly challenges don't penalize a partial first week.
""",
    "category": "Human Resources/Gamification",
    "author": "SGC TECH AI",
    "website": "https://sgc-tech.ai",
    "maintainer": "SGC TECH AI",
    "license": "LGPL-3",
    "depends": ["gamification", "hr_gamification", "crm"],
    "data": [
        "data/gamification_badge_data.xml",
        "views/leaderboard_templates.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
