import { forwardRef } from "react";
import type { ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md" | "lg";
};

const variantClasses = {
  primary: "border-primary bg-primary text-primary-foreground hover:border-primary-hover hover:bg-primary-hover",
  secondary: "border-border bg-transparent text-foreground hover:border-primary/60 hover:text-primary-text",
  ghost: "border-transparent bg-transparent text-foreground hover:bg-subtle",
  danger: "border-danger bg-transparent text-danger hover:bg-danger-pale",
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
        "inline-flex items-center justify-center gap-2 rounded-[2px] border font-semibold transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-50",
        variantClasses[variant],
        sizeClasses[size],
        className
      )}
      {...props}
    />
  );
});
