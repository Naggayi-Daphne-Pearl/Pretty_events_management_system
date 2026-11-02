# Pretty Events — Handoff Runbook

A short reference for whoever runs the system day to day after handover.

## What this system is

A web app for Pretty Events' customers, events, quotations, invoices, payments,
equipment, staff and finances. Staff sign in with their **email address** and
password at `https://management.prettyeventslimited.co.ug`. On phones it can be
installed to the home screen (browser menu → *Install app* / *Add to Home Screen*).

## Where things live

| What | Where |
|---|---|
| Application code | GitHub: `Pretty_events_management_system` (ask the developer for access) |
| App hosting | [Railway](https://railway.app), project **stellar-appreciation**, environment **production** |
| Database | Railway Postgres service in the same project |
| Domain / DNS | Namecheap (CNAME `management` → Railway) |
| HTTPS certificate | Issued and renewed automatically by Railway |

## Common tasks

**Give someone a login, or change their role**
1. Sign in as the owner (superuser).
2. **Staff** → open the person (or add them) → create their login and pick a role.
3. Roles and what each can do: **Administration → Roles & permissions**. Changes
   made there are kept when the app is updated.

**Reset someone's password**: **Staff** → the person → *Set password directly*. (With email
switched on, they can also use *Forgot your password?* on the sign-in page.)

**Lock someone out**: **Staff** → the person → *Edit* → under *System login*, untick **Active**.

**Set up or change taxes (e.g. VAT)**: **Finance → Taxes**. Changing a rate only
affects documents created afterwards; issued quotations and invoices keep theirs.

**Close a month's books**: **Finance → Close books**. Nothing dated in a closed
period can be changed; corrections go in as a reversal in an open period.

**See who did what**: **Administration → Activity log** (can be exported to CSV).

**Restart the app** if it seems stuck: Railway → the web service → **Deployments**
→ latest → ⋮ → **Restart**.

**View error logs**: Railway → the web service → **Deployments** → latest → **View logs**.

**Clear test data** (only before going live): Railway → web service → **Console**,
take a backup first (below), then:
```bash
python manage.py reset_business_data            # shows what would be deleted
python manage.py reset_business_data --confirm  # deletes it
```

## Backups

Railway keeps backups of the Postgres service according to the plan in use;
check **Postgres service → Backups**. For an extra copy, run from a computer with
the Postgres tools installed (the address is `DATABASE_PUBLIC_URL` under the
Postgres service's **Variables**):
```bash
pg_dump "<DATABASE_PUBLIC_URL>" > pretty-events-YYYY-MM-DD.sql
```
Keep these copies somewhere other than Railway, and test restoring one now and then.

## Things that run by themselves

- **Each morning** (on the first visit of the day): events move to In Progress /
  Completed by date, and unpaid invoices past their due date become Overdue.
- **Every update**: database changes are applied, and new starter permissions
  are added without undoing changes made in Roles & permissions.

## Who to contact

- **Development / bug fixes**: the developer who built this system (see the
  engagement contract for contact details and the support window).
- **Hosting**: Railway support. **Domain/DNS**: Namecheap support.
