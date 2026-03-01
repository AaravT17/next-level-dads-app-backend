from app.config.supabase import get_supabase


async def get_user_by_id(user_id: str) -> dict | None:
    supabase = get_supabase()
    res = (
        await supabase.table("users")
        .select("*, user_interests(interests(name)), user_children(age_range)")
        .eq("id", user_id)
        .execute()
    )

    if not res.data:
        return None

    # flatten interests, children age ranges
    user = {
        **res.data[0],
        "interests": [
            i["interests"]["name"] for i in res.data[0].get("user_interests", [])
        ],
        "children": [c["age_range"] for c in res.data[0].get("user_children", [])],
    }
    return user


async def delete_avatar(user_id: str):
    supabase = get_supabase()
    try:
        await supabase.storage.from_("avatars").remove([user_id])
    except Exception as _:
        pass
