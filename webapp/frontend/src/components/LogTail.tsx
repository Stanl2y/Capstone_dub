// 검은 터미널 패널에 맞춘 실시간 로그 tail 출력
import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/cn";

interface LogTailProps {
  lines: string[];
  className?: string;
  emptyLabel?: string;
}

export function LogTail({ lines, className, emptyLabel = "— 로그 대기 중 —" }: LogTailProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);

  useEffect(() => {
    if (!autoScroll || !containerRef.current) return;
    containerRef.current.scrollTop = containerRef.current.scrollHeight;
  }, [lines, autoScroll]);

  const onScroll = () => {
    if (!containerRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = containerRef.current;
    setAutoScroll(scrollHeight - scrollTop - clientHeight < 50);
  };

  return (
    <div ref={containerRef} onScroll={onScroll} className={cn("overflow-y-auto font-mono text-code-sm leading-relaxed", className)}>
      {lines.length === 0 ? (
        <div className="text-mute">{emptyLabel}</div>
      ) : (
        lines.map((line, idx) => (
          <div key={idx} className={cn("whitespace-pre-wrap break-all", line.toLowerCase().includes("warn") && "text-term-yellow", line.toLowerCase().includes("error") && "text-term-red")}>
            {line}
          </div>
        ))
      )}
    </div>
  );
}
