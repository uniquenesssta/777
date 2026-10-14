import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
} from "react";
import * as Dialog from "@radix-ui/react-dialog";
export const cn = (...v: (string | false | undefined)[]) =>
  v.filter(Boolean).join(" ");
export function Button({
  variant = "primary",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "outline" | "ghost" | "danger";
}) {
  return (
    <button
      className={cn("button", className)}
      data-variant={variant}
      type="button"
      {...props}
    />
  );
}
export function Input({
  className,
  ...props
}: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn("input", className)} {...props} />;
}
export function Field({
  label,
  children,
  compact = false,
}: {
  label: string;
  children: ReactNode;
  compact?: boolean;
}) {
  return (
    <label className={cn("field", compact && "compact-field")}>
      <span>{label}</span>
      {children}
    </label>
  );
}
export function Badge({
  children,
  muted = false,
}: {
  children: ReactNode;
  muted?: boolean;
}) {
  return (
    <span className="badge" data-muted={muted}>
      {children}
    </span>
  );
}
export function Alert({
  children,
  error = false,
}: {
  children: ReactNode;
  error?: boolean;
}) {
  return (
    <div className="alert" data-error={error} role={error ? "alert" : "status"}>
      {children}
    </div>
  );
}
export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}
export function Icon({
  name,
}: {
  name: "chevron" | "check" | "trash" | "discount-trash" | "lock";
}) {
  const file = {
    chevron: "a09ba.svg",
    check: "09c30.svg",
    trash: "74181.svg",
    "discount-trash": "2eb61.svg",
    lock: "7bfb4.svg",
  }[name];
  return <img className="icon" alt="" src={`/icons/${file}`} />;
}
export function Modal({
  open,
  onOpenChange,
  title,
  description,
  children,
  compact = false,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  title: string;
  description?: string;
  children: ReactNode;
  compact?: boolean;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content" data-compact={compact}>
          <Dialog.Title className="dialog-title">{title}</Dialog.Title>
          <Dialog.Description
            className={cn("dialog-description", !description && "sr-only")}
          >
            {description ?? title}
          </Dialog.Description>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
