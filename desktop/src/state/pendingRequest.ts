import {request} from '../bridge';

// The native journal is authoritative: a rejected replay may have cleared it.
// If IPC itself fails, retain the existing lock until the outcome is known.
export async function pendingRequestState():Promise<boolean|null> {
  try { return (await request<{pending:boolean}>('connection')).pending; }
  catch { return null; }
}
