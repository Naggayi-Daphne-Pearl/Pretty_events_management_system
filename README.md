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

## Roles

Run `python manage.py setup_groups` to create the three Phase 1 groups
(`Admin`, `Office Staff`, `Field Staff`) with model permissions already
assigned. Assign users to a group from `/admin/` (Users → edit → Groups).
Field Staff additionally only see events/issues they're assigned to — that
row-level scoping lives in view querysets, not just group permissions.

## Deployment

See `DEPLOYMENT.md` (VPS + Docker + Nginx + Neon + Let's Encrypt) and
`RUNBOOK.md` (day-to-day operations reference for handoff).
