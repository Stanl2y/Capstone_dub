// design.md text-input 패턴 — pill 모양 입력 (rounded-full, 40px height, hairline border)
import { forwardRef, type InputHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

export const PillInput = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "h-10 px-lg rounded-full border border-hairline bg-canvas text-body-md text-primary",
        "placeholder:text-mute focus:outline-none focus:border-primary focus-visible:ring-2 focus-visible:ring-focus-ring",
        className,
      )}
      {...props}
    />
  ),
);
PillInput.displayName = "PillInput";
