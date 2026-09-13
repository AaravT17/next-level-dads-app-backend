from typing import Literal

ConnectionStatus = Literal['pending_incoming', 'pending_outgoing', 'connected', 'blocked'] | None
