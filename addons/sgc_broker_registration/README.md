# SGC Broker Registration & Compliance (Odoo 19)

Public website onboarding for UAE real estate brokers (individual brokers and brokerage companies).

## Applicant journey (no login needed)
1. `/broker/register` - type (company / individual), emirate / regulator, contact details.
2. Email verification - 6-digit code (hashed in the database, valid 10 min, max 5 attempts,
   60 s resend cooldown, 5 sends / hour).
3. `/broker/application/<token>` - registration numbers (trade licence, ORN, BRN, TRN, goAML,
   Emirates ID, IBAN - all format-validated), document upload (PDF / JPG / PNG, content-sniffed,
   10 MB default, expiry date required where the document type has one), download of the
   brokerage agreement to sign.
4. Declarations + typed e-signature (name, timestamp, IP stored) -> submit. Submission is blocked
   until every required document for that applicant type / emirate is present and in date.

## Back office (Broker Registration app)
Start review -> accept / reject each document -> Approve (creates / updates the Contact),
Request information (applicant can fix and resubmit) or Reject. Daily cron alerts compliance
officers 30 days before a licence / regulator registration / document expires and flags the contact
as "Registration expired" once the trade licence lapses.

## Mapping to Contacts
Approval creates or updates the res.partner (matched by ORN, BRN, trade licence, VAT, then email):
legal data, TRN in the VAT field, "Registered Broker" tag, broker compliance tab (regulator, ORN,
BRN, licence and expiry, goAML, Emirates ID), the signatory as a child contact, the IBAN as a bank
account, and all accepted documents as attachments. If `sgc_offplan_rental_property_management`
is installed the contact also gets `user_type = broker`.

## Configuration
* **Document Requirements** (Compliance Manager): add, remove or restrict requirements per
  applicant type and emirate. The seeded list is a reasonable default for Dubai / Abu Dhabi; have your
  compliance officer confirm it against the current regulator rules (DLD/RERA, ADREC, etc.).
* Upload limit: system parameter `sgc_broker.max_upload_mb`.
* Outgoing mail server must be configured; verification emails are sent immediately.
* The agreement template (report `Brokerage Agreement`) is generic: have legal counsel review and
  edit it before use.

Tests: `odoo -d <db> -i sgc_broker_registration --test-tags /sgc_broker_registration --stop-after-init`
