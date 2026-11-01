// El identificador selecciona una cookie HttpOnly; nunca contiene el token de sesión.
const key = 'oliva.tab';
const valid = /^[a-f0-9]{32}$/;

export function createTabIdentity(storage: Pick<Storage, 'getItem' | 'setItem'>, locks: LockManager | undefined,
  onDispose: (release: () => void) => void, random: () => string): () => Promise<string> {
  let identity: Promise<string> | undefined;
  return () => {
    if (identity) return identity;
    identity = new Promise<string>((resolve, reject) => {
      const stored = storage.getItem(key);
      const candidate = stored && valid.test(stored) ? stored : random();
      function claim(id: string) {
        if (!locks) { storage.setItem(key, id); resolve(id); return; }
        // Duplicar una pestaña puede copiar sessionStorage: no compartir su sesión.
        void locks.request(`oliva.tab:${id}`, { ifAvailable: true }, (lock) => {
          if (!lock) { claim(random()); return; }
          storage.setItem(key, id); resolve(id);
          return new Promise<void>((release) => onDispose(() => { identity = undefined; release(); }));
        }).catch(reject);
      }
      claim(candidate);
    });
    return identity;
  };
}

let tabIdentity: (() => Promise<string>) | undefined;
export async function sessionHeaders(mutation = false): Promise<Record<string, string>> {
  tabIdentity ??= createTabIdentity(window.sessionStorage, navigator.locks,
    (release) => window.addEventListener('pagehide', release, { once: true }),
    () => crypto.randomUUID().replaceAll('-', ''));
  return { 'X-Oliva-Tab': await tabIdentity(), ...(mutation ? { 'Content-Type': 'application/json', 'X-CSRF-Protection': '1' } : {}) };
}
