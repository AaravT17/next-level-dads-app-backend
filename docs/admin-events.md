# Admin Organization Events

## Overview

Adds admin tooling to review organization-hosted event applications.

### Frontend

- `/admin/events` — Events list with metrics, filters, and status actions
- `/admin/organization-events/:eventId` — review page to approve, deny, return to pending, and save admin notes

### Backend

- `GET /api/organizations-events/` — list + metrics
- `GET /api/organizations-events/{event_id}` — single application detail
- `PATCH /api/organizations-events/{event_id}/decision` — update status and/or admin notes

All endpoints and pages are **admin-only**.

---

## Status values

DB enum `application_status`:

| DB value | UI label |
|----------|----------|
| `pending` | Pending |
| `approved` | Approved |
| `rejected` | Denied |

The Deny button sends `rejected` to match the database.

---

## Backend details

### `GET /api/organizations-events/`

Returns:

```json
{
  "metrics": {
    "total_rsvps_active": 0,
    "dads_attended_completed": 0,
    "event_attendance_rate": 0,
    "repeat_attendee_rate": 0
  },
  "events": [],
  "organizations": []
}
Optional query params:

search
region
organization
format
category
status

Notes:

Only events with hosted_by_org_id IS NOT NULL
RSVP count from event_attendees
format currently maps from events.type (local / virtual)
region currently maps from events.location
category not yet in DB
Attendance / repeat metrics are partial placeholders until richer data exists

GET /api/organizations-events/{event_id}
Returns full event row for org-hosted events.
PATCH /api/organizations-events/{event_id}/decision
Body:
JSON{
  "status": "pending | approved | rejected",
  "admin_notes": "optional string",
  "decision_message": "optional string"
}
Behavior:

Updates app_status
Updates admin_notes JSON when notes are provided
Stores note metadata (text, created_by, created_at, updated_at)


Frontend details
Events page (AdminEventsPage)

Metric cards
Search + filters
Table of organization events
Status button opens the review page
rejected is displayed as Denied

Review page (OrganizationEventApprovalPage)

Event details
Admin notes textarea
Actions:
Save Notes — updates notes only; keeps current status
Return to Pending — sets status to pending
Approve — sets approved
Deny — sets rejected

Parses admin_notes whether the API returns an object or JSON string


Auth

Backend: Depends(get_admin_user)
Frontend: routes wrapped in AdminRoute


How to test

Log in as an admin
Open /admin/events
Confirm list and metrics load
Open an event
Save notes, leave, reopen → notes persist
Approve → status becomes approved
Return to Pending → status becomes pending
Deny → DB stores rejected, UI shows Denied
Logged-out user visiting /admin/events should be redirected to login


Known limitations / follow-ups

Shared admin sidebar/top bar not included (expected from separate admin shell work)
Region/category/format filters are best-effort with current schema
Attendance and repeat-attendee metrics need richer attendance tracking
Notification/messaging on status change not implemented yet
decision_message is accepted by the API but notification send is not wired