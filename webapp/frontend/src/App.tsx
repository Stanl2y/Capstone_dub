// 참조 디자인 AppShell과 새 정보 구조를 연결하는 라우트 트리
import { Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { Dashboard } from "@/pages/Dashboard";
import { Upload } from "@/pages/Upload";
import { Progress } from "@/pages/Progress";
import { Chunks } from "@/pages/Chunks";
import { Compare } from "@/pages/Compare";
import { Metrics } from "@/pages/Metrics";
import { Activity } from "@/pages/Activity";
import { Projects } from "@/pages/Projects";
import { ProjectDetail } from "@/pages/ProjectDetail";
import { StepDetail } from "@/pages/StepDetail";

export default function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/projects" element={<Projects />} />
        <Route path="/projects/:inputStem" element={<ProjectDetail />} />
        <Route path="/runs/new" element={<Upload />} />
        <Route path="/runs/:id" element={<Progress />} />
        <Route path="/runs/:id/progress" element={<Progress />} />
        <Route path="/runs/:id/steps/:stepName" element={<StepDetail />} />
        <Route path="/runs/:id/chunks" element={<Chunks />} />
        <Route path="/runs/:id/compare" element={<Compare />} />
        <Route path="/runs/:id/metrics" element={<Metrics />} />
        <Route path="/runs/:id/activity" element={<Activity />} />
      </Routes>
    </AppShell>
  );
}
