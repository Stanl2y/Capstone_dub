// 고정 상단바를 제공하는 프론트 앱 셸
import type { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { cn } from "@/lib/cn";

interface AppShellProps {
  children: ReactNode;
}

const topNav = [
  { label: "Dashboard", to: "/", match: "exact" },
  { label: "Projects", to: "/projects", match: "projects" },
  { label: "New", to: "/runs/new", match: "new" },
] as const;


export function AppShell({ children }: AppShellProps) {
  const { pathname } = useLocation();
  const active = (match: string) => {
    if (match === "exact") return pathname === "/";
    if (match === "new") return pathname === "/runs/new";
    // run 상세는 프로젝트의 일부 — /runs/:id/* 도 Projects 탭이 활성으로
    if (match === "projects") {
      if (pathname === "/projects" || pathname.startsWith("/projects/")) return true;
      return /^\/runs\/[^/]+/.test(pathname) && pathname !== "/runs/new";
    }
    return false;
  };

  return (
    <div className="min-h-screen bg-background text-on-surface">
      <header className="fixed left-0 top-0 z-40 flex h-[56px] w-full items-center border-b border-border-hairline bg-surface px-5">
        <Link to="/" className="flex h-full items-center pr-6 font-display text-heading-sm text-primary">
          DubEngine AI
        </Link>
        <nav className="flex h-full items-center gap-1 text-body-sm-strong text-secondary">
          {topNav.map((item) => {
            const isActive = active(item.match);
            return (
              <Link
                key={item.label}
                to={item.to}
                aria-current={isActive ? "page" : undefined}
                className={cn(
                  "flex h-full items-center border-b-2 px-4 transition-colors",
                  isActive ? "border-primary text-primary" : "border-transparent hover:text-primary",
                )}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="ml-auto flex items-center gap-3">
          <Link to="/runs/new" className="hidden h-9 items-center rounded-full bg-primary px-4 text-body-sm-strong text-white hover:bg-ink-deep md:inline-flex">
            Start Dubbing
          </Link>
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-primary font-mono text-caption-strong text-white">AI</div>
        </div>
      </header>

      <main className="pt-[56px]">{children}</main>
    </div>
  );
}
