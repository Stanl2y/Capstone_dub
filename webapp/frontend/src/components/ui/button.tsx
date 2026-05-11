// design.md 의 button-primary / button-secondary / button-pill-on-dark 패턴을 강제하는 pill 래퍼
// 모든 인터랙티브 버튼은 이 컴포넌트만 사용 — shadcn 디폴트 rounded-md 가 새어들어오지 않도록
import { cva, type VariantProps } from "class-variance-authority";
import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

const buttonStyles = cva(
  // 모든 variant 공통 — pill 강제, 14px 500 weight, 36px height
  "inline-flex items-center justify-center rounded-full text-button-md transition-colors disabled:cursor-not-allowed disabled:bg-surface-soft disabled:text-mute focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring",
  {
    variants: {
      variant: {
        // button-primary — 검정 pill, on-primary 흰 텍스트
        primary: "bg-primary text-white hover:bg-ink-deep active:bg-ink-deep",
        // button-secondary — 캔버스 + hairline-strong 1px border
        secondary: "bg-canvas text-primary border border-hairline-strong hover:bg-surface-soft",
        // button-pill-on-dark — 다크 surface 위 흰 pill
        "pill-on-dark": "bg-canvas text-primary hover:bg-surface-soft",
      },
      size: {
        md: "h-9 px-5", // 36px height, 20px horizontal padding (design.md spec)
        sm: "h-8 px-4 text-body-sm-strong",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonStyles> {}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => (
    <button ref={ref} className={cn(buttonStyles({ variant, size }), className)} {...props} />
  ),
);
Button.displayName = "Button";
