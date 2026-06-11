import React from 'react';
import { AppNav } from './AppNav';

interface AppShellProps {
  children: React.ReactNode;
  balance?: number;
}

export function AppShell({ children, balance }: AppShellProps) {
  return (
    <div className="app-shell">
      <AppNav balance={balance} />
      <main className="main">
        {children}
      </main>
    </div>
  );
}
