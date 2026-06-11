import React, { createContext, useContext, useState, useCallback } from 'react';
import type { AuthUser } from '../api/auth';

interface AuthContextValue {
  user: AuthUser | null;
  token: string | null;
  login: (token: string, user: AuthUser) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function loadFromStorage(): { user: AuthUser | null; token: string | null } {
  try {
    const token = localStorage.getItem('creditos:token');
    const userRaw = localStorage.getItem('creditos:user');
    const user = userRaw ? (JSON.parse(userRaw) as AuthUser) : null;
    return { token, user };
  } catch {
    return { token: null, user: null };
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const stored = loadFromStorage();
  const [token, setToken] = useState<string | null>(stored.token);
  const [user, setUser] = useState<AuthUser | null>(stored.user);

  const login = useCallback((newToken: string, newUser: AuthUser) => {
    localStorage.setItem('creditos:token', newToken);
    localStorage.setItem('creditos:user', JSON.stringify(newUser));
    setToken(newToken);
    setUser(newUser);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem('creditos:token');
    localStorage.removeItem('creditos:user');
    setToken(null);
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, token, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
