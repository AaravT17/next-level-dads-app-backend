# Notification Centre & Banner Notifications

Design document for the notification centre and in-app banner notification system.

---

## Overview

Two notification surfaces:

1. **Notification centre** — persistent, accessed via a bell icon in the top-right header. Shows a chronological history of events the user may have missed. Backed by a `notifications` DB table.
2. **Banner notifications** — transient, full-width banners that slide down from the top of the viewport for real-time events. Ephemeral (not stored).

Both surfaces are driven by the same WebSocket events and share suppression logic (e.g., don't notify for your own actions). Banners cover a superset of notification centre events — message banners are banner-only (no centre entry). No dedicated "notification" event type on the wire — the frontend fans out existing events to whichever surfaces need them.

---

## Scope

### Notification centre events (persistent)

| Type                            | Text                                        | On tap                |
| ------------------------------- | ------------------------------------------- | --------------------- |
| `connection_request`            | **{Name}** sent you a connection request    | → requester's profile |
| `connection_accepted`           | **{Name}** accepted your connection request | → accepter's profile  |
| `chat_added` (group chats only) | **{Name}** added you to **{Chat Name}**     | → that group chat     |

### Banner events (transient)

All notification centre events above, plus:

| Type              | Title (bold)  | Content                                | On tap      |
| ----------------- | ------------- | -------------------------------------- | ----------- |
| New DM message    | {Sender name} | {message content}                      | → that chat |
| New group message | {Chat name}   | {Sender first name}: {message content} | → that chat |

### Excluded

- **Individual message notifications in the centre** — messages already have the chat nav badge and per-chat unread indicators. Including them in the centre would create noise and redundancy.
- **DM created** — the chat appearing in the chat list + the first message banner covers this. `chat_added` notifications and banners are for group chats only.
- **Moderation notifications** — separate system with different concerns (compliance, acknowledgement). Remains independent.

---

## Database

### `notifications` table

```sql
CREATE TABLE notifications (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type            TEXT NOT NULL,       -- 'connection_request', 'connection_accepted', 'chat_added'
    payload         JSONB NOT NULL,      -- type-specific display data (actor name, avatar, chat name, etc.)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_notifications_user_created
ON notifications (user_id, created_at DESC);
```

No `is_read` column — read state is timestamp-based (see below).

**Future note:** When batchable events are added (e.g., "you received 12 likes on your post"), add a `group_key TEXT` column to support upserts via `INSERT ... ON CONFLICT (user_id, group_key) WHERE ... DO UPDATE`. `updated_at` is already in place for this.

Notification rows are never created for the actor who performed the action (e.g., the user who sent the request does not get a notification for their own request).

### Payload shapes

```jsonc
// connection_request
{ "from_id": "uuid", "from_name": "John", "from_avatar_url": "..." }

// connection_accepted
{ "by_id": "uuid", "by_name": "John", "by_avatar_url": "..." }

// chat_added
{ "chat_id": "uuid", "chat_name": "Dads Who Code", "chat_type": "group", "chat_avatar_url": null, "added_by": "uuid", "added_by_name": "John" }
```

### `user_notification_state` table

```sql
CREATE TABLE user_notification_state (
    user_id         UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    last_read_at    TIMESTAMPTZ,
    last_cleared_at TIMESTAMPTZ
);
```

- **`last_read_at`** — set to `NOW()` when the user opens the notification centre. Everything created before this timestamp is considered "read." Controls the unread badge count.
- **`last_cleared_at`** — set to `NOW()` when the user clicks "Clear all." Notifications created before this are hidden from the centre.

Separate from `user_preferences` because these are operational timestamps, not user preferences. Separate from `users` to avoid write contention on a hot table. Same pattern as `chat_participants` holding `last_read_at` for chat read state.

### Read/unread mechanics

- **Unread count**: `SELECT COUNT(*) FROM notifications WHERE user_id = $1 AND created_at > COALESCE(last_read_at, epoch) AND created_at > COALESCE(last_cleared_at, epoch)`
- **No per-notification `is_read`** — opening the centre marks everything read in one write. No N-write fan-out.
- **Monotonic updates** — all timestamp writes use `GREATEST(COALESCE(col, NOW()), NOW())` so a concurrent or delayed request can never regress the value.
- **Clear all** sets both `last_read_at` and `last_cleared_at` (same GREATEST pattern).

---

## API

### `GET /api/users/me` (updated)

`MeResponse` now includes a `notification_state` object:

```jsonc
{
  // ... existing fields ...
  "notification_state": {
    "last_read_at": "2026-09-15T10:00:00Z",   // null if never read
    "last_cleared_at": "2026-09-14T08:00:00Z"  // null if never cleared
  }
}
```

Sourced via `LEFT JOIN user_notification_state`. The frontend stores these on the auth user object and updates them via WS events using max-comparison logic (never regresses).

### `GET /api/notifications?cursor_created_at={created_at}&cursor_id={id}&limit=20`

Returns notifications where `created_at > GREATEST(COALESCE(last_cleared_at, epoch), NOW() - INTERVAL '30 days')`, ordered by `created_at DESC`, keyset-paginated by `(created_at, id)`.

**Future note:** When batchable events are added, sort by `updated_at` so bumped notifications surface to the top. Bumps arrive via WebSocket — if the notification is already in the cache, update it and move it to the top (dedup by ID, same pattern as message dedup).

### `GET /api/notifications/count`

Lightweight endpoint returning just the unread count. Used during app hydration for the bell badge.

---

## WebSocket Changes

### New outbound event types (server → client via `user:{user_id}`)

| Event                   | Payload                                                                    | Published by          |
| ----------------------- | -------------------------------------------------------------------------- | --------------------- |
| `connections:request`   | `{ from_id, from_name, from_avatar_url, notification_id?, notification_created_at? }` | connections service   |
| `connections:accepted`  | `{ by_id, by_name, by_avatar_url, notification_id?, notification_created_at? }`       | connections service   |
| `notifications:read`    | `{ last_read_at }`                                                         | WS router (broadcast) |
| `notifications:cleared` | `{ last_read_at, last_cleared_at }`                                        | WS router (broadcast) |

`notification_id` and `notification_created_at` are present when the notification was successfully persisted. The frontend uses them for cache insertion and badge count — if absent (DB insert failed), the notification is skipped in the centre and the badge is not incremented. The WS event is still published regardless so query invalidations (connection requests, stats, etc.) fire either way.

### Updated outbound event payloads

| Event          | Added fields                                                             |
| -------------- | ------------------------------------------------------------------------ |
| `messages:new` | `chat_name`, `chat_type`, `chat_avatar_url`                              |
| `chats:added`  | `added_by`, `added_by_name`, `chat_name`, `chat_type`, `chat_avatar_url` |

`chat_avatar_url`: null for now (no group avatars yet). Banner avatar logic: frontend checks `chat_type` — DM uses `sender_avatar_url` (already in `MessageResponse`), group uses `chat_avatar_url` with a default fallback. When group avatars are introduced, `chat_avatar_url` will populate for groups with no payload changes needed.

### New inbound message types (client → server)

| Type                    | Purpose                             |
| ----------------------- | ----------------------------------- |
| `notifications:read`    | User opened the notification centre |
| `notifications:cleared` | User clicked "Clear all"            |

Backend receives these, updates `user_notification_state`, and re-publishes to `user:{user_id}` for cross-session sync.

### Rate limiting

Refactor from a single shared limiter to per-event-type limiters with independent budgets:

| Event type              | Rate limit | Context key             |
| ----------------------- | ---------- | ----------------------- |
| `chats:read`            | 3 per 5s   | `chats:read`            |
| `notifications:read`    | 3 per 10s  | `notifications:read`    |
| `notifications:cleared` | 3 per 60s  | `notifications:cleared` |

Each type gets its own `WebSocketRateLimiter` instance with a per-user Redis key (`ws:{user_id}:{context_key}`). Dispatch based on `msg.get('type')` before applying the relevant limiter.

---

## Real-Time Delivery Flow

### Notification-worthy events (connection request example)

```
1. User A sends connection request to User B
2. connections/service.py:
   a. INSERT into connections table (status='pending')
   b. INSERT into notifications table (type='connection_request', user_id=B, payload={...})
   c. publish('user:{B}', { type: 'connections:request', payload: {from_id, from_name, from_avatar_url, notification_id, notification_created_at} })
3. User B's frontend receives the event:
   a. Invalidate ['connections', 'requests'] and ['user', 'stats'] query caches
   b. If notification_id present: insert notification into cache using server ID, increment badge
   c. Show banner (if banners enabled)
```

### Cross-session sync (mark read example)

```
1. User opens notification centre in Session A
2. Session A sends WS message: { type: 'notifications:read' }
3. Session A optimistically sets bell badge to 0
4. Backend updates last_read_at = NOW() in user_notification_state
5. Backend publishes { type: 'notifications:read', payload: { last_read_at } } to user:{id}
6. Session B receives event → invalidates notification count query → badge zeroes out
```

---

## Frontend: Event Buffering

Expand the existing event buffer to cover notification events during app hydration:

1. WebSocket connects → `ws:ready`
2. Fetch chat memberships AND notification count in parallel
3. Buffer ALL incoming events (chat events + `connections:request`, `connections:accepted`, `chats:added`) during both fetches
4. Drain buffer once **both** resolve — each event processed through the same handler as live events

Scope of the existing buffer widens; the drain condition changes from "memberships resolved" to "memberships AND notifications resolved."

---

## Frontend: Notification Centre UI

### Unread badges (consistent across app)

All unread count badges use the same style: red circle with white number, capped at 99+. Applied to:

- **Bell icon** (notification centre) — unread notification count
- **Chat nav icon** — unread chat count
- **Account button** — pending connection request count

### Bell icon

- Top-right header, next to the account button
- Unread count sourced from hydration fetch (count endpoint), then maintained locally (increment on WS event, reset to 0 on open)

### Panel

- Popover dropdown anchored to the bell icon (~380px on desktop, right-side sheet on mobile)
- Fade in + slide down animation, ~200ms
- Header: "Notifications" title + "Clear all" button
- List: chronological (newest first), each card is a full-width tap target
- Card layout: avatar left, text with bold names, relative timestamp right
- Timestamps: "Just now" (<1m), minutes (<1h), hours (<24h), days (<7d), then date
- Empty state: "You're all caught up"
- Pagination: load more on scroll (keyset cursor)
- Closes on: click outside, press bell again, or navigate away

### On open

- Snapshot `user.notificationState.lastReadAt` at mount time (before marking read)
- Optimistically set badge count to 0
- Send `notifications:read` WS message → backend updates `last_read_at`
- New (unread) notifications get a subtle background highlight so they stand out visually
- A thin divider line separates the last new notification from the first previously-seen one
- If all notifications are previously seen (nothing new), no line or highlight — plain list
- If all notifications are new (`lastReadAt` is null or everything is newer), all highlighted, no line

### On "Clear all"

- Button hidden when notification list is empty
- Optimistically clear notification query cache
- Send `notifications:cleared` WS message → backend updates `last_read_at` and `last_cleared_at`

### Unread count management

- On new notification-worthy WS event: increment count locally (+1) only when the event includes `notification_id` (confirming the notification was persisted)
- On open: optimistically set to 0 (before server confirms)
- If a new event arrives while the centre is open, count increments normally (acceptable edge case — unlikely in practice, and opening the centre again corrects it)

### Cross-session sync

- `notifications:read` event received → invalidate count query. Initiating session already set count to 0 optimistically; other sessions refetch and zero out.
- `notifications:cleared` event received → clear notification cache and invalidate count query. Initiating session already cleared optimistically; other sessions clear and refetch.

### Cache insertion on WS event

Same pattern as message cache insertion: if the notification's insert position is not at the end of the cached pages, insert it directly. If it would go at the end, invalidate the cache instead. If the cache does not exist or is not initialised yet, do nothing.

### Query invalidations on events

| Event received          | Invalidate                                                                        |
| ----------------------- | --------------------------------------------------------------------------------- |
| `connections:request`   | `['connections', 'requests']`, `['user', 'stats']`                                |
| `connections:accepted`  | `['connections']`, `['connections', 'requests']`, `['user', 'stats']`, `['dads']` |
| `chats:added`           | (existing behaviour — fetch chat preview, add to cache)                           |
| `notifications:read`    | notification count query                                                          |
| `notifications:cleared` | notification cache, notification count query                                      |

---

## Frontend: Banner Notifications

### Implementation

Built on **Sonner** with a dedicated `<Toaster>` instance (separate from the existing system/moderation toaster):

- `position="top-center"`
- `visibleToasts={3}` — stacked (card-deck style), newest at front
- `unstyled={true}` with custom full-width styling
- Auto-dismiss after ~4 seconds, pause on hover
- Clickable — navigates to the relevant destination

### Banner content per type

| Type                | Title (bold header) | Content                                     | Avatar           |
| ------------------- | ------------------- | ------------------------------------------- | ---------------- |
| New DM message      | {Sender name}       | {message content}                           | Sender's avatar  |
| New group message   | {Chat name}         | {Sender first name}: {message content}      | Default group    |
| Connection request  | Connection Request  | **{Name}** sent you a connection request    | Requester avatar |
| Accepted connection | New Connection      | **{Name}** accepted your connection request | Accepter avatar  |
| Added to group chat | {Chat name}         | **{Name}** added you                        | Default group    |

### Message burst handling (same chat)

- Use `chat:{chat_id}` as the Sonner toast ID
- Subsequent messages in the same chat update the existing banner's content (latest message preview) and reset the dismiss timer
- No message count — always show latest content

### Reordering on update

When a banner updates (e.g., new message for an existing banner further back in the stack), dismiss the old toast and recreate it so it appears at the front: `toast.dismiss(id)` → `toast(newContent, { id })`.

### Suppression rules

- **Active chat**: Don't show message banners for the chat the user is currently viewing
- **Own messages**: Don't banner `sender_id === currentUserId`
- **Own actions for `chats:added`**: Don't banner or create notification if `added_by === currentUserId`
- **Banners disabled**: User preference toggle (localStorage)

**TODO:** Consider suppressing banners while the notification centre panel is open if it feels noisy in practice.

### User preference

- Toggle in the existing preferences/settings page
- Stored in **localStorage** only (no backend persistence — purely a display preference)
- Read on app launch to determine if banners are enabled

---

## Chat Page Error Handling (prerequisite fix)

The chat page (`Chat.tsx`) currently does not handle 403/404 errors from the chat detail or messages queries. If a user taps a stale "added to chat" notification after being removed, they see a broken/empty chat interface.

**Fix:** Destructure `error`/`isError` from the chat queries. On 403/404, redirect to the chat list and show a toast: "This chat is no longer available." Other pages (e.g., `EventDetail.tsx`) already follow this pattern.

---

## Docs to update

- **`docs/pubsub_design.md`**: Update the events table with new event types (`connections:request`, `connections:accepted`, `notifications:read`, `notifications:cleared`), updated payloads for `messages:new` and `chats:added`, new inbound message types, and per-type rate limiting.

---

## Implementation order

1. **Migration**: `notifications` table + `user_notification_state` table
2. **Backend: notifications module** — models, service (create, list, count), router (`GET /api/notifications`, `GET /api/notifications/count`)
3. **Backend: WS payload enrichment** — add `chat_name`, `chat_type`, `chat_avatar_url` to `messages:new`; add `added_by`, `added_by_name`, `chat_name`, `chat_type`, `chat_avatar_url` to `chats:added`
4. **Backend: connection events** — publish `connections:request` and `connections:accepted` to `user:{user_id}` + insert notification row
5. **Backend: chat_added notifications** — insert `chat_added` notification rows when users are added to group chats (both on group creation and adding participants), alongside existing `chats:added` publishes
6. **Backend: WS inbound handlers** — `notifications:read` and `notifications:cleared` message types, per-type rate limiters
7. **Frontend: notification centre UI** — bell icon, badge, panel, notification list, pagination, clear all
8. **Frontend: WS event handling** — handle new event types, cache invalidations, buffer expansion, optimistic badge updates
9. **Frontend: banner notifications** — dedicated Sonner toaster, banner components, suppression rules, message burst handling, reordering
10. **Frontend: banner preference toggle** — settings page toggle, localStorage persistence
11. **Frontend: chat page error handling** — 403/404 guard on chat queries
12. **Docs: update `pubsub_design.md`** — new events, updated payloads, inbound messages, rate limiting

---

## Post-implementation cleanup

After implementation is complete, this document should be revised to be a pure design document — remove the implementation order, prerequisite fixes, and docs-to-update sections. The goal is for this to serve as a reference for understanding how the notification system works, not as a task list.
