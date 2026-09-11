# Pretty Events System — What It Does

A plain-language description of the Phase 1 system, organized by module. Use this to sanity-check scope with the client before or during the build — it's the "what," not the "how" (see the companion Claude Code prompt for implementation).

---

## 1. Customer & Event Management

**What staff can do:**
- Add a new customer with their name, phone number, and contact details
- Look up a customer and see every event they've booked, past and upcoming
- Create a new event tied to a customer: event type, date, venue/location, guest count
- Move an event through a status lifecycle: Inquiry → Quoted → Confirmed → In Progress → Completed → Cancelled
- See, at a glance, which events are coming up this week/month

**What this replaces:** scattered WhatsApp threads and notebooks used to remember who booked what and when.

---

## 2. Quotations, Invoices & Receipts

**What staff can do:**
- Build a quotation for an event: add line items (equipment, services, delivery/setup fee), quantities, and rates — the system calculates the subtotal and total automatically
- Convert an approved quotation into an invoice with one action, without re-typing the line items
- Record a payment against an invoice (full or partial) and generate a receipt for it
- Download or print a branded PDF of any quotation, invoice, or receipt to send to the client
- See at a glance which invoices are unpaid, partially paid, or overdue

**What this replaces:** hand-written or Excel-based quotes with no link between the quote, the eventual invoice, and what was actually paid.

---

## 3. Basic Inventory & Equipment

**What staff can do:**
- Maintain a register of every piece of equipment (tents, chairs, tables, décor items) with a total owned quantity
- See how many of each item are currently available vs. issued to an event
- Issue equipment to a specific event and record it as "out"
- Record equipment as returned after an event
- Get a simple low-stock view (e.g. "6 of 24 round tables still available") so double-booking equipment across events is avoidable

**What this replaces:** guessing whether enough chairs/tents are free for a new booking without checking a notebook or calling around.

---

## 4. Income & Expenses

**What staff can do:**
- Record income (usually tied to an invoice payment, but can also be logged standalone)
- Record expenses with a category (e.g. transport, wages, supplies, equipment repair)
- See a basic summary of income vs. expenses over a period (week/month)

**What this replaces:** paper receipts and a mental tally of what came in and went out.

---

## 5. Staff Management

**What staff can do:**
- Register a staff member/worker with basic contact info
- Assign specific staff to a specific event (who's working which event)
- See, per event, which staff are assigned

**What this replaces:** verbally telling workers where to show up, with no record anyone can check later.

---

## 6. Client Communication

**What staff can do:**
- Store a customer's contact details in one place, reliably reusable for outreach
- (Phase 1 stops here — no automated SMS/WhatsApp sending yet; that's a Phase 2 addition once this foundation exists)

**What this replaces:** contacts scattered across personal phones and old chat threads.

---

## 7. Reports

**What staff/management can see:**
- Sales/income summary over a chosen period
- Expenses summary over a chosen period
- Outstanding payments — which invoices are still unpaid and by how much
- Event summary — how many events, by status, over a period
- Basic inventory summary — what's owned, what's issued, what's available

**What this replaces:** management having to manually cross-reference notebooks, Excel files, and receipts to answer "how are we actually doing?"

---

## Who uses the system (roles)

- **Admin/Owner** — full access to everything, including finance and staff records
- **Office staff** — customers, events, quotations/invoices/receipts, inventory; limited or no access to sensitive financial summaries depending on what's confirmed with the client
- **Field staff** — likely view-only access to their own assigned events (confirm with client whether field staff need system access at all in Phase 1, or if this is office-only for now)

## Explicitly not in Phase 1

Customer login/portal, online booking, online payments (mobile money/cards), a mobile app, automated SMS/WhatsApp sending, multi-branch support, advanced payroll, profit & loss / advanced analytics. These are designed for so they can be added later without a rebuild, but none of them get built now.
