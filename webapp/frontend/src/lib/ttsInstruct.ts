// CosyVoice 학습 분포에 정합한 wrapper — "You are a helpful assistant. " prefix + <|endofprompt|> 토큰을 UI 에서 가리고 저장 시 자동 부여
// storage(master_timeline) 에는 두 wrapper 모두 유지 — tts_runtime 이 그 형식을 기대함
const END_TOKEN = "<|endofprompt|>";
const PREFIX = "You are a helpful assistant.";
const TOKEN_RE = /<\|endofprompt\|>/g;
const TRAILING_TOKEN_RE = /(?:\s*<\|endofprompt\|>\s*)+$/g;
const LEADING_PREFIX_RE = /^\s*you are a helpful assistant\.\s*/i;

// 표시·초기 시드용 — 시작의 prefix 와 끝의 토큰을 모두 정돈해서 사용자에게 본문만 보이게
export function stripEndOfPrompt(text: string | null | undefined): string {
  if (!text) return "";
  return text.replace(LEADING_PREFIX_RE, "").replace(TRAILING_TOKEN_RE, "").trimEnd();
}

// onChange 입력용 — wrapper 만 제거 (사용자가 누른 공백·줄바꿈은 그대로 보존)
export function stripTokenOnly(text: string): string {
  return text.replace(LEADING_PREFIX_RE, "").replace(TOKEN_RE, "");
}

// 저장 직전 자동 부여 — prefix + 본문 + endofprompt 형식으로 wrap
export function ensureEndOfPrompt(text: string): string {
  const stripped = stripEndOfPrompt(text);
  if (!stripped) return "";
  return `${PREFIX} ${stripped}${END_TOKEN}`;
}

// CJK (한자) + 한글 감지 — CosyVoice instruct 는 영어 분포에서만 학습됐어 안 그러면 합성 텍스트로 오인됨
const CJK_HANGUL_RE = /[㐀-鿿가-힯぀-ヿ]/;
export function hasNonLatinScript(text: string): boolean {
  return CJK_HANGUL_RE.test(text);
}
