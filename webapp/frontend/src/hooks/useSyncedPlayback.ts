// Compare Player에서 두 video element를 하나의 컨트롤로 동기화
import { useEffect, useRef, useState } from "react";

export type AudioMode = "original" | "dubbed" | "both";

export function useSyncedPlayback(rightEnabled: boolean) {
  const leftRef = useRef<HTMLVideoElement>(null);
  const rightRef = useRef<HTMLVideoElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [audioMode, setAudioMode] = useState<AudioMode>("dubbed");

  useEffect(() => {
    const left = leftRef.current;
    const right = rightRef.current;
    if (left) left.muted = audioMode === "dubbed";
    if (right) right.muted = audioMode === "original" || !rightEnabled;
  }, [audioMode, rightEnabled]);

  const toggle = () => {
    const left = leftRef.current;
    const right = rightRef.current;
    if (!left) return;
    if (isPlaying) {
      left.pause();
      right?.pause();
      setIsPlaying(false);
      return;
    }
    if (rightEnabled && right) right.currentTime = left.currentTime;
    void left.play().then(() => {
      if (rightEnabled && right) void right.play().catch(() => undefined);
      setIsPlaying(true);
    }).catch(() => setIsPlaying(false));
  };

  const seek = (value: number) => {
    const left = leftRef.current;
    const right = rightRef.current;
    if (!left) return;
    left.currentTime = value;
    if (rightEnabled && right) right.currentTime = value;
    setCurrentTime(value);
  };

  const handleLoadedMetadata = () => {
    const left = leftRef.current;
    if (!left) return;
    setDuration(Number.isFinite(left.duration) ? left.duration : 0);
  };

  const handleTimeUpdate = () => {
    const left = leftRef.current;
    const right = rightRef.current;
    if (!left) return;
    setCurrentTime(left.currentTime);
    if (rightEnabled && right && Math.abs(right.currentTime - left.currentTime) > 0.08) {
      right.currentTime = left.currentTime;
    }
  };

  const handleEnded = () => {
    rightRef.current?.pause();
    setIsPlaying(false);
  };

  return { leftRef, rightRef, isPlaying, currentTime, duration, audioMode, setAudioMode, toggle, seek, handleLoadedMetadata, handleTimeUpdate, handleEnded };
}
