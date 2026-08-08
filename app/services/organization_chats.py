

#async def create_or_get_organization_chat()
# Verify the organization exists.
# Verify the requester is allowed to access it.
# Find an existing chat by organization_id.
# Return it if found.
# Otherwise insert and return a new chat.

#async def create_organization_message()
# Verify the chat exists.
# Verify the current user can access that organization’s chat.
# Validate reply_to_id, if supplied, belongs to the same chat.
# Insert the message using the authenticated user as sender_id.
# Return the inserted row.

#async def verify_organization_chat_access()
# admin can access any chat
# rep can only access their own org's chat    

# TODO: Add reply-to support with validation.

# TODO: Add message editing support.
# Validate that the authenticated sender owns the message,
# update content, and set edited_at.

# TODO: Add soft-delete support for messages.
# Validate that the authenticated sender owns the message,
# mark is_deleted = true, and preserve the database record.

# TODO: add a fallback of deleted user for null sender_id after an auth.user.id account is deleted