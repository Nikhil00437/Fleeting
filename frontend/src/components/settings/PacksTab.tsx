/** #495: install a theme + prompt pack. Kept out of SettingsView because the
 * only thing it does that the other tabs do not is apply tokens to the live
 * document — that is a side effect, not a setting. */
import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";
import { errorMessage } from "../settingsState";
import type { Pack } from "../../types";
import { applyTokens, clearTokens, findPack } from "../packs";
import PackList from "../PackList";

export default function PacksTab({
  active,
  onToast,
}: {
  active: string;
  onToast: (message: string, kind?: "ok" | "err") => void;
}) {
  const [packs, setPacks] = useState<Pack[] | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [dir, setDir] = useState("");
  // #495. Kept so a pack change can revert the previous pack's tokens rather
  // than leaving them layered under the new one — once set, an inline
  // `--ink-100` beats every stylesheet, so there is no undo by other means.
  const [applied, setApplied] = useState<string[]>([]);

  const load = useCallback(() => {
    api
      .packs(dir || undefined)
      .then((r) => {
        setPacks(r.packs);
        setErrors(r.errors ?? []);
        setLoadError(null);
      })
      .catch((e: unknown) => setLoadError(errorMessage(e)));
  }, [dir]);

  useEffect(load, [load]);

  useEffect(() => {
    if (!packs || !active) return;
    const pack = findPack(packs, active);
    if (!pack) return;
    clearTokens(applied);
    setApplied(applyTokens(pack.theme));
    // `applied` is deliberately not a dependency: including it re-applies the
    // same tokens on every revert, which never converges.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [packs, active]);

  async function install(name: string) {
    try {
      const res = await api.installPack(name, dir || undefined);
      setApplied(applyTokens(res.theme));
      onToast(`Installed ${res.installed}`, "ok");
      load();
    } catch (e) {
      onToast(errorMessage(e), "err");
    }
  }

  return (
    <section className="glass-studio space-y-4 rounded-2xl p-5">
      <div>
        <h2 className="text-sm font-semibold text-ink-100">Themes & Prompt Packs</h2>
        <p className="text-xs text-ink-400">
          A pack is a JSON file with a theme and some prompts. Nothing is downloaded.
        </p>
      </div>

      <label className="block">
        <span className="micro-label !text-[9px]">Folder</span>
        <input
          value={dir}
          onChange={(e) => setDir(e.target.value)}
          placeholder="~/.config/fleeting/packs/"
          className="mt-1 w-full rounded-lg border border-ink-800 bg-ink-950/60 px-2.5 py-1.5 font-mono text-[11px] text-ink-200 placeholder:text-ink-600"
        />
      </label>

      <PackList packs={packs} errors={errors} error={loadError} dir={dir} onInstall={install} />
    </section>
  );
}