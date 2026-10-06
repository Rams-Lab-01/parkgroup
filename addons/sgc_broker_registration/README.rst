SGC Broker Registration & Compliance (Odoo 19)
==============================================


Public website onboarding for UAE real estate brokers (individual brokers and brokerage companies).


Applicant journey (no login needed)
-----------------------------------

1. ``/broker/register`` - type (company / individual), emirate / regulator, contact details.
2. Email verification - 6-digit code (hashed in the database, valid 10 min, max 5 attempts,
   60 s resend cooldown, 5 sends / hour).
3. ``/broker/application/<token>`` - registration numbers (trade licence, ORN, BRN, TRN, goAML,
   Emirates ID, IBAN - all format-validated), document upload (PDF / JPG / PNG, content-sniffed,
   10 MB default, expiry date required where the document type has one), download of the
   brokerage agreement to sign.
4. Declarations + typed e-signature (name, timestamp, IP stored) -> submit. Submission is blocked
   until every required document for that applicant type / emirate is present and in date.


Back office (Broker Registration app)
-------------------------------------

Start review -> accept / reject each document -> **Approve** (status becomes **Registered**, the
contact is created / updated, the brokerage agreement runs for **1 year from approval**),
Request information (applicant can fix and resubmit) or Reject. **Renew Agreement** extends it by the
configured validity (from the current expiry if still valid, otherwise from today).


Expiry monitoring and reminders
-------------------------------

Tracked for every registered broker: the brokerage agreement, trade licence, regulator registration /
broker card, and every accepted document that has an expiry date. A daily job (`Broker compliance:
expiry reminders`) sends, to the broker by email (plus optional extra recipients) and to the compliance
officers as an Odoo notification and a to-do:

* **Daily for the last 5 days before expiry** (5, 4, 3, 2, 1 days left);
* the **expired notice on the expiry date** (first day of expiration), when the contact status flips from
  Registered to **Expired**;
* then **every 15 days** until the date is renewed. Changing the date restarts the cycle and the contact is
  Registered again.
  Days and agreement length are configurable under Broker Registration > Settings. The Expiry Monitor
  menu lists everything expired or expiring in 30 days.


Mapping to Contacts
-------------------

Approval creates or updates the res.partner (matched by ORN, BRN, trade licence, VAT, then email):
legal data, TRN in the VAT field, "Registered Broker" tag, broker compliance tab (regulator, ORN,
BRN, licence and expiry, goAML, Emirates ID), the signatory as a child contact, the IBAN as a bank
account, and all accepted documents as attachments. If ``sgc_offplan_rental_property_management``
is installed the contact also gets ``user_type = broker``.


Configuration
-------------

* **Document Requirements** (Compliance Manager): add, remove or restrict requirements per
  applicant type and emirate. The seeded list is a reasonable default for Dubai / Abu Dhabi; have your
  compliance officer confirm it against the current regulator rules (DLD/RERA, ADREC, etc.).
* Upload limit, reminder days and agreement validity: Broker Registration > Settings.
* Outgoing mail server must be configured; verification emails are sent immediately.
* The agreement template (report ``Brokerage Agreement``) is generic: have legal counsel review and
  edit it before use.

Tests: ``odoo -d <db> -i sgc_broker_registration --test-tags /sgc_broker_registration --stop-after-init``
