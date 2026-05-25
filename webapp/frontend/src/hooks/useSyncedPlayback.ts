// Compare Player에서 단일 video와 원본 audio track을 함께 제어
import { useEffect, useRef, useState } from "react";

export type AudioMode = "original" | "dubbed";

export function useSyncedPlayback(enabled: boolean) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const originalAudioRef = useRef<HTMLAudioElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [audioMode, setAudioModeState] = useState<AudioMode>("dubbed");

  useEffect(() => {
    const video = videoRef.current;
    if (!enabled) {
      video?.pause();
      originalAudioRef.current?.pause();
      setIsPlaying(false);
      setCurrentTime(0);
      setDuration(0);
      return;
    }
    if (video) video.muted = audioMode === "original";
  }, [audioMode, enabled]);

  const syncOriginalTime = (value: number) => {
    const audio = originalAudioRef.current;
    if (audio && Number.isFinite(value)) audio.currentTime = value;
    return audio;
  };

  const toggle = () => {
    const video = videoRef.current;
    if (!video || !enabled) return;
    if (isPlaying) {
      video.pause();
      originalAudioRef.current?.pause();
      setIsPlaying(false);
      return;
    }

    video.muted = audioMode === "original";
    const originalAudio = audioMode === "original" ? syncOriginalTime(video.currentTime) : null;
    if (audioMode === "dubbed") originalAudioRef.current?.pause();
    const originalPlay = originalAudio ? originalAudio.play() : Promise.resolve();
    void Promise.all([video.play(), originalPlay]).then(() => setIsPlaying(true)).catch(() => {
      originalAudio?.pause();
      setIsPlaying(!video.paused);
    });
  };

  const seek = (value: number) => {
    const video = videoRef.current;
    const next = Number.isFinite(value) ? Math.max(0, value) : 0;
    const bounded = duration > 0 ? Math.min(next, duration) : next;
    if (video) video.currentTime = bounded;
    syncOriginalTime(bounded);
    setCurrentTime(bounded);
  };

  const setAudioMode = (mode: AudioMode) => {
    if (mode === audioMode) return;
    const video = videoRef.current;
    const time = video ? video.currentTime : currentTime;
    const shouldResume = Boolean(video && !video.paused && !video.ended);
    setAudioModeState(mode);
    setCurrentTime(time);

    if (!video) return;
    if (mode === "original") {
      video.muted = true;
      const originalAudio = syncOriginalTime(time);
      if (shouldResume && originalAudio) {
        void originalAudio.play().then(() => setIsPlaying(true)).catch(() => setIsPlaying(!video.paused));
      }
      return;
    }

    originalAudioRef.current?.pause();
    video.muted = false;
    setIsPlaying(shouldResume);
  };

  const handleLoadedMetadata = () => {
    const video = videoRef.current;
    if (!video) return;
    video.muted = audioMode === "original";
    setDuration(Number.isFinite(video.duration) ? video.duration : 0);
  };

  const handleAudioLoadedMetadata = () => {
    const video = videoRef.current;
    if (!video) return;
    syncOriginalTime(video.currentTime);
  };

  const handleTimeUpdate = () => {
    const video = videoRef.current;
    const originalAudio = originalAudioRef.current;
    if (!video) return;
    setCurrentTime(video.currentTime);
    if (audioMode === "original" && originalAudio && !originalAudio.paused && Math.abs(originalAudio.currentTime - video.currentTime) > 0.12) {
      originalAudio.currentTime = video.currentTime;
    }
  };

  const handleEnded = () => {
    originalAudioRef.current?.pause();
    setIsPlaying(false);
  };

  return {
    videoRef,
    originalAudioRef,
    isPlaying,
    currentTime,
    duration,
    audioMode,
    setAudioMode,
    toggle,
    seek,
    handleLoadedMetadata,
    handleAudioLoadedMetadata,
    handleTimeUpdate,
    handleEnded,
  };
}
