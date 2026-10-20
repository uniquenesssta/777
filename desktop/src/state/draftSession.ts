const runtimeKey = '777-draft-runtime';
export const draftKey = '777-desktop-draft-v1';
export function clearDraftStorage(storage: Storage) {
  for (let i = storage.length - 1; i >= 0; i--) {
    const key = storage.key(i);
    if (key && (key === draftKey || key.startsWith('777-desktop-draft-source-') || key.startsWith('777-desktop-restricted-draft-'))) storage.removeItem(key);
  }
}
// The native process ID changes even if WebView restores session storage after a restart.
export function startDraftSession(storage: Storage, legacy: Storage, runtime: string) {
  clearDraftStorage(legacy);
  if (storage.getItem(runtimeKey) !== runtime) clearDraftStorage(storage);
  storage.setItem(runtimeKey, runtime);
  return storage.getItem(draftKey);
}
