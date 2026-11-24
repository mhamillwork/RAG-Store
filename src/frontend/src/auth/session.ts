export interface Account {
  id: string;
  username: string;
  role: string;
  quota: Record<string, number>;
}

export function isAdmin(account: Account | null): boolean {
  return account?.role === "admin";
}
