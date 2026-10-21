import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "./api";
import type { Admin } from "./types";
import { useQueryClient } from "@tanstack/react-query";

interface AuthContextValue {
  admin: Admin | null;
  loading: boolean;
  login: (username: string, password: string, otpCode?: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [admin, setAdmin] = useState<Admin | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    localStorage.removeItem("hamgara_token");
    localStorage.removeItem("spectergate_token");
    api
      .get<Admin>("/api/auth/me")
      .then(setAdmin)
      .catch(() => {
        setAdmin(null);
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const onUnauthorized = () => { setAdmin(null); queryClient.clear(); };
    window.addEventListener("spectergate:unauthorized", onUnauthorized);
    return () => window.removeEventListener("spectergate:unauthorized", onUnauthorized);
  }, [queryClient]);

  const login = useCallback(async (username: string, password: string, otpCode?: string) => {
    const response = await api.post<Admin>("/api/auth/session", { username, password, otp_code: otpCode || null });
    queryClient.clear();
    setAdmin(response);
  }, [queryClient]);

  const logout = useCallback(async () => {
    await api.post("/api/auth/logout");
    setAdmin(null);
    queryClient.clear();
  }, [queryClient]);

  const value = useMemo(() => ({ admin, loading, login, logout }), [admin, loading, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
