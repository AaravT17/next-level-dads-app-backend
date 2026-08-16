from fastapi import APIRouter, Depends, HTTPException, status, Query
from app.dependencies.auth import get_consented_user, get_current_user
from app.models.events import EventResponse, EventCreate, EventCreateResponse, EventUpdate, EventUpdateResponse, PartnerEventResponse
from app.dependencies.db import get_db
from typing import Literal
import asyncpg
from uuid import UUID
from datetime import datetime
from app.services.events import build_discover_events_query, build_get_event_by_id_query
from app.config.rate_limits import CreateEventLimiter




router = APIRouter(
    prefix='/api/events',
    tags=['events'],
)


@router.get('/', response_model=list[EventResponse])
async def get_events(
    name: str | None = None,
    event_type: Literal['local', 'virtual'] | None = Query(default=None, alias='type'),
    is_free: bool | None = None,
    cursor_id: str | None = None,
    cursor_starts_at: datetime | None = None,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    try:
        query, params = build_discover_events_query(
            user_id=UUID(user_id),
            name=name,
            event_type=event_type,
            is_free=is_free,
            cursor_id=UUID(cursor_id) if cursor_id else None,
            cursor_starts_at=cursor_starts_at,
        )
        res = await conn.fetch(query, *params)
        return [EventResponse(**dict(r)) for r in res]
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch events. Please try again later.',
        )


@router.get('/{id}', response_model=EventResponse)
async def get_event_by_id(
    id: str,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    try:
        query, params = build_get_event_by_id_query(id=UUID(id), user_id=UUID(user_id))
        res = await conn.fetchrow(query, *params)
        if not res:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Event not found')
        return EventResponse(**dict(res))
    except HTTPException as _:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch event details. Please try again later.',
        )


@router.post('/{id}/attendees', status_code=status.HTTP_204_NO_CONTENT)
async def register_for_event(
    id: str,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    # TODO: For paid events, integrate with payment gateway and only register user after successful payment
    try:
        id, user_id = UUID(id), UUID(user_id)
        # check if the event is free or paid
        query = """
            SELECT price_cad from events WHERE id = $1
        """
        res = await conn.fetchval(query, *[id], column=0)
        if res is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Event not found')
        price = float(res)
        # for now, if the event is paid, do not allow registration through this endpoint
        if price > 0:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail='Cannot register for paid events through this endpoint.',
            )
        query = """
            INSERT INTO event_attendees (event_id, user_id, joined_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT DO NOTHING
        """
        await conn.execute(query, *[id, user_id])
        return
    except HTTPException as _:
        raise
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to register for event. Please try again later.',
        )


@router.delete('/{id}/attendees', status_code=status.HTTP_204_NO_CONTENT)
async def unregister_from_event(
    id: str,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    try:
        id, user_id = UUID(id), UUID(user_id)
        query = """
            DELETE FROM event_attendees 
            WHERE event_id = $1 AND user_id = $2
        """
        await conn.execute(query, *[id, user_id])
        return
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to unregister from event. Please try again later.',
        )

@router.post(
    '/event-application',
    response_model=EventCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an event",
    description="""
        Creates a new event application

        Required fields include name, type, starts_at, location, and price_cad
        The authenticated user must administer an organization
    """,
    responses={
        201: {"description": "Event created successfully"},
        404: {"description": "User does not administer an organization"},
        500: {"description": "Internal server error: failed to create event."}
    }
)
async def create_event(
    event: EventCreate,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        async with conn.transaction():
            user_id = UUID(user_id)
            # print("user id: ", user_id)
            # Fetch Organization Id using the current users ID
            query = """
                SELECT organization_id 
                FROM organization_representatives
                WHERE user_id = $1
            """
            organization_id = await conn.fetchval(query, *[user_id])
            # print("Organization id: ", organization_id)

            if not organization_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='User does not administer an organization')

            query = """
                INSERT INTO events (name, description, type, starts_at, ends_at, location, latitude, longitude, hosted_by_org_id, contact_email, contact_phone, price_cad, created_by, created_at, app_status)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, NOW(), 'pending')
                RETURNING id
            """

            # print("inserting into event table")
            # Retrieve the ID of the new event row after insertion
            res = await conn.fetchval(
                query,
                event.name, 
                event.description, 
                event.type, 
                event.starts_at, 
                event.ends_at, 
                event.location, 
                event.latitude, 
                event.longitude, 
                organization_id, 
                event.contact_email, 
                event.contact_phone, 
                event.price_cad, 
                user_id
            )

            # print ("insertion complete, id: ", res)

            if not res:
                raise Exception('Failed to create event')

            # Return event id to user
            event_id = res
            return {'id': event_id}
        
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to create event. Please try again later.',
        )

@router.patch(
        '/{id}', 
        response_model=EventUpdateResponse,
        summary="Update an event",
        description="""
        Updates one or more fields of an event.

        Only the fields present within the response body will be modified.
        The user must administer the organization that owns the event
        """
        )
async def update_event(
    id: UUID,
    event: EventUpdate,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        user_id = UUID(user_id)
        # Fetch Organization Id using the current users ID
        query = """
            SELECT organization_id 
            FROM organization_representatives
            WHERE user_id = $1
        """
        organization_id = await conn.fetchval(query, *[user_id])

        if not organization_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='User does not administer an organization')

        # Verify the event exist and belongs to the user's organization
        query = """
            SELECT *
            FROM events
            WHERE id = $1 AND hosted_by_org_id = $2
        """
        existing_event = await conn.fetchval(query, id, organization_id)
        if not existing_event:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Event not found"
            )

        # Create new update model
        update_data = event.model_dump(exclude_unset=True)

        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields provided for update"
            )

        set_clauses = []
        values = []

        for index, (field, value) in enumerate(update_data.items(), start=1):
            set_clauses.append(f"{field} = ${index}")
            values.append(value)

        event_id_param = len(values) + 1

        query = f"""
            UPDATE events
            SET {", ".join(set_clauses)}
            WHERE id = ${event_id_param} AND hosted_by_org_id = ${event_id_param + 1}
            RETURNING id, name, description, type, starts_at, ends_at, location, latitude, longitude, contact_email, contact_phone, price_cad, created_at, app_status
        """

        values.append(id)
        values.append(organization_id)

        updated_event = await conn.fetchrow(query, *values)

        # Return new event data to user
        return EventUpdateResponse(**dict(updated_event))

    except Exception as _:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail='Failed to update event. Please try again later.',
            )

# TODO: For partners to view their event listings
# -- FIX: Getting unknown error message 
# @router.get(
#     '/my-partner-events',
#     response_model=list[PartnerEventResponse],
# )
# async def get_partner_events(
#     conn: asyncpg.Connection = Depends(get_db),
#     user_id = Depends(get_current_user)
# ):
#     try:
#         print(user_id)
#         # Get user's organization id
#         query = """
#             SELECT organization_id 
#             FROM organization_representatives
#             WHERE user_id = $1
#         """
#         organization_id = await conn.fetchval(query, user_id)
#         print("Organization id: ", organization_id)

#         if not organization_id:
#             raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='User does not administer an organization')

#         # Get event data
#         query = """
#             SELECT e.id, e.name, e.description, e.type, e.starts_at, e.ends_at, e.location, e.latitude, e.longitude, e.contact_email, e.contact_phone, e.price_cad, e.created_at, e.app_status, count(ea.user_id) AS attendee_count
#             FROM events AS e
#             LEFT JOIN event_attendees AS ea
#             ON ea.event_id = e.id
#             WHERE e.hosted_by_org_id = $1
#             GROUP BY e.id
#         """

#         res = await conn.fetch(query, organization_id)

#         return [PartnerEventResponse(**dict(r)) for r in res]
    
#     except ValueError as e:
#             raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
#     except Exception as _:
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail='Failed to fetch events. Please try again later.',
#         )
