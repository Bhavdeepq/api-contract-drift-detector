USERS_ENDPOINT = "/users/{userId}"


def display_user(user: dict[str, object]) -> str:
    return str(user.get("id", ""))


def fetch_options() -> dict[str, bool]:
    return {"includeDetails": True}
