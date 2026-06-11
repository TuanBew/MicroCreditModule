import React, { createContext, useContext, useState, useCallback } from 'react';

interface ToastMessage {
  id: string;
  message: string;
  type: 'default' | 'success' | 'error';
}

interface ToastContextValue {
  showToast: (message: string, type?: 'default' | 'success' | 'error') => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  const showToast = useCallback((message: string, type: 'default' | 'success' | 'error' = 'default') => {
    const id = crypto.randomUUID();
    setToasts((prev) => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 3500);
  }, []);

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      <div className="toast-region">
        {toasts.map((t) => (
          <div key={t.id} className={`toast${t.type !== 'default' ? ` ${t.type}` : ''}`}>
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within ToastProvider');
  return ctx;
}
