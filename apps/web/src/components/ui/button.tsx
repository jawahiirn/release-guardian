import type { ButtonHTMLAttributes } from "react";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost" | "danger";
  size?: "sm" | "md";
};

export function Button({ variant = "primary", size = "md", className = "", ...props }: ButtonProps) {
  return <button className={`button button-${variant} button-${size} ${className}`.trim()} {...props} />;
}
