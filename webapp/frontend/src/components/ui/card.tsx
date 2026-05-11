// design.md pricing-card 패턴 — 1px hairline + rounded-lg + 흰 캔버스. 그림자 금지.
import { forwardRef, type HTMLAttributes } from "react";
import { cn } from "@/lib/cn";

export const Card = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn("bg-canvas border border-hairline rounded-lg p-xxl", className)}
      {...props}
    />
  ),
);
Card.displayName = "Card";

// 단 1회 inverted dark surface — final_score 등 가장 강조하고 싶은 KPI 1개에만 사용
export const CardDark = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn("bg-surface-dark text-white rounded-lg p-xxl", className)}
      {...props}
    />
  ),
);
CardDark.displayName = "CardDark";
