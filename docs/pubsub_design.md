# Real-Time Messaging: Per-Chat Pub/Sub Design

Design document for the migration from per-user to per-chat Redis Pub/Sub channels.

---

## Overview

Messages are delivered in real-time via Redis Pub/Sub and WebSocket connections. Redis Pub/Sub acts as the broadcast layer between server instances — when a message is published on one server, all servers subscribed to that channel receive it and fan out to their local WebSocket connections.

Each message publishes once to a `chat:{chat_id}` channel, and each server instance fans out to its connected subscribers via `asyncio.gather`. User-level events (chat added/removed, read receipts) are delivered via `user:{user_id}` channels.

This replaces the previous per-user architecture where sending a message to a chat with N participants required N separate `redis.publish()` calls to individual `messages:{user_id}` channels.

---

## Channels

Two channel types:

| Channel          | Purpose                                     |
| ---------------- | ------------------------------------------- |
| `chat:{chat_id}` | Chat-scoped events (messages)               |
| `user:{user_id}` | User-scoped events (chat membership, reads) |

### Events

| Channel          | Event             | Payload                                                         | Backend Action                    | Frontend Action                 |
| ---------------- | ----------------- | --------------------------------------------------------------- | --------------------------------- | ------------------------------- |
| `chat:{chat_id}` | `messages:new`    | Full `MessageResponse`                                          | Fan out to subscribed connections | Append message (dedup by id)    |
| `chat:{chat_id}` | `messages:edit`   | `{id, chat_id, content, edited_at, is_deleted}`                 | Fan out to subscribed connections | Update message in place         |
| `chat:{chat_id}` | `messages:delete` | `{id, chat_id, content: '', is_deleted: true, edited_at: null}` | Fan out to subscribed connections | Mark message deleted            |
| `user:{user_id}` | `chats:added`     | `{chat_id}`                                                     | Subscribe to chat channel         | Fetch chat preview, add to list |
| `user:{user_id}` | `chats:removed`   | `{chat_id}`                                                     | Unsubscribe from chat channel     | Remove chat from list           |
| `user:{user_id}` | `chats:read`      | `{chat_id, last_read_at}`                                       | Forward to user's connections     | Update read state               |

---

## Data Structures (`connection_manager.py`)

```python
_user_connections: dict[str, dict[str, WebSocket]] = {}
# {user_id: {connection_id: WebSocket}}
# All active WebSocket connections for each user on this server.

_chat_subscribers: dict[str, set[str]] = {}
# {chat_id: set of user_ids}
# Which users on this server are subscribed to a given chat's channel.

_user_chats: dict[str, set[str]] = {}
# {user_id: set of chat_ids}
# Reverse index of _chat_subscribers. Used for efficient cleanup on disconnect.

_users_initialized: set[str] = set()
# Users whose initial chat subscription setup is complete.
# Prevents redundant DB queries on subsequent connections for the same user.
# Cleared when the user's last connection disconnects.
```

All mutations to these structures and all Redis subscribe/unsubscribe calls are protected by a single `asyncio.Lock()`.

---

## Connection Lifecycle

### Connect (`ws/router.py` + `connection_manager.py`)

1. Verify token and consent
2. `ws.accept()`
3. **Lock 1**: Add WebSocket to `_user_connections`. If first connection for user, subscribe to `user:{user_id}`.
4. If user not in `_users_initialized`:
   - Query DB for all chat IDs (outside lock)
   - **Lock 2**: Add chat IDs to `_user_chats[user_id]`. Add user to `_chat_subscribers[chat_id]` for each chat. Subscribe to all `chat:{chat_id}` channels. Mark user as initialized.
5. Send `{"type": "ws:ready"}` to client
6. Enter message receive loop
7. `finally`: Unregister connection

`ws:ready` is the synchronization point — the frontend ignores all events until it's received, then does initial fetches. This decouples "transport is open" from "backend is ready to deliver events".

### Disconnect (`connection_manager.py`)

Single lock acquisition:

1. Remove WebSocket from `_user_connections[user_id]`
2. If user has other connections: done
3. If last connection for user:
   - Remove user from `_users_initialized`
   - For each chat in `_user_chats[user_id]`: remove user from `_chat_subscribers[chat_id]`. If the chat has no remaining subscribers on this server instance, add `chat:{chat_id}` to the unsubscribe list and remove the entry from `_chat_subscribers`.
   - Remove `_user_chats[user_id]`
   - Single batched `unsubscribe(user:{user_id}, ...chat channels)` call

---

## Event Handlers (`connection_manager.py`)

### `_process_chat_event(msg)`

No lock needed — read-only on data structures.

1. Parse event from `msg['data']`
2. Extract `chat_id` from channel name
3. Look up `_chat_subscribers[chat_id]` → set of user IDs
4. Collect all WebSockets for those users
5. Send to all WebSockets concurrently via `asyncio.gather`

### `_process_user_event(msg)`

Lock needed for `chats:added` / `chats:removed` (mutate data structures + call sub/unsub). No lock for `chats:read` (forward only).

- **`chats:added`**: Subscribe to `chat:{chat_id}`, update `_user_chats` and `_chat_subscribers`, then forward event to user's WebSockets.
- **`chats:removed`**: Remove from `_user_chats` and `_chat_subscribers`. If no subscribers remain for the chat on this server instance, unsubscribe from the channel. Forward event.
- **`chats:read`**: Forward event to user's WebSockets.

---

## Publish Side (`chats/service.py`)

Single `publish(f'chat:{chat_id}', event)` instead of N publishes to individual user channels. No need to query participant IDs for publishing.

```python
# send_message
asyncio.create_task(
    _safe_publish(f'chat:{chat_id}', {'type': 'messages:new', 'payload': msg.model_dump(mode='json')})
)

# edit_message / delete_message — same pattern
asyncio.create_task(
    _safe_publish(f'chat:{chat_id}', {'type': 'messages:edit', 'payload': {...}})
)
```

User-level events (`chats:added`, `chats:removed`) still publish to individual `user:{user_id}` channels since they target specific users.

---

## Redis Configuration (`redis.py`)

`publish()` takes a channel string directly:

```python
async def publish(channel: str, msg: dict):
    await redis_client.publish(channel=channel, message=json.dumps(msg))
```

Callers pass `f'chat:{chat_id}'` or `f'user:{user_id}'`.

---

## Locking Strategy

Single global `asyncio.Lock()`. All dict mutations and Redis sub/unsub calls happen inside the lock. DB queries happen outside.

**Why a single lock**: The data structures are interconnected (`_chat_subscribers` and `_user_chats` are two sides of the same relationship). Per-user/per-chat locks would increase concurrency but add complexity (multiple lock acquisitions per operation, lock ordering). At current scale, the single lock is not a bottleneck.

Redis sub/unsub calls are batched into single `subscribe(ch1, ch2, ...)` / `unsubscribe(ch1, ch2, ...)` calls regardless of channel count.

---

## Frontend Contract

1. **`ws:ready`**: Wait for this event before doing initial fetches for real-time-dependent features
2. **Dedup**: Ignore incoming `messages:new` if message ID already in state
3. **Rotate `connection_id`**: Generate new UUID on each reconnect. If both use the same ID, there is a race between the old connection's disconnect and the new connection's connect — the old connection's `unregister_connection` could pop the new connection's WebSocket from the dict.
4. **Event buffer during fetch**: Queue incoming WS events while initial fetches are in flight, drain in order once fetches resolve
5. **Reconnect = invalidate + re-fetch**: On WS drop, invalidate all chat state and re-fetch on reconnect

---

## Known Race Conditions

### Stale DB snapshot during connect

Between the DB query (step 4) and Lock 2, a `chats:removed` event could arrive for a chat returned by the query. The event handler tries to remove the chat from `_user_chats`, but Lock 2 hasn't populated it yet — so it's a no-op. Lock 2 then subscribes to the now-stale chat.

- **Likelihood**: Near zero — requires removal in the milliseconds between DB query and Lock 2
- **Impact**: Backend subscribes to the stale chat channel, but the frontend is unaffected. The frontend maintains its own set of chats the user is a member of and filters out events for chats not in that set.
- **Self-healing**: Backend cleans up when the user's last connection closes (full cleanup runs, next connect gets fresh state); frontend is already correct
- **Fundamental cause**: Any system that snapshots state and then acts on it has this window

### Concurrent connects for same user

Two connections arriving simultaneously could both run the DB query + Lock 2. This is safe: Lock 2 only adds to sets (never clears/replaces), re-subscribing is idempotent, and `_users_initialized` ensures subsequent connections skip the setup entirely.

---

## Benchmark Results

Test setup: 1 sender, 3 uvicorn workers, local Redis, remote Supabase DB. 100 measured rounds per test, 5 warmup rounds discarded.

### Server-Side Fan-Out Latency (publish → last ws.send_json completes)

**500 connections:**

| Metric | Per-User | Per-Chat | Speedup |
| ------ | -------- | -------- | ------- |
| p50    | 222.4ms  | 19.3ms   | 11.5×   |
| p95    | 309.8ms  | 24.3ms   | 12.7×   |
| p99    | 318.6ms  | 28.9ms   | 11.0×   |

**1000 connections:**

| Metric | Per-User | Per-Chat | Speedup |
| ------ | -------- | -------- | ------- |
| p50    | 368.3ms  | 35.4ms   | 10.4×   |
| p95    | 458.4ms  | 56.9ms   | 8.1×    |
| p99    | 466.1ms  | 137.2ms  | 3.4×    |

### End-to-End Delivery Latency (POST send → last WS receive)

**500 connections:**

| Metric | Per-User | Per-Chat | Speedup |
| ------ | -------- | -------- | ------- |
| p50    | 350.0ms  | 138.8ms  | 2.5×    |
| p95    | 440.7ms  | 196.1ms  | 2.2×    |
| p99    | 530.5ms  | 252.1ms  | 2.1×    |

**1000 connections:**

| Metric | Per-User | Per-Chat | Speedup |
| ------ | -------- | -------- | ------- |
| p50    | 518.5ms  | 184.4ms  | 2.8×    |
| p95    | 627.9ms  | 243.2ms  | 2.6×    |
| p99    | 660.2ms  | 325.3ms  | 2.0×    |

### Summary

| Metric                     | Improvement      |
| -------------------------- | ---------------- |
| Server fan-out latency p50 | 10–12× faster    |
| Server fan-out latency p95 | 8–13× faster     |
| Server fan-out latency p99 | 3–11× faster     |
| E2E delivery latency p50   | 2.5–2.8× faster  |
| E2E delivery latency p95   | 2.2–2.6× faster  |
| E2E delivery latency p99   | 2.0–2.1× faster  |
| Redis publishes/msg        | O(n) → O(1)      |
