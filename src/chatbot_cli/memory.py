import uuid


async def seed_username(store, user_id: str):
    namespace = ("user", user_id, "details")
    existing = await store.asearch(namespace, query=None, limit=500)
    already = any(user_id.lower() in it.value.get("data", "").lower() for it in existing)
    if not already:
        await store.aput(namespace, str(uuid.uuid4()), {"data": f"User's username is {user_id}"})
