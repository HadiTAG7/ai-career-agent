import { forwardRef } from "react";
import type { ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md" | "lg";
};

const variantClasses = {
  primary: "border-emerald bg-emerald text-white hover:border-emerald-dark hover:bg-emerald-dark",
  secondary: "border-border bg-white text-ink hover:border-emerald hover:text-emerald",
  ghost: "border-transparent bg-transparent text-ink hover:bg-slate-50",
  danger: "border-danger bg-white text-danger hover:bg-danger-pale",
};

const sizeClasses = {
  sm: "min-h-11 px-4 text-[13px]",
  md: "min-h-11 px-5 text-sm",
  lg: "min-h-[52px] px-7 text-base",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant = "primary", size = "md", type = "button", ...props },
  ref
) {
  return (
    <button
      ref={ref}
      type={type}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-lg border font-semibold transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-50",
        variantClasses[variant],
        sizeClasses[size],
        className
      )}
      {...props}
    />
  );
});
