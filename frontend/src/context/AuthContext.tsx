import React, { createContext, useContext, useState, useCallback, useEffect } from 'react';
import type { AuthUser } from '../api/auth';
import { getMe } from '../api/auth';

interface AuthContextValue {
  user: AuthUser | null;
  login: (user: AuthUser) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function loadUserFromStorage(): AuthUser | null {
  try {
    const userRaw = localStorage.getItem('creditos:user');
    return userRaw ? (JSON.parse(userRaw) as AuthUser) : null;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(loadUserFromStorage);

  // On mount, validate session by calling /auth/me.
  // 401 = cookie definitively expired/invalid → clear stale local state so
  // ProtectedRoute redirects to /login instead of rendering protected pages
  // with a user that the server won't accept.
  // Network errors leave state intact (graceful degradation for offline/tests).
  useEffect(() => {
    getMe()
      .then((serverUser) => {
        setUser(serverUser);
        localStorage.setItem('creditos:user', JSON.stringify(serverUser));
      })
      .catch((err: unknown) => {
        const status = (err as { response?: { status?: number } })?.response?.status;
        if (status === 401) {
          localStorage.removeItem('creditos:user');
          setUser(null);
        }
      });
  }, []);

  const login = useCallback((newUser: AuthUser) => {
    localStorage.setItem('creditos:user', JSON.stringify(newUser));
    setUser(newUser);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem('creditos:user');
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
