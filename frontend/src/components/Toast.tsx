"use client";

import { createContext, useCallback, useContext, useRef, useState } from "react";

export type ToastKind = "info" | "success" | "error";

export interface ToastMessage {
  id: number;
  kind: ToastKind;
  text: string;
  actionLabel?: string;
  onAction?: () => void;
}

interface ToastContextValue {
  push: (text: string, kind?: ToastKind, action?: { label: string; onClick: () => void }) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside ToastProvider");
  return ctx;
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const counter = useRef(0);

  const push = useCallback(
    (text: string, kind: ToastKind = "info", action?: { label: string; onClick: () => void }) => {
      const id = ++counter.current;
      setToasts((prev) => [
        ...prev,
        { id, kind, text, actionLabel: action?.label, onAction: action?.onClick },
      ]);
      const timeout = kind === "error" ? 8000 : 4500;
      setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
      }, timeout);
    },
    [],
  );

  return (
    <ToastContext.Provider value={{ push }}>
      {children}
      <div
        className="fixed bottom-24 right-6 z-50 flex flex-col gap-2"
        role="status"
        aria-live="polite"
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            className={
              "flex items-center gap-3 rounded border px-4 py-2.5 text-[13px] shadow-sm " +
              (t.kind === "error"
                ? "border-danger bg-danger-soft text-danger"
                : t.kind === "success"
                  ? "border-success bg-success-soft text-success"
                  : "border-hairline bg-paper-soft text-ink")
            }
          >
            <span>{t.text}</span>
            {t.actionLabel && (
              <button
                type="button"
                onClick={t.onAction}
                className="font-medium underline underline-offset-2 hover:opacity-70"
              >
                {t.actionLabel}
              </button>
            )}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
