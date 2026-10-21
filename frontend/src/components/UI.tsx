import { t } from "../lib/i18n";import {
  useEffect,
  useId,
  cloneElement,
  isValidElement,
  type ReactElement,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes } from
"react";
import { createPortal } from "react-dom";
import { AlertTriangle, Loader2, X } from "lucide-react";
import { cn } from "../lib/format";

/* ---------------- Button ---------------- */
type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "outline";
type ButtonSize = "sm" | "md" | "lg";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  icon?: ReactNode;
}

export function Button({
  children,
  className,
  variant = "primary",
  size = "md",
  loading = false,
  icon,
  disabled,
  ...props
}: ButtonProps) {
  return (
    <button
      className={cn("btn", `btn-${variant}`, `btn-${size}`, className)}
      disabled={disabled || loading}
      {...props}>

      {loading ? <Loader2 className="spin" size={17} /> : icon}
      {children && <span>{children}</span>}
    </button>);

}

/* ---------------- Card / section ---------------- */
export function Card({ children, className }: {children: ReactNode;className?: string;}) {
  return <div className={cn("card", className)}>{children}</div>;
}

export function SectionHeader({
  title,
  subtitle,
  action




}: {title: string;subtitle?: string;action?: ReactNode;}) {
  return (
    <div className="section-header">
      <div>
        <h2>{title}</h2>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {action}
    </div>);

}

/* ---------------- Badge ---------------- */
export function Badge({
  children,
  tone = "neutral",
  dot = false,
  className





}: {children: ReactNode;tone?: "success" | "danger" | "warning" | "info" | "neutral" | "violet";dot?: boolean;className?: string;}) {
  return (
    <span className={cn("badge", `badge-${tone}`, className)}>
      {dot && <i className="badge-dot" />}
      {children}
    </span>);

}

export function StatusBadge({ status }: {status: string;}) {
  const map: Record<string, {tone: "success" | "danger" | "warning" | "neutral" | "info";label: string;}> = {
    active: { tone: "success", label: t("فعال") },
    online: { tone: "success", label: t("آنلاین") },
    expired: { tone: "danger", label: t("منقضی") },
    offline: { tone: "danger", label: t("آفلاین") },
    limited: { tone: "warning", label: t("اتمام حجم") },
    disabled: { tone: "neutral", label: t("غیرفعال") },
    unknown: { tone: "neutral", label: t("نامشخص") }
  };
  const item = map[status] ?? { tone: "info" as const, label: status };
  return (
    <Badge tone={item.tone} dot>
      {item.label}
    </Badge>);

}

/* ---------------- Form controls ---------------- */
export function Field({
  label,
  hint,
  error,
  children,
  className






}: {label: string;hint?: string;error?: string;children: ReactNode;className?: string;}) {
  const labelId = useId();
  const helpId = useId();
  const control = isValidElement(children) ? cloneElement(children as ReactElement<Record<string, unknown>>, { "aria-labelledby": labelId, "aria-describedby": error || hint ? helpId : undefined }) : children;
  return (
    <label className={cn("field", className)}>
      <span id={labelId} className="field-label">{label}</span>
      {control}
      {error ? <span id={helpId} className="field-error">{error}</span> : hint ? <span id={helpId} className="field-hint">{hint}</span> : null}
    </label>);

}

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn("input", className)} {...props} />;
}

export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={cn("input select", className)} {...props}>
      {children}
    </select>);

}

export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn("input textarea", className)} {...props} />;
}

export function Toggle({
  checked,
  onChange,
  label,
  disabled





}: {checked: boolean;onChange: (value: boolean) => void;label?: string;disabled?: boolean;}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      className={cn("toggle-row", disabled && "is-disabled")}
      onClick={() => onChange(!checked)}>

      <span className={cn("toggle", checked && "is-on")}>
        <span className="toggle-thumb" />
      </span>
      {label && <span className="toggle-label">{label}</span>}
    </button>);

}

/* ---------------- Modal ---------------- */
export function Modal({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  wide = false








}: {open: boolean;onClose: () => void;title: string;description?: string;children: ReactNode;footer?: ReactNode;wide?: boolean;}) {
  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previous;
      window.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);

  if (!open) return null;
  return createPortal(
    <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div className={cn("modal", wide && "modal-wide")} role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-head">
          <div>
            <h3>{title}</h3>
            {description && <p>{description}</p>}
          </div>
          <button type="button" className="icon-btn" onClick={onClose} aria-label={t("بستن")}>
            <X size={19} />
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>,
    document.body
  );
}

export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  message,
  confirmLabel = t("حذف"),
  loading = false,
  danger = true









}: {open: boolean;onClose: () => void;onConfirm: () => void;title: string;message: string;confirmLabel?: string;loading?: boolean;danger?: boolean;}) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      footer={
      <>
          <Button variant="ghost" onClick={onClose}>{"" + t("انصراف") + " "}

        </Button>
          <Button variant={danger ? "danger" : "primary"} loading={loading} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </>
      }>

      <div className="confirm-content">
        <span className={cn("confirm-icon", danger ? "danger" : "warning")}>
          <AlertTriangle size={24} />
        </span>
        <p>{message}</p>
      </div>
    </Modal>);

}

/* ---------------- Feedback ---------------- */
export function Spinner({ label = t("در حال بارگذاری...") }: {label?: string;}) {
  return (
    <div className="loading-state">
      <Loader2 className="spin" size={24} />
      <span>{label}</span>
    </div>);

}

export function Skeleton({ height = 20, width = "100%" }: {height?: number;width?: string | number;}) {
  return <span className="skeleton" style={{ height, width }} />;
}

export function EmptyState({
  icon,
  title,
  description,
  action





}: {icon: ReactNode;title: string;description: string;action?: ReactNode;}) {
  return (
    <div className="empty-state">
      <span className="empty-icon">{icon}</span>
      <h3>{title}</h3>
      <p>{description}</p>
      {action}
    </div>);

}

export function Progress({
  value,
  tone = "accent",
  className




}: {value: number;tone?: "accent" | "danger" | "warning" | "violet";className?: string;}) {
  return (
    <div className={cn("progress", `progress-${tone}`, className)}>
      <span style={{ width: `${Math.min(100, Math.max(0, value))}%` }} />
    </div>);

}

export function CopyButton({
  value,
  label = t("کپی"),
  className,
  onCopied





}: {value: string;label?: string;className?: string;onCopied?: () => void;}) {
  return (
    <button
      type="button"
      className={cn("copy-btn", className)}
      onClick={async (event) => {
        event.stopPropagation();
        await navigator.clipboard.writeText(value);
        onCopied?.();
      }}>

      {label}
    </button>);

}
