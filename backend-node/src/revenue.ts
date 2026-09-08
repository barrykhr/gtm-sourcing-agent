// Port of revenue.py, verbatim — one constant, one formula. Expected
// revenue is role_value * margin; realized revenue is never computed
// here, it's the recruiter-entered placement_fee (see storage.ts's
// analyticsOverview / recruiterRevenue).
export const REVENUE_MARGIN_PERCENTAGE = 8.33;

export function expectedRevenue(roleValue: number | null | undefined): number | null {
  if (roleValue === null || roleValue === undefined) return null;
  return Math.round(roleValue * (REVENUE_MARGIN_PERCENTAGE / 100) * 100) / 100;
}
