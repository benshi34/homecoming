/** Whether the ten-minute Notification Center poll has new work. */
export function notificationReadDue(enabled: boolean, dbMtime: number | null, seenMtime: number | null): boolean {
  return enabled && dbMtime !== null && dbMtime !== seenMtime;
}
