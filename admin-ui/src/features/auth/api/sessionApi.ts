export async function loginByCredentials(adminId: string, password: string): Promise<void> {
  const body = new URLSearchParams({
    admin_id: adminId,
    password,
  });

  const response = await fetch("/admin/login", {
    method: "POST",
    credentials: "include",
    redirect: "follow",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: body.toString(),
  });

  if (response.status === 401 || response.url.includes("/admin/login")) {
    throw new Error("Invalid admin_id or password");
  }

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
}

export async function logoutSession(): Promise<void> {
  await fetch("/admin/logout", {
    method: "GET",
    credentials: "include",
  });
}
