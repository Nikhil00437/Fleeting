import { useCallback, useEffect, useRef, useState } from "react";
import { storeMicId, storedMicId } from "../../mic";
import { inputCls, labelCls } from "./shared";

/**
 * #384: pick the input device and hear it while choosing — device labels are
 * only populated after the user grants mic permission, so enumeration
 * re-runs once after the first test run.
 */
export default function MicPicker() {
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [selected, setSelected] = useState<string>(() => storedMicId() ?? "");
  const [testing, setTesting] = useState(false);
  const [level, setLevel] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const rafRef = useRef(0);

  const refresh = useCallback(async () => {
    try {
      const list = await navigator.mediaDevices.enumerateDevices();
      setDevices(list.filter((d) => d.kind === "audioinput"));
    } catch {
      setDevices([]);
    }
  }, []);

  useEffect(() => {
    void refresh();
    return () => {
      cancelAnimationFrame(rafRef.current);
      streamRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, [refresh]);

  async function startTest() {
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: selected ? { deviceId: { ideal: selected } } : true,
      });
      streamRef.current = stream;
      const ctx = new AudioContext();
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      ctx.createMediaStreamSource(stream).connect(analyser);
      const buf = new Uint8Array(analyser.frequencyBinCount);
      const tick = () => {
        analyser.getByteTimeDomainData(buf);
        let peak = 0;
        for (let i = 0; i < buf.length; i++) peak = Math.max(peak, Math.abs(buf[i] - 128) / 128);
        setLevel(peak);
        rafRef.current = requestAnimationFrame(tick);
      };
      rafRef.current = requestAnimationFrame(tick);
      setTesting(true);
      await refresh(); // labels appear after permission grant
    } catch {
      setError("microphone unavailable — check browser permissions");
    }
  }

  function stopTest() {
    cancelAnimationFrame(rafRef.current);
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setTesting(false);
    setLevel(0);
  }

  return (
    <div className="mt-5 space-y-3 border-t border-ink-800/80 pt-4">
      <label className={labelCls}>Microphone</label>
      <select
        value={selected}
        onChange={(e) => {
          setSelected(e.target.value);
          storeMicId(e.target.value || null);
        }}
        className={inputCls}
      >
        <option value="">System default</option>
        {devices.map((d, i) => (
          <option key={d.deviceId || i} value={d.deviceId}>
            {d.label || `Microphone ${i + 1}`}
          </option>
        ))}
      </select>
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => (testing ? stopTest() : void startTest())}
          className="rounded-lg border border-ink-700 bg-ink-900 px-3 py-1 text-[11px] font-medium text-ink-200 hover:border-ember-400/40"
        >
          {testing ? "Stop test" : "Test mic"}
        </button>
        <div className="flex h-4 flex-1 items-center gap-[3px]" aria-hidden>
          {Array.from({ length: 24 }).map((_, i) => (
            <div
              key={i}
              className={`w-[3px] rounded-full transition-all ${i / 24 < level ? "bg-ember-400" : "bg-ink-800"}`}
              style={{ height: `${Math.min(100, 30 + level * 70)}%` }}
            />
          ))}
        </div>
      </div>
      {error && <p className="text-[11px] text-red-300">{error}</p>}
    </div>
  );
}
