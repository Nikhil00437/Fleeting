import { useState } from "react";
import MicPicker from "./MicPicker";
import { api } from "../../api";
import { BotIcon, CpuIcon, MicIcon, SparkIcon } from "../Icons";
import { fmtMB, inputCls, labelCls, Toggle, type FormProps } from "./shared";
import type { WhisperProgress } from "../../types";

interface Props extends FormProps {
  /** Live download/load progress pushed over SSE. */
  whisperProgress?: WhisperProgress | null;
  /** Re-probes settings/health, so the test buttons reflect a fresh read. */
  loadAll: () => void;
}

/** AI & Speech tab: LLM provider/model/key and the whisper transcription tier. */
export default function AiTab({
  s,
  patch,
  save,
  whisperProgress,
  loadAll,
}: Props) {
  const [llmTest, setLlmTest] = useState<{ ok?: boolean; text: string; models?: string[] } | null>(
    null,
  );
  const [whisperTest, setWhisperTest] = useState<{ ok?: boolean; text: string } | null>(null);
  const [apiKeyDraft, setApiKeyDraft] = useState("");
  const [whisperBusy, setWhisperBusy] = useState(false);

  const wp: WhisperProgress | null = whisperProgress ?? s.transcribe_progress ?? null;
  const cachedWhisperSet = new Set(
    (s.transcribe_cached_models as string[] | undefined) ?? [],
  );
  const isWhisperWorking =
    !!whisperBusy || wp?.status === "downloading" || wp?.status === "loading";

  /** Blank draft means "leave the stored key alone"; only a real value writes. */
  async function commitApiKey() {
    const key = apiKeyDraft.trim();
    if (!key) return;
    setApiKeyDraft("");
    await save({ llm_api_key: key }, "API key saved");
  }

  async function clearApiKey() {
    setApiKeyDraft("");
    await save({ llm_api_key: "" }, "API key cleared");
  }

  return (
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            {/* Local LLM Compartment */}
            <section className="glass-studio flex flex-col justify-between rounded-2xl p-5">
              <div className="space-y-4">
                <div className="flex items-center gap-3">
                  <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-ember-500/15 text-ember-300 ring-1 ring-ember-400/30">
                    <BotIcon className="h-4.5 w-4.5" />
                  </div>
                  <div>
                    <h2 className="text-sm font-semibold text-ink-100">Local LLM Engine</h2>
                    <p className="text-xs text-ink-400">
                      Generates titles, summaries, tags, action items &amp; midnight digests
                    </p>
                  </div>
                </div>

                {/* Visual Provider Cards */}
                <div>
                  <label className={labelCls}>Inference Provider</label>
                  <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
                    {[
                      { id: "ollama", title: "Ollama", desc: "127.0.0.1:11434", defaultUrl: "http://127.0.0.1:11434" },
                      { id: "lmstudio", title: "LM Studio", desc: "OpenAI API", defaultUrl: "http://127.0.0.1:1234" },
                      { id: "custom", title: "Custom", desc: "OpenAI-compatible", defaultUrl: s.llm_base_url },
                      { id: "none", title: "Offline Rules", desc: "Deterministic", defaultUrl: "" },
                    ].map((p) => {
                      const active = s.llm_provider === p.id;
                      return (
                        <button
                          key={p.id}
                          onClick={async () => {
                            const newUrl = p.id === "custom" ? s.llm_base_url : p.defaultUrl;
                            patch({ llm_provider: p.id, llm_base_url: newUrl || s.llm_base_url });
                            setLlmTest(null);
                            const changes: Record<string, unknown> = { llm_provider: p.id };
                            if (p.id !== "custom" && p.defaultUrl) {
                              changes.llm_base_url = p.defaultUrl;
                            }
                            await save(changes, `provider: ${p.title}`);
                            // Auto-test connection for active providers
                            if (p.id !== "none") {
                              setLlmTest({ text: "probing endpoint…" });
                              try {
                                const r = await api.testLLM({
                                  provider: p.id,
                                  base_url: changes.llm_base_url as string | undefined ?? s.llm_base_url,
                                });
                                setLlmTest({
                                  ok: r.ok,
                                  text: r.ok
                                    ? `Connected · ${(r.models ?? []).length} chat models`
                                    : r.detail ?? "Unreachable",
                                  models: r.models,
                                });
                              } catch (e) {
                                setLlmTest({
                                  ok: false,
                                  text: e instanceof Error ? e.message : String(e),
                                });
                              }
                            }
                          }}
                          className={`rounded-xl border p-3 text-left transition-all ${
                            active
                              ? "border-ember-400/50 bg-ember-500/15 text-ink-100 shadow-xs"
                              : "border-ink-800 bg-ink-950/65 text-ink-300 hover:border-ink-700"
                          }`}
                        >
                          <p className="text-xs font-semibold">{p.title}</p>
                          <p className="mt-0.5 font-mono text-[10px] text-ink-400">{p.desc}</p>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {s.llm_provider !== "none" && (
                  <>
                    <div>
                      <label className={labelCls}>Endpoint Base URL</label>
                      <input
                        value={s.llm_base_url}
                        onChange={(e) => patch({ llm_base_url: e.target.value })}
                        onBlur={() =>
                          void save({ llm_base_url: s.llm_base_url }, "endpoint URL updated")
                        }
                        className={`${inputCls} font-mono`}
                        spellCheck={false}
                        placeholder={
                          s.llm_provider === "ollama"
                            ? "http://127.0.0.1:11434"
                            : s.llm_provider === "lmstudio"
                              ? "http://127.0.0.1:1234"
                              : "http://your-server:port"
                        }
                      />
                    </div>

                    <div>
                      <label className={labelCls}>Timeout (seconds)</label>
                      <input
                        type="number"
                        value={s.llm_timeout_secs}
                        onChange={(e) => patch({ llm_timeout_secs: Number(e.target.value) })}
                        onBlur={() =>
                          void save({ llm_timeout_secs: s.llm_timeout_secs }, "timeout updated")
                        }
                        className={`${inputCls} w-32 font-mono`}
                      />
                    </div>

                    {(s.llm_provider === "custom" || s.llm_provider === "lmstudio") && (
                      <div>
                        <label className={labelCls}>API Key (optional)</label>
                        <input
                          type="password"
                          value={apiKeyDraft}
                          onChange={(e) => setApiKeyDraft(e.target.value)}
                          onBlur={() => void commitApiKey()}
                          placeholder={
                            s.llm_api_key_set ? "stored — type to replace" : "sk-..."
                          }
                          spellCheck={false}
                          autoComplete="off"
                          className={`${inputCls} font-mono`}
                        />
                        <div className="mt-1 flex items-center gap-3">
                          <p className="text-[10px] text-ink-500">
                            {s.llm_api_key_set
                              ? "A key is stored. Leave blank to keep it."
                              : "Sent as an Authorization: Bearer header."}
                          </p>
                          {s.llm_api_key_set && (
                            <button
                              type="button"
                              onClick={() => void clearApiKey()}
                              className="text-[10px] text-red-300/80 underline hover:text-red-300 cursor-pointer"
                            >
                              clear
                            </button>
                          )}
                        </div>
                      </div>
                    )}
                  </>
                )}
              </div>

              {/* Connection Tester + Dynamic Model Selector */}
              {s.llm_provider !== "none" && (
                <div className="mt-5 border-t border-ink-800/80 pt-4">
                  <div className="flex flex-wrap items-center gap-3">
                    <button
                      onClick={async () => {
                        setLlmTest({ text: "probing endpoint…" });
                        try {
                          // Probe the values in the form, not the saved config:
                          // blur-save and this POST would otherwise race.
                          const r = await api.testLLM({
                            provider: s.llm_provider,
                            base_url: s.llm_base_url,
                            model: s.llm_model,
                            // Probe with the typed key if there is one, else the
                            // stored one, so testing works before saving.
                            ...(apiKeyDraft.trim() ? { api_key: apiKeyDraft.trim() } : {}),
                          });
                          setLlmTest({
                            ok: r.ok,
                            text: r.ok
                              ? `Connected · ${(r.models ?? []).length} chat models available${
                                  r.hidden ? ` · ${r.hidden} embedding-only hidden` : ""
                                }`
                              : r.detail ?? "Unreachable",
                            models: r.models,
                          });
                        } catch (e) {
                          setLlmTest({
                            ok: false,
                            text: e instanceof Error ? e.message : String(e),
                          });
                        }
                      }}
                      className="flex items-center gap-1.5 rounded-xl border border-ember-500/40 bg-ember-500/15 px-3.5 py-2 text-xs font-semibold text-ember-200 transition-colors hover:bg-ember-500/25"
                    >
                      <CpuIcon className="h-3.5 w-3.5" /> Test Connection &amp; Discover Models
                    </button>
                    {llmTest && (
                      <span
                        className={`flex items-center gap-1.5 text-xs font-medium ${
                          llmTest.ok === true
                            ? "text-emerald-300"
                            : llmTest.ok === false
                              ? "text-red-300"
                              : "text-ink-300 animate-pulse"
                        }`}
                      >
                        {llmTest.ok === true && (
                          <span className="inline-block h-2 w-2 rounded-full bg-emerald-400" />
                        )}
                        {llmTest.ok === false && (
                          <span className="inline-block h-2 w-2 rounded-full bg-red-400" />
                        )}
                        {llmTest.text}
                      </span>
                    )}
                  </div>

                  {/* Dynamic Model Selector — shows discovered models as clickable chips */}
                  {llmTest?.models && llmTest.models.length > 0 ? (
                    <div className="mt-3">
                      <p className="micro-label mb-1.5 !text-[9px]">
                        Select a model to use:
                      </p>
                      <div className="flex flex-wrap gap-1.5">
                        {llmTest.models.map((m) => (
                          <button
                            key={m}
                            onClick={() => {
                              patch({ llm_model: m });
                              void save({ llm_model: m }, `selected model: ${m}`);
                            }}
                            className={`rounded-lg border px-2.5 py-1 font-mono text-[11px] transition-colors ${
                              s.llm_model === m
                                ? "border-ember-400 bg-ember-500/25 text-ember-200"
                                : "border-ink-700 bg-ink-950 text-ink-300 hover:border-ember-400/40 hover:text-ink-100"
                            }`}
                          >
                            {m}
                          </button>
                        ))}
                      </div>
                      {s.llm_model && (
                        <p className="mt-2 font-mono text-[11px] text-ink-400">
                          Active: <span className="text-ember-300">{s.llm_model}</span>
                        </p>
                      )}
                    </div>
                  ) : (
                    /* Fallback manual model input — only when no models discovered yet */
                    <div className="mt-3">
                      <label className={labelCls}>Model Identifier</label>
                      <input
                        value={s.llm_model}
                        onChange={(e) => patch({ llm_model: e.target.value })}
                        onBlur={() => void save({ llm_model: s.llm_model }, "LLM model updated")}
                        className={`${inputCls} font-mono`}
                        placeholder="test connection to discover models"
                        spellCheck={false}
                      />
                      <p className="mt-1 text-[10px] text-ink-500">
                        Click &quot;Test Connection&quot; to auto-discover available models
                      </p>
                    </div>
                  )}
                </div>
              )}

              {/* #266 fallback chain — only meaningful with a live provider */}
              {s.llm_provider !== "none" && (
                <div className="mt-4 border-t border-ink-800/80 pt-4">
                  <label className={labelCls} htmlFor="llm-fallback-models">
                    Fallback Models
                  </label>
                  <input
                    id="llm-fallback-models"
                    value={s.llm_fallback_models ?? ""}
                    onChange={(e) => patch({ llm_fallback_models: e.target.value })}
                    onBlur={() =>
                      void save(
                        { llm_fallback_models: s.llm_fallback_models },
                        "fallback models updated",
                      )
                    }
                    className={`${inputCls} font-mono`}
                    placeholder="qwen2.5:3b, llama3.2:1b"
                    spellCheck={false}
                  />
                  <p className="mt-1 text-[10px] text-ink-500">
                    Comma-separated, tried in order when the primary model is unreachable or
                    answers with unusable output. Each step gets an equal share of the timeout.
                    Leave empty to fall back to heuristics on the first failure.
                  </p>
                </div>
              )}

              {/* #257 tag vocabulary — the tags enrichment is held to. */}
              {s.llm_provider !== "none" && (
                <div className="mt-4 border-t border-ink-800/80 pt-4">
                  <label className={labelCls} htmlFor="llm-preferred-tags">
                    Preferred Tags
                  </label>
                  <input
                    id="llm-preferred-tags"
                    value={s.llm_preferred_tags ?? ""}
                    onChange={(e) => patch({ llm_preferred_tags: e.target.value })}
                    onBlur={() =>
                      void save(
                        { llm_preferred_tags: s.llm_preferred_tags },
                        "preferred tags updated",
                      )
                    }
                    className={`${inputCls} font-mono`}
                    placeholder="homelab, work, reading"
                    spellCheck={false}
                  />
                  <p className="mt-1 text-[10px] text-ink-500">
                    Comma-separated. The enricher is told about these and its output is snapped onto
                    them, so a model that answers &quot;homelab-router&quot; when you use
                    &quot;homelab&quot; gets corrected. Unrelated tags are left alone.
                  </p>
                </div>
              )}

              {s.llm_provider === "none" && (
                <div className="mt-5 border-t border-ink-800/80 pt-4">
                  <p className="text-xs text-ink-400">
                    LLM enrichment is disabled. Notes will be processed using deterministic
                    heuristic rules (keyword extraction, pattern matching). Switch to a provider
                    above to enable AI-powered enrichment.
                  </p>
                </div>
              )}
            </section>

            {/* Whisper Speech-to-Text Compartment */}
            <section className="glass-studio flex flex-col justify-between rounded-2xl p-5">
              <div className="space-y-4">
                <div className="flex items-center gap-3">
                  <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-iris-500/15 text-iris-300 ring-1 ring-iris-400/30">
                    <MicIcon className="h-4.5 w-4.5" />
                  </div>
                  <div>
                    <h2 className="text-sm font-semibold text-ink-100">
                      Whisper Speech-to-Text (faster-whisper)
                    </h2>
                    <p className="text-xs text-ink-400">
                      100% offline CPU int8 voice memo & YouTube audio transcription
                    </p>
                  </div>
                </div>

                {/* 4-tier Visual Model Selector */}
                <div>
                  <label className={labelCls}>Whisper Model Size</label>
                  <div className="grid grid-cols-2 gap-2.5">
                    {[
                      { id: "tiny", name: "tiny", size: "~39 MB", desc: "Fastest · quick memos" },
                      {
                        id: "base",
                        name: "base",
                        size: "~75 MB",
                        desc: "Balanced · recommended",
                      },
                      {
                        id: "small",
                        name: "small",
                        size: "~244 MB",
                        desc: "High accuracy · multilingual",
                      },
                      {
                        id: "medium",
                        name: "medium",
                        size: "~769 MB",
                        desc: "Studio grade · slowest",
                      },
                    ].map((tier) => {
                      const active = s.transcribe_model === tier.id;
                      const isWarm =
                        (s.transcribe_loaded && active) ||
                        (wp?.status === "ready" && wp.model === tier.id);
                      const isCached = cachedWhisperSet.has(tier.id);
                      const isTierDownloading =
                        (wp?.status === "downloading" || wp?.status === "loading") &&
                        wp.model === tier.id;

                      return (
                        <button
                          key={tier.id}
                          disabled={isWhisperWorking}
                          onClick={() => {
                            setWhisperTest(null);
                            void save(
                              { transcribe_model: tier.id },
                              `whisper set to '${tier.id}'`,
                            );
                          }}
                          className={`relative overflow-hidden rounded-xl border p-3 text-left transition-all ${
                            active
                              ? "border-iris-400/50 bg-iris-500/15 text-ink-100 shadow-xs"
                              : "border-ink-800 bg-ink-950/65 text-ink-300 hover:border-ink-700"
                          } ${isWhisperWorking ? "cursor-wait opacity-80" : ""}`}
                        >
                          <div className="flex items-center justify-between gap-1.5">
                            <span className="font-mono text-xs font-bold uppercase">
                              {tier.name}
                            </span>
                            <div className="flex items-center gap-1.5">
                              {isWarm ? (
                                <span className="rounded-md border border-emerald-500/30 bg-emerald-500/15 px-1.5 py-0.2 font-mono text-[9.5px] font-semibold text-emerald-300">
                                  in RAM
                                </span>
                              ) : isCached ? (
                                <span className="rounded-md border border-ink-700 bg-ink-850 px-1.5 py-0.2 font-mono text-[9.5px] text-emerald-300/90">
                                  cached
                                </span>
                              ) : (
                                <span className="rounded-md border border-iris-400/25 bg-iris-500/10 px-1.5 py-0.2 font-mono text-[9.5px] text-iris-300/80">
                                  download
                                </span>
                              )}
                              <span className="font-mono text-[10px] text-iris-300">
                                {tier.size}
                              </span>
                            </div>
                          </div>
                          <p className="mt-1 text-[11px] text-ink-400">{tier.desc}</p>
                          {isTierDownloading && (
                            <div className="mt-2 h-1 w-full overflow-hidden rounded-full bg-ink-900">
                              <div
                                className="h-full bg-gradient-to-r from-iris-400 to-ember-400 transition-all duration-150"
                                style={{ width: `${Math.max(5, wp.percent)}%` }}
                              />
                            </div>
                          )}
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div>
                  <label className={labelCls}>Transcription Language</label>
                  <div className="flex gap-1.5">
                    <input
                      value={s.transcribe_language}
                      onChange={(e) => patch({ transcribe_language: e.target.value })}
                      onBlur={() =>
                        void save(
                          { transcribe_language: s.transcribe_language },
                          "language updated",
                        )
                      }
                      className={`${inputCls} font-mono`}
                      placeholder="auto"
                    />
                    {["auto", "en", "hi"].map((lang) => (
                      <button
                        key={lang}
                        onClick={() => {
                          patch({ transcribe_language: lang });
                          void save({ transcribe_language: lang }, `language: ${lang}`);
                        }}
                        className={`shrink-0 rounded-xl border px-3 font-mono text-xs transition-colors ${
                          s.transcribe_language === lang
                            ? "border-iris-400/50 bg-iris-500/20 text-iris-200"
                            : "border-ink-700 bg-ink-900 text-ink-400 hover:text-ink-200"
                        }`}
                      >
                        {lang}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="space-y-2">
                  {(
                    [
                      ["transcribe_translate", "Translate to English (whisper)", "Recordings in other languages are transcribed into English."],
                      ["transcribe_cleanup_audio", "Audio cleanup before transcription", "Normalise loudness with ffmpeg loudnorm before sending to whisper."],
                      ["transcribe_keep_audio", "Keep original audio files", "When off, the raw audio file is deleted once transcription succeeds."],
                      ["transcribe_voice_punctuation", "Voice punctuation commands", "Spoken words like \"comma\" or \"new line\" become symbols in the transcript."],
                      ["transcribe_auto_format", "Auto-capitalisation", "Sentence-case the transcript and capitalise bare \"i\"."],
                      ["transcribe_diarize", "Speaker labels (diarization)", "Label transcript words by speaker with pyannote-audio. Needs pyannote-audio installed and an HF token set."],
                    ] as const
                  ).map(([key, title, sub]) => (
                    <label key={key} className="flex cursor-pointer items-center justify-between gap-3">
                      <div>
                        <div className="text-xs font-medium text-ink-200">{title}</div>
                        <p className="text-[11px] text-ink-500">{sub}</p>
                      </div>
                      <Toggle
                        checked={Boolean(s[key as keyof typeof s])}
                        onChange={(v) => {
                          patch({ [key]: v });
                          void save({ [key]: v }, `${title} ${v ? "on" : "off"}`);
                        }}
                      />
                    </label>
                  ))}
                </div>

                <div>
                  <label className={labelCls}>Hugging Face Token</label>
                  <input
                    type="password"
                    placeholder={s.transcribe_hf_token_set ? "•••••••• (set — type to replace)" : "hf_..."}
                    onBlur={(e) => {
                      if (e.target.value.trim()) void save({ transcribe_hf_token: e.target.value.trim() }, "HF token saved");
                    }}
                    className={inputCls}
                  />
                  <p className="text-[10px] text-ink-500">Used to download gated pyannote models. Never shown again after saving.</p>
                </div>

                <div>
                  <label className={labelCls}>Custom Replacements</label>
                  <input
                    value={s.transcribe_replacements ?? ""}
                    onChange={(e) => patch({ transcribe_replacements: e.target.value })}
                    onBlur={() =>
                      void save(
                        { transcribe_replacements: s.transcribe_replacements },
                        "replacements updated",
                      )
                    }
                    className={`${inputCls} font-mono`}
                    placeholder='Spoken phrase=written form, e.g. my email=me@example.com, my standup=daily sync'
                  />
                </div>

                <div>
                  <label className={labelCls}>Custom Vocabulary</label>
                  <input
                    value={s.transcribe_vocabulary ?? ""}
                    onChange={(e) => patch({ transcribe_vocabulary: e.target.value })}
                    onBlur={() =>
                      void save(
                        { transcribe_vocabulary: s.transcribe_vocabulary },
                        "vocabulary updated",
                      )
                    }
                    className={`${inputCls} font-mono`}
                    placeholder="Names and terms whisper should expect, e.g. Nikhil, FastAPI, Omarchy"
                  />
                </div>
              </div>

              <MicPicker />

              <div className="mt-5 space-y-3 border-t border-ink-800/80 pt-4">
                <div className="flex flex-wrap items-center gap-3">
                  <button
                    disabled={isWhisperWorking}
                    onClick={async () => {
                      setWhisperBusy(true);
                      const needsDownload = !cachedWhisperSet.has(s.transcribe_model);
                      setWhisperTest({
                        text: needsDownload
                          ? `downloading '${s.transcribe_model}' from Hugging Face…`
                          : `loading '${s.transcribe_model}' into CPU int8 memory…`,
                      });
                      try {
                        const r = await api.testWhisper();
                        setWhisperTest({
                          ok: true,
                          text: `✓ '${r.model}' model verified & warm in RAM`,
                        });
                        loadAll();
                      } catch (e) {
                        setWhisperTest({
                          ok: false,
                          text: e instanceof Error ? e.message : String(e),
                        });
                      } finally {
                        setWhisperBusy(false);
                      }
                    }}
                    className={`flex items-center gap-1.5 rounded-xl border px-3.5 py-2 text-xs font-semibold transition-colors ${
                      isWhisperWorking
                        ? "cursor-wait border-iris-400/30 bg-iris-500/10 text-iris-300"
                        : "border-iris-400/40 bg-iris-500/15 text-iris-200 hover:bg-iris-500/25"
                    }`}
                  >
                    <MicIcon className="h-3.5 w-3.5" />
                    {wp?.status === "downloading"
                      ? `Downloading '${wp.model}' (${wp.percent}%)…`
                      : wp?.status === "loading" || whisperBusy
                        ? `Loading '${s.transcribe_model}' into RAM…`
                        : !cachedWhisperSet.has(s.transcribe_model)
                          ? `Download & Warm Up '${s.transcribe_model}'`
                          : "Warm Up & Verify Whisper"}
                  </button>

                  {!isWhisperWorking && whisperTest && (
                    <span
                      className={`text-xs font-medium ${
                        whisperTest.ok === true
                          ? "text-emerald-300"
                          : whisperTest.ok === false
                            ? "text-red-300"
                            : "text-ink-300"
                      }`}
                    >
                      {whisperTest.text}
                    </span>
                  )}
                </div>

                {/* Live Download & Warm-Up Progress Bar */}
                {(isWhisperWorking ||
                  wp?.status === "downloading" ||
                  wp?.status === "loading" ||
                  (wp?.status === "ready" && wp.model === s.transcribe_model)) && (
                  <div className="rounded-xl border border-ink-800 bg-ink-950/80 p-3">
                    <div className="mb-1.5 flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span
                          className={`h-2 w-2 rounded-full ${
                            wp?.status === "downloading"
                              ? "animate-ping bg-iris-400"
                              : wp?.status === "loading" || whisperBusy
                                ? "animate-pulse bg-ember-400"
                                : "bg-emerald-400"
                          }`}
                        />
                        <span className="font-mono text-[10.5px] font-semibold tracking-wider text-ink-200 uppercase">
                          {wp?.status === "downloading"
                            ? `Downloading '${wp.model}' weights`
                            : wp?.status === "loading" || whisperBusy
                              ? `Warming '${s.transcribe_model}' in CPU int8 RAM`
                              : `Model '${wp?.model ?? s.transcribe_model}' ready`}
                        </span>
                      </div>

                      <div className="flex items-center gap-2 font-mono text-[11px]">
                        {wp && wp.total_bytes > 0 && wp.status === "downloading" && (
                          <span className="text-ink-400">
                            {fmtMB(wp.downloaded_bytes)} / {fmtMB(wp.total_bytes)}
                          </span>
                        )}
                        {wp && wp.speed_bps > 0 && wp.status === "downloading" && (
                          <span className="text-iris-300">
                            {(wp.speed_bps / (1024 * 1024)).toFixed(1)} MB/s
                          </span>
                        )}
                        <span
                          className={`font-bold ${
                            wp?.status === "ready" ? "text-emerald-300" : "text-ink-100"
                          }`}
                        >
                          {wp?.percent ?? (whisperBusy ? 10 : 100)}%
                        </span>
                      </div>
                    </div>

                    <div className="h-2 w-full overflow-hidden rounded-full bg-ink-900 ring-1 ring-ink-800">
                      <div
                        className={`h-full rounded-full transition-all duration-200 ${
                          wp?.status === "ready"
                            ? "bg-emerald-400"
                            : "bg-gradient-to-r from-iris-500 via-ember-400 to-emerald-400"
                        }`}
                        style={{
                          width: `${Math.max(
                            4,
                            wp?.percent ?? (whisperBusy ? 15 : 100),
                          )}%`,
                        }}
                      />
                    </div>

                    <p className="mt-1.5 truncate font-mono text-[10.5px] text-ink-400">
                      {wp?.detail ||
                        whisperTest?.text ||
                        `Preparing faster-whisper '${s.transcribe_model}'…`}
                    </p>
                  </div>
                )}
              </div>
            </section>
          </div>

          {/* Local Enrichment Pipeline Architecture Overview */}
          <div className="glass-studio rounded-2xl p-4">
            <div className="mb-3 flex items-center justify-between">
              <span className="micro-label flex items-center gap-1.5">
                <SparkIcon className="h-3 w-3 text-ember-400" />
                Zero-Cloud Enrichment Pipeline
              </span>
              <span className="font-mono text-[10.5px] text-ink-400">
                100% On-Device Processing
              </span>
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <div className="rounded-xl border border-ink-800/80 bg-ink-950/60 p-3">
                <p className="text-xs font-semibold text-ink-100">1. Capture & Ingest</p>
                <p className="mt-1 text-[11.5px] leading-relaxed text-ink-300">
                  Text notes, microphone voice memos, and YouTube URLs are saved immediately to
                  SQLite WAL and queued for background enrichment.
                </p>
              </div>
              <div className="rounded-xl border border-ink-800/80 bg-ink-950/60 p-3">
                <p className="text-xs font-semibold text-ink-100">
                  2. Transcribe & Synthesize
                </p>
                <p className="mt-1 text-[11.5px] leading-relaxed text-ink-300">
                  Audio & captionless videos run through CTranslate2{" "}
                  <code className="font-mono text-iris-300">faster-whisper</code>, then your
                  local LLM extracts titles, tags, and action items.
                </p>
              </div>
              <div className="rounded-xl border border-ink-800/80 bg-ink-950/60 p-3">
                <p className="text-xs font-semibold text-ink-100">3. Index & Vault Mirror</p>
                <p className="mt-1 text-[11.5px] leading-relaxed text-ink-300">
                  Enriched notes are indexed in SQLite FTS5 (BM25 ranking) and mirrored as clean
                  Markdown files into your Obsidian vault.
                </p>
              </div>
            </div>
          </div>
        </div>
  );
}
