import { t } from "./i18n";import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Info, X } from "lucide-react";
import { cn } from "./format";

type ToastKind = "success" | "error" | "info";
interface ToastItem {
  id: number;
  kind: ToastKind;
  message: string;
}

interface ToastContextValue {
  success: (message: string) => void;
  error: (message: string) => void;
  info: (message: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function ToastProvider({ children }: {children: ReactNode;}) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const counter = useRef(0);

  const remove = useCallback((id: number) => {
    setItems((current) => current.filter((item) => item.id !== id));
  }, []);

  const push = useCallback(
    (kind: ToastKind, message: string) => {
      const id = ++counter.current;
      setItems((current) => [...current.slice(-3), { id, kind, message }]);
      window.setTimeout(() => remove(id), kind === "error" ? 6500 : 4500);
    },
    [remove]
  );

  const value = useMemo(
    () => ({
      success: (message: string) => push("success", message),
      error: (message: string) => push("error", message),
      info: (message: string) => push("info", message)
    }),
    [push]
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toast-viewport" aria-live="polite">
        {items.map((item) => {
          const Icon = item.kind === "success" ? CheckCircle2 : item.kind === "error" ? AlertTriangle : Info;
          return (
            <div key={item.id} className={cn("toast", `toast-${item.kind}`)}>
              <Icon size={18} />
              <span>{item.message}</span>
              <button type="button" onClick={() => remove(item.id)} aria-label={t("بستن")}>
                <X size={15} />
              </button>
            </div>);

        })}
      </div>
    </ToastContext.Provider>);

}

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside ToastProvider");
  return context;
}
