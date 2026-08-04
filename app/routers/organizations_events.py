from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Optional
from uuid import UUID
import asyncpg

from app.dependencies.auth import get_admin_user
from app.dependencies.db import get_db
from app.services.organizations_events import (
    build_get_organization_event_by_id_query,
    build_update_organization_event_decision_query,
)


class DecisionRequest(BaseModel):
    status: str
    admin_notes: Optional[str] = None
    decision_message: Optional[str] = None


router = APIRouter(
    prefix="/api/organizations-events",
    tags=["organizations-events"]
)


@router.get("/{event_id}")
async def get_organization_event(
    event_id: str,
    conn: asyncpg.Connection = Depends(get_db),
    admin_user = Depends(get_admin_user)
):
    """
    Get the full details of one organization event application.
    Admin only
    """
    try:
        query, params = build_get_organization_event_by_id_query(
            event_id=UUID(event_id)
        )
        res = await conn.fetchrow(query, *params)

        if not res:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization event not found",
            )
        
        return dict(res)

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch organization event. Please try again later.",
        )


@router.patch("/{event_id}/decision")
async def decide_organization_event(
    event_id: str,
    decision: DecisionRequest,
    conn: asyncpg.Connection = Depends(get_db),
    admin_user = Depends(get_admin_user)
):
    """
    Allow admin to approve, deny, keep pending an organizations event application
    """
    try:
        allowed_statuses = {"pending", "approved", "denied"}
        if decision.status not in allowed_statuses:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Status must be one of: {', '.join(allowed_statuses)}",
            )

        query, params = build_update_organization_event_decision_query(
            event_id=UUID(event_id),
            status=decision.status,
            admin_notes=decision.admin_notes,
            admin_user_id=admin_user,
        )
        res = await conn.fetchrow(query, *params)

        if not res:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization event not found"
            )

        return {
            "id": str(res["id"]),
            "app_status": res["app_status"],
            "admin_notes": res['admin_notes'],
            "decision_message": decision.decision_message
    }

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update organization event decision. Please try again later.",
        )


