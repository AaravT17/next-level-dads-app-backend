from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel
from typing import Optional
from uuid import UUID
import asyncpg

from app.dependencies.auth import get_admin_user, get_current_user
from app.dependencies.db import get_db
from app.services.organizations_events import (
    build_get_organization_event_by_id_query,
    build_list_organization_events_query,
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

# Partner-Facing 

@router.get("/me")
async def get_my_organization_events(
    conn: asyncpg.Connection = Depends(get_db),
    user_id = Depends(get_current_user),
    ):
    """
    Get all event submissions belonging to the logged-in user's organization,
    across all statuses (pending, approved, rejected).
    Partner-facing — not admin only.
    """
    try:
        org_query = """
            SELECT o.id
            FROM organizations o
            JOIN organization_representatives r ON r.organization_id = o.id
            WHERE r.user_id = $1
            LIMIT 1
        """
        org_row = await conn.fetchrow(org_query, UUID(user_id))
        if not org_row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No organization found for this user."
            )
        org_id = org_row["id"]

        events_query = """
            SELECT id, name, description, type, app_status, created_at, location
            FROM events
            WHERE hosted_by_org_id = $1
            ORDER BY created_at DESC
        """
        rows = await conn.fetch(events_query, org_id)
        return [dict(row) for row in rows]

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
            detail="Failed to fetch your organization's events. Please try again later.",
        )

# Admin Review

@router.get("/")
async def list_organization_events(
    search: str | None = Query(default=None),
    region: str | None = Query(default=None),
    organization: str | None = Query(default=None),
    format: str | None = Query(default=None),
    category: str | None = Query(default=None),
    status: str | None = Query(default=None),
    conn: asyncpg.Connection = Depends(get_db),
    admin_user=Depends(get_admin_user),
):
    """
    Admin Events page list + metrics.
    """
    try:
        query, params = build_list_organization_events_query(
            search=search,
            region=region,
            organization=organization,
            format=format,
            category=category,
            status=status,
        )
        rows = await conn.fetch(query, *params)

        events = []
        organizations: set[str] = set()
        total_rsvps = 0
        total_attended = 0

        for r in rows:
            item = {
                "id": str(r["id"]),
                "name": r["name"],
                "organization_name": r["organization_name"],
                "event_date": r["event_date"].isoformat() if r["event_date"] else None,
                "rsvps": int(r["rsvps"] or 0),
                "attended": int(r["attended"] or 0),
                "attendance_rate": float(r["attendance_rate"] or 0),
                "status": r["status"],
                "region": r["region"],
                "format": r["format"],
                "category": r["category"],
            }
            events.append(item)
            if item["organization_name"]:
                organizations.add(item["organization_name"])
            total_rsvps += item["rsvps"]
            total_attended += item["attended"]

        metrics = {
            "total_rsvps_active": total_rsvps,
            "dads_attended_completed": total_attended,
            "event_attendance_rate": (
                (total_attended / total_rsvps) if total_rsvps > 0 else 0
            ),
            "repeat_attendee_rate": 0,  # needs richer attendance history later
        }

        return {
            "metrics": metrics,
            "events": events,
            "organizations": sorted(organizations),
        }

    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list organization events. Please try again later.",
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
        allowed_statuses = {"pending", "approved", "rejected"}
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


