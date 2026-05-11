// design.md terminal-card 패턴 — 진행 로그/15단계 표시에 차용
import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/cn";

interface TerminalCardProps extends HTMLAttributes<HTMLDivElement> {
  title?: string;
  children: ReactNode;
}

export function TerminalCard({ title, children, className, ...props }: TerminalCardProps) {
  return (
    <div className={cn("bg-canvas border border-hairline rounded-lg overflow-hidden", className)} {...props}>
      {/* macOS traffic-light 헤더 + 선택적 타이틀 */}
      <div className="flex items-center gap-sm px-lg py-sm border-b border-hairline">
        <span className="w-3 h-3 rounded-full bg-term-red" aria-hidden />
        <span className="w-3 h-3 rounded-full bg-term-yellow" aria-hidden />
        <span className="w-3 h-3 rounded-full bg-term-green" aria-hidden />
        {title && (
          <span className="ml-sm text-caption-sm text-mute font-mono">{title}</span>
        )}
      </div>
      <div className="p-lg font-mono text-code-sm text-primary">{children}</div>
    </div>
  );
}
