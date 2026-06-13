import React from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

interface ProtectedRouteProps {
  children: React.ReactNode;
  requiredRole?: 'user' | 'admin';
}

export function ProtectedRoute({ children, requiredRole }: ProtectedRouteProps) {
  const { user } = useAuth();

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  if (requiredRole && user.role !== requiredRole) {
    // Admin trying to access buyer pages goes to /admin; buyer trying /admin goes to /dashboard
    const redirect = user.role === 'admin' ? '/admin' : '/dashboard';
    return <Navigate to={redirect} replace />;
  }

  return <>{children}</>;
}
