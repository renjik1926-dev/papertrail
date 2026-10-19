export function formatCents(cents: number): string {
  return (cents / 100).toLocaleString("en-US", { style: "currency", currency: "USD" });
}

const ROLE_LABELS: Record<string, string> = {
  owed: "You owe",
  balance: "Balance — not a bill",
  charged: "Charged",
  paid_by_insurer: "Insurance paid",
  refund: "Refund to you",
  other: "Amount",
};

export function roleLabel(role: string | null): string {
  return ROLE_LABELS[role ?? "other"] ?? "Amount";
}
