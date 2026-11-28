// The public demo logins (see backend/app/seed.py ensure_demo_accounts). They are open to everyone on purpose:
// the household is a normal account, and the two staff accounts are read-only roles that can change nothing.
export const DEMO = {
  password: "NidhiDemo2036",
  household: "demo-household@example.com",
  discom: "demo-discom@example.com",
  geda: "demo-geda@example.com",
} as const;
