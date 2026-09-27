USERS_ENDPOINT = "/users/{userId}"


def display_user(user: dict[str, object]) -> str:
    return str(user["email"])


def fetch_options() -> dict[str, bool]:
    return {"includeDetails": True}
