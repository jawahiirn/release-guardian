import type { ButtonHTMLAttributes } from "react";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost";
};

export function Button({ variant = "primary", className = "", ...props }: ButtonProps) {
  const variantClass = variant === "primary" ? "primary" : "ghost";
  return <button className={`${variantClass} ${className}`.trim()} {...props} />;
}
