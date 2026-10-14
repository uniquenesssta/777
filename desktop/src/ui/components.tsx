import type {
  ComponentPropsWithRef,
  InputHTMLAttributes,
  ReactNode,
} from "react";
import { useRef, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
export const cn = (...v: (string | false | undefined)[]) =>
  v.filter(Boolean).join(" ");
export function Button({
  variant = "primary",
  className,
  ...props
}: ComponentPropsWithRef<"button"> & {
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
  const [failed, setFailed] = useState(false);
  const file = {
    chevron: "a09ba.svg",
    check: "09c30.svg",
    trash: "74181.svg",
    "discount-trash": "2eb61.svg",
    lock: "7bfb4.svg",
  }[name];
  return failed ? <span className="icon-fallback" role="img" aria-label="图标不可用" title="图标不可用">!</span>
    : <img className="icon" alt="" src={`/icons/${file}`} onError={()=>setFailed(true)} />;
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
  const previousFocus = useRef<HTMLElement | null>(null);
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content" data-compact={compact}
          onOpenAutoFocus={()=>{previousFocus.current=document.activeElement instanceof HTMLElement?document.activeElement:null;}}
          onCloseAutoFocus={event=>{
            const target=previousFocus.current?.isConnected?previousFocus.current:document.querySelector<HTMLElement>('main.workspace');
            if(target) {event.preventDefault();target.focus();}
          }}>
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
