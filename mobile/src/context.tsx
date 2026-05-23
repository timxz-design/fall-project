/**
 * Auth context — holds the current home's identity. Read by every screen.
 */
import React, {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { clearAuth, loadAuth, saveAuth, StoredAuth } from "./storage";

interface AuthContextValue {
  auth: StoredAuth | null;
  loading: boolean;
  setAuth: (a: StoredAuth) => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [auth, setAuthState] = useState<StoredAuth | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      const stored = await loadAuth();
      setAuthState(stored);
      setLoading(false);
    })();
  }, []);

  const setAuth = useCallback(async (a: StoredAuth) => {
    await saveAuth(a);
    setAuthState(a);
  }, []);

  const signOut = useCallback(async () => {
    await clearAuth();
    setAuthState(null);
  }, []);

  return (
    <AuthContext.Provider value={{ auth, loading, setAuth, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
