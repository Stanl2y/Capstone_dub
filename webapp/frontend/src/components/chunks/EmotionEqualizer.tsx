import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";

const EMOTION_KEYS = [
  "angry",
  "disgusted",
  "fearful",
  "happy",
  "neutral",
  "other",
  "sad",
  "surprised",
  "unknown",
] as const;

type EmotionKey = (typeof EMOTION_KEYS)[number];

interface EmotionEqualizerProps {
  scores: Record<string, number> | null | undefined;
  label: string | null | undefined;
  onSave: (next: { label: string; scores: Record<string, number> }) => void;
  onCancel: () => void;
  onChange?: (next: { label: string; scores: Record<string, number> }) => void;
  pending?: boolean;
}

export function EmotionEqualizer({ scores, label, onSave, onCancel, onChange, pending }: EmotionEqualizerProps) {
  const initial = useMemo(() => buildInitial(scores), [scores]);
  const [draft, setDraft] = useState<Record<EmotionKey, number>>(initial);

  useEffect(() => {
    setDraft(initial);
  }, [initial]);

  const dominant = useMemo(() => pickDominant(draft, label), [draft, label]);

  useEffect(() => {
    onChange?.({ label: dominant, scores: draft });
  }, [draft, dominant, onChange]);

  const setOne = (key: EmotionKey, value: number) => {
    setDraft((prev) => ({ ...prev, [key]: clamp01(value) }));
  };

  const reset = () => setDraft(initial);

  const normalize = () => {
    const total = Object.values(draft).reduce((acc, v) => acc + v, 0);
    if (total <= 0) return;
    const next = { ...draft };
    (Object.keys(next) as EmotionKey[]).forEach((key) => {
      next[key] = Number((draft[key] / total).toFixed(4));
    });
    setDraft(next);
  };

  const save = () => {
    onSave({ label: dominant, scores: draft });
  };

  return (
    <div>
      <div className="mb-4 flex items-center justify-between gap-3">
        <span className="font-mono text-data-label uppercase text-data-label">Adjust scores</span>
        <span className="rounded-full bg-primary px-3 py-1 font-mono text-caption-strong text-white">label / {dominant}</span>
      </div>

      <div className="space-y-3">
        {EMOTION_KEYS.map((key) => {
          const value = draft[key];
          const pct = Math.round(value * 100);
          return (
            <label key={key} className="block">
              <div className="mb-1 flex justify-between font-mono text-code-sm text-secondary">
                <span>{key}</span>
                <span>{pct}%</span>
              </div>
              <div className="relative h-7">
                <div className="absolute inset-x-0 top-1/2 h-2 -translate-y-1/2 overflow-hidden rounded-full bg-surface-container">
                  <div className="h-full rounded-full bg-primary" style={{ width: `${pct}%` }} />
                </div>
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.01}
                  value={value}
                  disabled={pending}
                  onChange={(event) => setOne(key, Number(event.target.value))}
                  className="absolute inset-x-0 top-1/2 h-5 w-full -translate-y-1/2 cursor-pointer bg-transparent accent-black disabled:cursor-not-allowed"
                />
              </div>
            </label>
          );
        })}
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={reset} disabled={pending}>Reset</Button>
          <Button variant="secondary" size="sm" onClick={normalize} disabled={pending}>Normalize</Button>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={onCancel} disabled={pending}>Cancel</Button>
          <Button size="sm" onClick={save} disabled={pending}>{pending ? "Saving" : "Save"}</Button>
        </div>
      </div>
    </div>
  );
}

function buildInitial(scores: Record<string, number> | null | undefined): Record<EmotionKey, number> {
  const out = {} as Record<EmotionKey, number>;
  for (const key of EMOTION_KEYS) {
    out[key] = clamp01(Number(scores?.[key] ?? 0));
  }
  return out;
}

function pickDominant(draft: Record<EmotionKey, number>, fallbackLabel: string | null | undefined): string {
  let best: EmotionKey = "neutral";
  let bestVal = -1;
  for (const key of EMOTION_KEYS) {
    if (draft[key] > bestVal) {
      best = key;
      bestVal = draft[key];
    }
  }
  if (bestVal <= 0 && fallbackLabel) return fallbackLabel;
  return best;
}

function clamp01(value: number): number {
  if (Number.isNaN(value)) return 0;
  return Math.max(0, Math.min(1, value));
}
