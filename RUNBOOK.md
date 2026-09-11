# Pretty Events — Handoff Runbook

A one-page reference for whoever operates this system day-to-day after handoff.

## What this system is

A web app for managing Pretty Events' customers, events, quotations,
invoices, payments, equipment, staff, and finances. Staff log in with a
username and password at `https://yourdomain.com`.

## Where things live

| What | Where |
|---|---|
| Application code | GitHub repo (ask the developer for access) |
| Application server | The VPS — see hosting provider account |
| Database | [Neon](https://neon.tech) — managed Postgres, see the Neon dashboard for the project |
| Domain / DNS | Namecheap account |
| TLS certificate | Free, via Let's Encrypt — auto-renews via a cron job on the VPS |

## Common tasks

**Restart the app** (e.g. after it seems stuck):
```bash
ssh deploy@<vps-ip>
cd pretty_events
docker compose restart web
```

**View logs** (to see what went wrong):
```bash
docker compose logs -f web
```

**Reset a staff member's password**:
1. Log in as an Admin/Owner user.
2. Go to `/admin/` (the Django admin).
3. Under "Users", click the staff member, set a new password, save.

**Add a new staff login and assign their role**:
1. In `/admin/`, add a User (username + password).
2. Under "Groups", add them to one of: `Admin`, `Office Staff`, `Field Staff`.
3. If they're a field worker, also create a matching `StaffMember` record
   under Staff and link it to their User account so their event assignments
   show up correctly.

**Check database health / see raw data**: log into the Neon dashboard —
it has a SQL editor and shows connection/storage metrics.

**Where do backups live?** Neon retains its own backup/point-in-time
recovery for its managed database — check the current retention window on
the Neon dashboard for the plan in use. No separate local backup job is
running for the database.

## Who to contact

- **Development / bug fixes (1-month post-launch window)**: the developer
  who built this system — see the engagement contract for contact details.
- **Hosting/server issues**: your VPS provider's support.
- **Domain/DNS issues**: Namecheap support.
