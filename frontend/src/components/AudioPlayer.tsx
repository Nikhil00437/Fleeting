import { useEffect, useRef } from "react";

/**
 * #88: audio playback with click-a-word-to-seek. Words come from whisper's
 * word timestamps stored on source.transcription.words.
 *
 * #319: `seekTo` lets an outside search result jump the player — the `key`
 * changes every request, so re-seeking the same time still fires the effect.
 */
export default function AudioPlayer({
  noteId,
  words,
  seekTo,
}: {
  noteId: string;
  words: Array<{ w: string; s: number; e: number }>;
  seekTo?: { t: number; key: number } | null;
}) {
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    if (!seekTo || !audioRef.current) return;
    audioRef.current.currentTime = seekTo.t;
    void audioRef.current.play();
  }, [seekTo?.key, seekTo?.t]);

  return (
    <div className="mt-3 rounded-xl border border-white/[0.06] bg-white/[0.02] p-3">
      <audio ref={audioRef} controls preload="metadata" src={`/api/notes/${noteId}/audio`} className="w-full" />
      {words.length > 0 && (
        <p className="mt-2 text-[12.5px] leading-relaxed text-ink-300">
          {words.map((w, i) => (
            <button
              key={i}
              title={`${w.s.toFixed(1)}s`}
              onClick={() => {
                if (audioRef.current) {
                  audioRef.current.currentTime = w.s;
                  void audioRef.current.play();
                }
              }}
              className="hover:text-ember-300 hover:underline underline-offset-2"
            >
              {w.w}
            </button>
          ))}
        </p>
      )}
    </div>
  );
}
