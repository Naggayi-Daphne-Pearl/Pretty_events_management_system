# Pretty Events — Business Management System

Django (single codebase, server-rendered templates + Django admin) for
Pretty Events' Phase 1 scope: customers & events, quotations/invoices/
receipts/payments, equipment inventory, income & expenses, staff
management, client contact storage, and reports.

## Local development

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # defaults to sqlite locally; edit if pointing at Neon

python manage.py migrate
python manage.py setup_groups        # creates Admin / Office Staff / Field Staff groups
python manage.py createsuperuser
python manage.py runserver
```

Visit `http://127.0.0.1:8000/`.

PDF generation (quotations/invoices/receipts) uses WeasyPrint, which needs
Pango/Cairo installed natively:

```bash
brew install pango   # macOS
# or: apt-get install libpango-1.0-0 libpangocairo-1.0-0 libcairo2 (Debian/Ubuntu)
```

If those libs aren't available, PDF views fall back to plain HTML so the
document is still viewable — the Docker image installs them, so production
always gets real PDFs.

## App structure

- `core` — shared base model, branding context processor, dashboard, role/group setup command
- `customers` — customer records
- `events` — event lifecycle (Inquiry → Quoted → Confirmed → In Progress → Completed → Cancelled)
- `billing` — quotations, invoices, payments, receipts, PDF generation
- `inventory` — equipment register, issue/return tracking
- `finance` — income/expense records and summaries
- `staffing` — staff records and event assignments
- `comms` — structured client contact/communication log (no sending — a Phase 2 foundation)
- `reports` — cross-app ORM aggregation reports
- `accounting` — chart of accounts, double-entry journals, banking (cash / mobile money / bank accounts and transfers), trial balance, balance sheet and income statement. Cash basis: every income and expense record (including each invoice payment) posts its journal automatically; accountants add manual journals for assets, loans, capital, depreciation and opening balances.

## Logging in

Staff log in with their **email address**. New logins are created from the Staff
page. Sending email from the server is **off by default** (`EMAIL_ENABLED`): while
it's off, the admin sets each new login's first password and resets forgotten ones
from the staff page, and the "Email to Client" / "Forgot your password?" options are
hidden. With `EMAIL_ENABLED=True` and a mail provider configured (see `.env.example`),
new staff are emailed an invite link to choose their own password (links work once
and expire after 3 days) and "Forgot your password?" emails a reset link. Sessions end after 30 minutes idle, when the browser
closes, and in any case 12 hours after login (`SESSION_MAX_AGE_HOURS`). Five wrong
passwords lock that email out for 15 minutes. 
## Roles

`python manage.py setup_groups` (run automatically on every deploy) creates four
starter roles, `Admin`, `Office Staff`, `Field Staff` and `Accountant`, with sensible
permissions. Each default is applied only once, so roles and permissions changed
in **Administration → Roles & permissions** are kept on later deploys; `--reset`
puts the starter roles back. Give someone a role when creating their login on the
**Staff** page. Field Staff only see events they're assigned to (the
`view_assigned_events_only` permission, enforced in the views), and record loading
and returns from each event's phone job sheet.

## Daily jobs, taxes and other setup

- **Daily jobs** (event statuses, overdue invoices) run on the first request each
  day; no cron is required (see `DEPLOYMENT.md` §8).
- **Taxes** are set up under **Finance → Taxes** and chosen per quotation/invoice.
  Tax collected on payments posts to Taxes Payable (2100), not income.
- **Clearing test data** before go-live: `python manage.py reset_business_data`
  (dry run), then `--confirm`.

## Deployment

See `DEPLOYMENT.md` (VPS + Docker + Nginx + Neon + Let's Encrypt) and
`RUNBOOK.md` (day-to-day operations reference for handoff).
