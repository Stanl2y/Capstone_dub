// 백엔드 static mount 규칙에 맞춰 artifact 경로를 브라우저 URL로 변환
export function toStaticUrl(path: string | null | undefined): string | null {
  if (!path) return null;
  const normalized = path.replace(/\\/g, "/").replace(/^\.\//, "");
  if (/^https?:\/\//.test(normalized) || normalized.startsWith("/static/")) return normalized;
  const cleaned = normalized.replace(/^\//, "");
  // segment 별로 percent-encode — 한국어/공백/특수문자 path 가 일부 환경에서 자동 인코딩 누락되어 404 나는 케이스 방지
  const encoded = cleaned.split("/").map(encodeURIComponent).join("/");
  // prefix 매칭만 — substring 매칭이면 "chunks/input/.." 의 input/ 가 잘못 잡혀서 A 트랙이 404 뜸
  for (const root of ["input", "chunks", "dub", "output"] as const) {
    if (cleaned.startsWith(`${root}/`)) return `/static/${encoded}`;
  }
  return `/static/${encoded}`;
}

export function fileName(path: string | null | undefined): string {
  if (!path) return "—";
  return path.replace(/\\/g, "/").split("/").filter(Boolean).at(-1) ?? path;
}
