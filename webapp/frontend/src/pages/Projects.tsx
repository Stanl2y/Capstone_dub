// 영상 단위 (input_stem) 로 묶은 프로젝트 카드 그리드
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, Plus } from "lucide-react";
import { api, type ProjectSummary } from "@/api/client";
import { fileName } from "@/lib/staticUrl";

export function Projects() {
  const projectsQuery = useQuery({ queryKey: ["projects"], queryFn: api.listProjects, refetchInterval: 15000, retry: 1 });
  const projects = projectsQuery.data ?? [];

  return (
    <section className="min-h-[calc(100vh-56px)] bg-background px-8 py-7">
      <div className="mx-auto max-w-[1280px]">
        <header className="flex flex-wrap items-end justify-between gap-4 border-b border-border-hairline pb-5">
          <div>
            <p className="font-mono text-data-label uppercase text-data-label">Projects</p>
            <h1 className="mt-2 font-display text-heading-lg text-primary">영상별 더빙 프로젝트</h1>
            <p className="mt-2 text-body-sm text-secondary">같은 입력 영상으로 시도한 run 들을 한 묶음으로 봅니다. 카드를 열면 그 영상의 모든 시도가 보입니다.</p>
          </div>
          <Link to="/runs/new" className="inline-flex h-10 items-center gap-2 rounded-full bg-primary px-5 text-body-sm-strong text-white hover:bg-ink-deep">
            <Plus className="h-4 w-4" />
            New Project
          </Link>
        </header>

        {projectsQuery.isLoading ? (
          <div className="py-10 text-body-sm text-mute">프로젝트를 불러오는 중입니다.</div>
        ) : projects.length === 0 ? (
          <div className="mt-8 rounded-[2rem] border border-border-hairline bg-surface-container-lowest p-8 text-center">
            <h2 className="font-display text-heading-md text-primary">아직 프로젝트가 없습니다.</h2>
            <p className="mt-2 text-body-sm text-secondary">New Project 로 입력 영상을 올리면 첫 프로젝트가 생성됩니다.</p>
          </div>
        ) : (
          <ul className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {projects.map((project) => <ProjectCard key={project.input_stem} project={project} />)}
          </ul>
        )}
      </div>
    </section>
  );
}

function ProjectCard({ project }: { project: ProjectSummary }) {
  return (
    <li>
      <Link
        to={`/projects/${encodeURIComponent(project.input_stem)}`}
        className="flex h-full flex-col rounded-[2rem] border border-border-hairline bg-surface-container-lowest p-5 transition hover:bg-surface-soft"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="truncate font-display text-heading-sm text-primary">{fileName(project.input_video)}</h2>
            <p className="mt-1 truncate font-mono text-code-sm text-mute">{project.input_stem}</p>
          </div>
          <ArrowUpRight className="h-4 w-4 shrink-0 text-mute" />
        </div>

        <div className="mt-4 grid grid-cols-3 gap-2 font-mono text-code-sm">
          <Stat label="runs" value={project.run_count} tone="primary" />
          <Stat label="success" value={project.success_count} tone="success" />
          <Stat label="failed" value={project.failed_count + project.canceled_count} tone="muted" />
        </div>

        <div className="mt-4">
          <div className="mb-1 flex items-center justify-between font-mono text-caption-sm text-secondary">
            <span>{project.last_status ? `latest · ${project.last_status}` : "—"}</span>
            <span>{project.last_progress_pct}%</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-surface-container">
            <div className="h-full rounded-full bg-primary" style={{ width: `${project.last_progress_pct}%` }} />
          </div>
        </div>

        <p className="mt-4 font-mono text-caption-sm text-mute">updated · {formatRelative(project.updated_at)}</p>
      </Link>
    </li>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone: "primary" | "success" | "muted" }) {
  const color = tone === "success" ? "text-status-done" : tone === "primary" ? "text-primary" : "text-mute";
  return (
    <div className="rounded-[1rem] bg-surface-soft p-3">
      <p className="font-mono text-data-label uppercase text-data-label">{label}</p>
      <p className={`mt-1 font-display text-heading-sm ${color}`}>{value}</p>
    </div>
  );
}

function formatRelative(value: number): string {
  const ms = value > 10_000_000_000 ? value : value * 1000;
  const diff = Date.now() - ms;
  const min = Math.round(diff / 60_000);
  if (min < 1) return "방금";
  if (min < 60) return `${min}분 전`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}시간 전`;
  const day = Math.round(hr / 24);
  if (day < 7) return `${day}일 전`;
  return new Date(ms).toLocaleDateString("ko-KR", { month: "2-digit", day: "2-digit" });
}
