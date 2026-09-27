const userPath = "/users/{userId}";

export const getUserId = (user: { id?: string }) => user.id ?? "";
