# Pretty Events Management System — Claude Code Kickoff Prompt

Paste this into Claude Code in your project's root directory to start the engagement. It's split into stages so you can run it phase-by-phase rather than all at once — Claude Code will do better work if you let it plan before it codes.

**Stack decision:** Python + Django, single codebase — Django templates + a customized Django admin serve the dashboard directly (no separate Angular/API layer). This maximizes MVP speed and keeps deployment to one deployable unit.

**Infrastructure decision:** PostgreSQL is hosted on Neon (managed cloud Postgres, free tier) rather than run locally or as a container on the VPS — both local development and the production VPS connect to it via a connection string in `.env`. The VPS (~$46/yr) only runs Django + Gunicorn + Nginx. Domain via Namecheap. Version control is Git/GitHub.

**Timeline:** targeting a single weekend build (see the planning document's hour-by-hour schedule) rather than the full 4 weeks — treat the module order in Stage 4 as the priority order if time runs short, and let Reports or Client Communication storage slip before the Quotation→Invoice→Payment flow does.

---

## STAGE 0 — Context to paste first (once, at the top of your session)

```
I'm building a business management system for a client called "Pretty Events"
(an events/rentals company — tents, chairs, tables, décor). This is a paid
Phase 1 engagement (UGX 1,500,000 / 4 weeks) with a Phase 2 planned later.

Tech stack decision (already made, don't revisit): Python + Django, single
codebase. The dashboard is served via Django templates plus a customized
Django admin — no separate frontend framework, no separate REST API layer
unless a specific feature genuinely needs one (e.g. an AJAX endpoint for a
dynamic form). Use Django's built-in strengths (ORM, admin, forms, auth,
permissions) to move fast rather than reinventing them.

I'll give you the full feature spec, then walk you through planning,
architecture, implementation, and cloud deployment stage by stage. Don't
start writing code until I say "begin implementation."

FULL PHASE 1 SCOPE:
1. Customer & Event Management — register customers, contact details,
   create/manage events, event dates & locations, event status tracking
2. Quotations, Invoices & Receipts — create quotations, convert to invoices,
   generate receipts, record payments, print/download documents (PDF)
3. Basic Inventory & Equipment — register equipment (chairs, tents, tables,
   décor), quantities, availability tracking, issue items to events, basic
   return tracking
4. Income & Expenses — record income/expenses, categorize transactions,
   basic financial summaries
5. Staff Management — register staff, basic info, assign workers to events
6. Client Communication — basic SMS/contact setup, store contacts for
   future outreach
7. Reports — sales/income summary, expenses summary, outstanding payments,
   event summary, basic inventory summary

NOT in Phase 1 (design so these can bolt on later, but don't build them):
customer portal/login, online booking, online payments (mobile money/
cards), mobile app, advanced payroll, multi-branch, automated SMS/WhatsApp
notification engine, profit & loss / advanced analytics.

Deliverable includes: system design, UI/UX, admin dashboard, user accounts
(staff login, roles), testing, deployment, basic training handoff, and a
1-month post-launch bug-fix window — so the codebase needs to be clean
enough for someone else (or future-you) to maintain after handoff.
```

---

## STAGE 1 — Discovery & Requirements Planning

```
Before any architecture or code: act as a senior product/technical
consultant and turn the Phase 1 scope above into a concrete requirements
doc. Produce:

1. A list of user roles (e.g. Admin/Owner, Office Staff, Field Staff) and
   what each can see/do — flag where you're making an assumption so I can
   confirm with the client. Map these to Django's permissions/groups model.
2. Entities and their key fields (Customer, Event, Quotation, Invoice,
   Receipt, Payment, EquipmentItem, StockTransaction/Issue-Return, StaffMember,
   EventAssignment, IncomeRecord, ExpenseRecord, ExpenseCategory).
3. Core workflows as step-by-step sequences: quotation → invoice → receipt
   → payment; equipment issue → event → return; event lifecycle (Inquiry →
   Quoted → Confirmed → In Progress → Completed → Cancelled).
4. Open questions I need to clarify with Pretty Events before locking
   scope (e.g. multi-currency? single UGX only; single admin user or
   multiple staff logins from day one; do they need offline/low-connectivity
   support given intermittent power/internet is common for SMEs in Uganda).

Write this as a markdown requirements doc, not code yet.
```

*(Read what comes back, answer the open questions with the client if needed, then move on.)*

---

## STAGE 2 — Architecture (Django, single codebase)

```
Design the Django architecture for this system:

1. App structure — split into Django apps by domain (e.g. customers,
   events, billing, inventory, finance, staff, reports) rather than one
   monolithic app, so it stays maintainable after handoff.
2. Data models per app — fields, relationships (ForeignKey/M2M), and any
   model-level validation or computed properties (e.g. invoice balance
   due, equipment quantity available = total - currently issued).
3. Auth & permissions — use Django's built-in auth + Groups/Permissions
   for role-based access (Admin/Owner, Office Staff, Field Staff) rather
   than building custom RBAC from scratch.
4. Where templates suffice vs. where a small amount of JS/AJAX is worth
   it (e.g. live-searching a customer when creating a quotation, dynamic
   line-item rows on an invoice form) — keep this minimal and justified,
   not a shadow SPA.
5. PDF generation approach for quotations/invoices/receipts (e.g.
   WeasyPrint or similar — render from an HTML template so branding is
   easy to adjust).
6. Admin customization plan — which models get a fully custom-branded
   template view vs. which are fine as a well-configured Django admin
   screen (list_display, filters, inlines) for internal staff use.

Produce this as: the app list, model definitions (as actual models.py
code), and a short doc explaining the permission groups and PDF approach.
Don't wire up views/templates yet — this is the architecture review step.
```

---

## STAGE 3 — UI/UX Design

```
Design the dashboard UX for these modules: Dashboard/overview, Customers,
Events, Quotations/Invoices/Receipts, Inventory, Finance (Income/Expenses),
Staff, Reports.

For each module give me: the main list view (key columns, filters, search,
pagination), the create/edit form (fields, validation, grouping into
logical sections), and any secondary views (e.g. an event's detail page
showing its linked quotation/invoice/assigned equipment/assigned staff in
one place).

Design this as server-rendered Django templates with a clean, modern
look (a template base with a sidebar nav + top bar, consistent card/table/
form components reused across modules — not a raw default Django admin
look for the client-facing dashboard, even though internal admin screens
can lean on Django admin directly). Call out anywhere a simpler MVP
shortcut is reasonable given the 4-week timeline vs. where it's worth
doing properly the first time (e.g. the quotation→invoice→receipt
document flow is core to the brief — don't shortcut PDF formatting/
branding there).
```

---

## STAGE 4 — Implementation

```
Begin implementation. Build in this order so I always have something
demoable:
1. Project scaffold, Django apps skeleton, auth, permission groups, base
   template/layout/navigation
2. Customer & Event management (module 1)
3. Quotations → Invoices → Receipts → Payments (module 2, the revenue-
   critical path, including PDF generation)
4. Inventory/equipment register + issue/return tracking (module 3)
5. Income & Expenses (module 4)
6. Staff management + event assignment (module 5)
7. Client contact storage for future comms (module 6, no SMS sending yet
   — just structured storage that a Phase 2 SMS integration can use)
8. Reports (module 7) — pull from data already in the system using Django
   ORM aggregation (Sum, Count, annotate) rather than raw SQL where possible

After each module, stop and tell me what to test manually before moving on.
Use the secure env-var pattern I already use on Kanzu Finance projects —
CLAUDE.md instructions + .claude/settings.json deny rules so you can run
against secrets/.env (SECRET_KEY, DB credentials) without reading their
contents.
```

---

## STAGE 5 — Cloud Deployment Configuration

```
Now prepare deployment for a Django app using an external managed database
(Neon Postgres — not a local/containerized Postgres):
1. A Dockerfile and docker-compose.yml wiring up: Django app (Gunicorn)
   and Nginx (serving static/media files + reverse proxy) only — no
   Postgres container, since the database is Neon, reached via a
   connection string in the environment.
2. Production settings split (settings/base.py, settings/production.py)
   with env-var driven config (DEBUG off, ALLOWED_HOSTS with the real
   domain, DATABASE_URL pointed at Neon, SECRET_KEY).
3. A step-by-step deployment guide for a single small VPS (~$46/yr
   budget tier): server hardening basics (non-root sudo user, SSH-key-only
   login, ufw firewall allowing only 22/80/443, fail2ban), domain pointing
   via Namecheap DNS, TLS/HTTPS via Let's Encrypt/Certbot, running
   migrations against Neon, collectstatic, and basic uptime monitoring.
   Note that Neon's own backup/retention covers the database, so no
   local backup cron job is needed for it — just confirm what the free
   tier actually guarantees before relying on it as the sole copy of
   financial data.
4. A one-page runbook for Pretty Events' handoff: how to restart the
   service, where the database lives (Neon dashboard) and how backups
   work there, how to reset a staff password via Django admin, who to
   contact for the 1-month bug-fix window.

Keep the ops footprint minimal — this client won't have dedicated IT
staff maintaining it after handoff. A single lightweight VPS running
Django + Nginx via docker-compose, talking to Neon over the network, is
the target — not a multi-service cloud architecture.
```

---

### Notes for using this
- Run stages in order in the same Claude Code session so context carries over; don't skip straight to Stage 4.
- The requirements doc from Stage 1 is your best artifact to walk the client through before you touch code — it doubles as scope-confirmation for the milestone payment.
- Phase 2 items are deliberately excluded from the build but referenced in Stage 2 so the schema/architecture doesn't box you in later.
- Your Angular admin-UX skill file isn't used in this version since the dashboard is server-rendered Django templates — keep it on hand in case Phase 2 ever moves toward a separate SPA frontend (e.g. for a customer portal or mobile-facing views).
