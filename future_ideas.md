# Ideas

> All 500 ideas below are cut into shippable releases in
> [`docs/versions/`](docs/versions/README.md) — one file per version, with the
> data model each one needs. Read that instead of this list when you want to
> build something.

# Part 1: Ideas 1-100

## Capture & HUD (1-12)
1. Capture templates in the HUD (idea, bug, quote, shopping, meeting) that preset tags and the LLM prompt.
2. A "hold to talk" mode as well as toggle.
3. Clipboard capture hotkey that saves selected or copied text with the source window title.
4. Screenshot capture with OCR, stored as a note with the image attached.
5. Per-capture destination: Inbox, straight to Tasks, or a specific project.
6. Undo toast after any capture ("Saved, undo for 5s").
7. Draft recovery if the HUD is dismissed mid-dictation.
8. Live partial transcription in the HUD while recording.
9. Voice commands inside dictation ("new line", "tag work", "make this a task").
10. Capture-by-email-to-self via a local IMAP poll.
11. Share-target endpoint so a phone on the LAN can POST captures (with a pairing token).
12. Browser extension for selected text, page URL and highlight capture.

## Inbox & notes (13-26)
13. Pin notes to the top of the Inbox.
14. Archive and snooze (hide until a date or "next Monday").
15. Bulk select with merge, tag, archive and delete.
16. Merge-duplicates suggestion when two notes embed very close together.
17. A "split note" action for long brain dumps.
18. Inline editing in the card, without opening the drawer.
19. Note version history (raw capture vs. cleaned) with revert.
20. "Regenerate title/summary/tags" button with a model picker.
21. Diff view between raw transcript and cleaned text.
22. Backlinks and `[[wikilinks]]` matching the Obsidian vault.
23. Auto-suggested related notes in the drawer, using the existing embeddings.
24. Attachments: drag a file or image onto a note.
25. Note colours or icons by type (voice, text, YouTube, screenshot).
26. A sensitive-note flag that excludes the note from the vault mirror, the LLM and logs.

## Tasks (27-40)
27. Due dates and reminders parsed from text ("by Friday"), with desktop notifications.
28. Recurring tasks.
29. Subtasks and drag to reorder.
30. A "Today" view of overdue, due today and what you actually worked on.
31. Task priority inferred by the LLM, with manual override.
32. Estimated time per task and total load for the day.
33. A "next action" suggestion based on current time and recent activity.
34. Link a task to the window or app where you could do it.
35. Auto-complete suggestions when the Timeline shows matching file or commit work.
36. Kanban layout alongside the checklist.
37. Keyboard-only triage mode (j/k, x, s, e).
38. A weekly task review ritual with a "carry over or drop" screen.
39. Completion streaks and a completion heatmap.
40. Export tasks to todo.txt or a Markdown checklist in the vault.

## Search & recall (41-52)
41. Search filters (type, tag, date range, has-audio) as chips.
42. Saved searches that behave like smart folders.
43. Global command palette (Ctrl+K) for search, navigation and actions.
44. "Ask Fleeting" answers with clickable source notes and passage highlights.
45. Time-scoped questions ("what did I decide about the router last week?").
46. A "random old note" resurfacing card, spaced-repetition style.
47. A "this day last month/year" view.
48. Search across the Timeline (window titles, commits) in the same results.
49. Recent-search history and autocomplete from tags.
50. Tag cloud and tag manager with rename and merge.
51. Topic clustering view grouping notes by embedding similarity.
52. A simple knowledge-graph visualisation of notes, tags and links.

## Timeline & activity (53-66)
53. Project auto-detection from window titles, git repos and file paths, with time per project.
54. Manual session editing: split, merge, relabel, delete.
55. Categories (focus / communication / entertainment) with custom rules.
56. Goals such as "max 1h on social" with a gentle nudge.
57. Daily focus score, shown as a trend.
58. Context-switch counter.
59. Calendar heatmap of active hours.
60. Real Wayland idle detection (`ext-idle-notify`) instead of the cursor heuristic.
61. Optional meeting detection (mic or camera in use).
62. Compare today with your 7-day average in the time-split bar.
63. Drag a time range on the Timeline to ask the LLM "what was I doing here?"
64. Per-app rename and merge (Firefox and firefox collapse into one).
65. Private mode that pauses tracking for N minutes, from the tray menu.
66. Redaction rules that strip patterns like tokens or emails from stored window titles.

## Reports & digests (67-74)
67. Choose the report time or window (workday, not strictly midnight).
68. Report tone presets (terse, narrative, standup-style).
69. A standup generator: yesterday, today, blockers.
70. Monthly and yearly reviews built from the weekly logs.
71. Side-by-side comparison of reports across days.
72. Editable reports, with edits kept when you regenerate.
73. Report sections linked to the underlying sessions and notes.
74. Export a report as PDF or Markdown.

## UI polish (75-86)
75. Light theme and auto theme following the system, with accent colour options.
76. Density toggle (compact / comfortable).
77. Skeleton loaders and optimistic updates.
78. Empty states with a useful next action.
79. Drag-and-drop of audio files, text and URLs onto the capture bar.
80. Resizable, collapsible drawer with a split view for note plus related notes.
81. Respect `prefers-reduced-motion` across the animations.
82. A global keyboard-shortcut cheat sheet (`?` overlay).
83. Sidebar badge showing processing and failed captures.
84. Toasts with an action ("View note", "Undo") and a stacking limit.
85. Configurable HUD position (corner, centre, follow cursor's monitor).
86. Text size and font settings for the long-form reader.

## Voice & transcription (87-91)
87. Speaker labels for meeting recordings (diarization).
88. Word-level timestamps with click-to-seek playback.
89. Custom vocabulary or names list passed to whisper as an initial prompt.
90. Auto language detection per memo, with translation to your main language.
91. Audio cleanup before transcription, and a configurable audio retention policy.

## AI & LLM (92-96)
92. A model per task in Settings (small for tags, larger for reports and assistant).
93. Prompt editor for enrichment and reports, with reset to default.
94. LLM and embeddings health panel: latency, queue depth, last error, one-click retry.
95. A "reprocess everything" job after you change the model or embedding dimension, with progress.
96. Confidence flags on LLM-extracted action items, so you confirm rather than clean up.

## Platform, data & reliability (97-100)
97. Encrypted backup and restore: one-click export of DB, audio and vault, plus scheduled snapshots.
98. Portable mode and a Windows/macOS fallback for the activity tracker.
99. Optional encryption at rest for the SQLite file, with the key in the system keyring (and the `api_key` moved out of plaintext TOML).
100. A first-run onboarding wizard that checks Ollama, ffmpeg, yt-dlp and hyprctl, picks a model, and imports an existing Obsidian vault.

# Part 2: Ideas 101-200

## Assistant & actions (101-112)
101. Multi-turn assistant memory with a "pinned context" panel showing which notes the answer drew on.
102. Slash commands in the assistant (`/task`, `/summarize today`, `/find`, `/log`).
103. Confirm-before-act preview for every assistant action, with undo.
104. Voice-in, voice-out assistant using local TTS (Piper).
105. Saved prompts or "recipes" you can rerun.
106. Scheduled assistant jobs ("every Friday 5pm, draft my week summary").
107. Streaming responses with a stop button and regenerate-with-different-model.
108. Assistant suggestions inside the note drawer.
109. Natural-language bulk edits ("retag all my router notes as homelab"), with a dry run.
110. A nightly "what did I forget?" nudge for open loops.
111. Assistant conversation history search and pinning.
112. Tool-use transparency: a collapsible trace of which queries and notes the assistant touched.

## Vault & Obsidian sync (113-122)
113. Conflict-resolution UI when a vault file and the DB version diverge (three-way merge).
114. Frontmatter schema editor.
115. Folder mapping rules (tag to subfolder, type to subfolder).
116. Logseq-style outline export as an alternative format.
117. Daily-note integration, appending captures to today's `Daily/YYYY-MM-DD.md`.
118. A "vault health" report: orphans, broken links, missing frontmatter.
119. Import an existing Markdown folder and run it through enrichment and embeddings.
120. Attachment sync into an `attachments/` folder in the vault.
121. Optional Git backing for the vault, with auto-commit after sync.
122. Dry-run mode for vault sync.

## Integrations (123-134)
123. Local calendar import (ICS or CalDAV) shown on the Timeline.
124. Deeper git integration: per-repo activity charts and PR/branch context.
125. Opt-in browser history reader for page titles.
126. Shell hook for terminal command history awareness.
127. Home Assistant or MQTT bridge so a smart button triggers a capture.
128. A Telegram or Matrix bot for capturing from your phone.
129. RSS/Atom feed ingestion with LLM summaries.
130. A "read later" queue for URLs, with article extraction.
131. PDF ingestion with text extraction, OCR fallback and a summary note.
132. Podcast and audio-file import with chaptered summaries.
133. Token-protected webhook endpoint for local automations.
134. Obsidian URI handler so notes open in Obsidian from a button.

## Privacy & security (135-144)
135. App lock with a passphrase or system auth.
136. A one-click "forget the last N minutes/hours" panic button.
137. Data inventory page showing what is stored per category and its size.
138. Per-source retention policies.
139. API-key storage in the OS keyring instead of plaintext TOML.
140. Audit log of settings changes and destructive actions.
141. A network-egress self-check page.
142. Auth token for the local API even on loopback.
143. A redacted export mode that strips names, emails and numbers.
144. Signed releases and checksum verification for the Electron build.

## Desktop shell (145-156)
145. Tray menu quick actions (capture, pause tracking, open today's report, quit).
146. A mini "now" widget window showing current task and elapsed time.
147. Multi-monitor awareness for the HUD.
148. Autostart and "start minimised to tray" toggles.
149. Native notifications with action buttons ("Mark done", "Snooze 1h").
150. Deep links (`fleeting://note/123`, `fleeting://capture?text=...`).
151. Drag a note out of the app to produce a Markdown file elsewhere.
152. Configurable global-shortcut editor with conflict detection against Hyprland binds.
153. Opt-in auto-update checks against GitHub releases.
154. Crash and log viewer in Settings.
155. Hyprland rules snippet generator in Settings.
156. Packaging as AppImage and an AUR PKGBUILD.

## CLI (157-162)
157. `flee search "query"` and `flee tasks`.
158. `flee today` to print the day's report or time split.
159. `flee done 12` and `flee snooze 12 2h`.
160. Shell completions (bash/zsh/fish).
161. `flee --audio file.wav` to transcribe and file an existing recording.
162. A TUI mode (Textual).

## Insights & analytics (163-172)
163. Capture frequency stats: notes per day, top tags over time.
164. Optional one-tap mood and energy check-in, correlated with focus time.
165. Break reminders after N hours without a gap.
166. A weekly "what shipped" view combining commits, tasks and notes.
167. Per-project dashboards.
168. Trend lines for recurring tags.
169. A persistent "unfinished threads" list from reports.
170. Time-estimate accuracy: predicted vs. actual time on tasks.
171. A quarterly review generator.
172. An annual "Wrapped"-style summary, entirely local.

## Accessibility & i18n (173-180)
173. Full keyboard-navigation audit with visible focus rings.
174. Screen-reader announcements for SSE-driven updates.
175. High-contrast and colour-blind-safe chart palettes.
176. Scalable UI zoom, persisted per window, HUD included.
177. UI translations, starting with Hindi and Spanish.
178. Locale-aware dates, times and first day of the week.
179. Right-to-left layout support.
180. Dictation language switcher in the HUD.

## Performance & reliability (181-188)
181. Virtualised lists in Inbox, Tasks and Timeline.
182. Incremental embedding with batching, backoff and a visible queue.
183. DB maintenance tool in Settings (VACUUM, FTS rebuild, integrity check).
184. Background task priorities so interactive captures preempt reports and re-embeds.
185. Graceful startup screen with clear errors if the port is taken.
186. Lazy-load heavy views and code-split the bundle.
187. SSE reconnect with backoff and missed-event catch-up after sleep.
188. Auto-backup of the DB before every schema migration.

## Developer experience & project health (189-196)
189. Seed-data and demo-mode command.
190. Playwright end-to-end tests for the Electron app and HUD.
191. A CI workflow running pytest, vitest, type-check and lint.
192. Typed API client generated from the FastAPI OpenAPI schema.
193. Pre-commit hooks (ruff, eslint, tsc).
194. An architecture overview doc with a capture-pipeline sequence diagram.
195. Feature flags in config for experimental modules.
196. A plugin or hook system for custom processors.

## Delight & wellbeing (197-200)
197. A calm end-of-day "shutdown ritual" screen.
198. A distraction-free focus mode.
199. Optional subtle sound feedback for capture start, stop and save.
200. Shareable, anonymised summary cards of your day, generated locally.

# Part 3: Ideas 201-300

## Editor & note content (201-210)
201. Markdown editor mode in the drawer with live preview and toolbar.
202. Slash-menu block insertion (`/todo`, `/quote`, `/divider`, `/date`).
203. Syntax-highlighted code blocks with copy button and language auto-detect.
204. Inline task syntax: typing `- [ ]` in a note creates a real linked task, synced both ways.
205. Quote capture with attribution fields.
206. Collapsible sections and an auto-generated outline sidebar.
207. Table editor that also renders pasted CSV or TSV.
208. Math and diagram support (KaTeX, Mermaid).
209. Text-expansion snippets (`;sig`, `;standup`).
210. A "reading mode" with comfortable width, progress bar and reading time.

## YouTube & media (211-218)
211. Chapter detection with per-chapter summaries and timestamp links.
212. Playlist import with progress and per-video skip.
213. A "key takeaways and quotes" mode for videos.
214. Overnight watch-later queue that processes when the machine is idle.
215. Embedded local audio/video player with transcript-synced highlighting.
216. Other yt-dlp sources (podcasts, Vimeo, talks) with source badges.
217. Thumbnail and channel metadata on the note card.
218. A "study mode" that generates flashcards or quiz questions from a transcript.

## Cross-device & sync (219-228)
219. Optional encrypted peer-to-peer sync between your own machines.
220. A read-only LAN web view with a pairing code.
221. Conflict-free merging of note edits across devices.
222. Sync status indicator in the sidebar.
223. Selective sync by tag or project.
224. Sync over a user-supplied folder (Dropbox, NAS, Nextcloud).
225. Device names and per-device activity breakdown in reports.
226. A "continue on phone" QR code.
227. A self-hosted remote capture inbox the desktop drains.
228. Sync dry-run and a "restore this device from another" wizard.

## Mobile & PWA (229-234)
229. Installable PWA manifest and service worker for the LAN view.
230. Share-sheet integration that creates a capture.
231. Mobile-first capture screen with a big record button.
232. Offline queue for captures made without a connection.
233. Home-screen shortcuts ("Voice note", "Quick thought", "Today's tasks").
234. A widget-friendly JSON endpoint for tasks and the report.

## Onboarding & settings UX (235-244)
235. Settings search with jump-to highlight.
236. Inline validation and "test connection" buttons for LLM, embeddings and vault path.
237. "What does this do" popovers with recommended values.
238. Switchable settings profiles (Work, Personal, Low-power).
239. A diff view when `config.toml` is edited outside the app.
240. Settings import and export as a single file.
241. Hardware-aware recommendation for whisper and LLM model sizes.
242. "Restore defaults" per section.
243. An interactive tour showing real keyboard shortcuts.
244. A "what's new" panel after each update.

## Charts & visualisation (245-254)
245. Hover and click-through on charts that jumps to the underlying data.
246. App-to-app switching Sankey or flow chart.
247. A 24-hour radial "day clock".
248. Weekly small-multiples comparing all seven days.
249. Tag co-occurrence matrix and topic-over-time stream chart.
250. A task funnel (captured, planned, started, completed).
251. A project time treemap.
252. Calendar-style heatmap for note creation and task completion.
253. Chart export as PNG or SVG.
254. Sparklines on every list header.

## AI quality & enrichment (255-266)
255. A feedback thumb on each enrichment that feeds a per-user preference prompt.
256. Few-shot examples taken from your corrected titles and tags.
257. Tag vocabulary control with a preferred list and "propose new" as the exception.
258. Entity extraction (people, places, projects, dates) with a clickable index.
259. Local-only sentiment and urgency flags for sorting.
260. A "clarifying question" step for vague captures.
261. Grammar and punctuation cleanup for dictated text, with "keep my wording" toggle.
262. Per-language enrichment prompts with auto language detection.
263. Hallucination guard: cite the sentence or timestamp each summary claim came from.
264. A local benchmark page scoring your models on your own past notes.
265. A button that exports your corrected enrichments as a JSONL dataset for QLoRA training.
266. LLM fallback chains with per-step timeouts, ending in the heuristic pass.

## Projects, collections & organisation (267-276)
267. First-class projects with description, status and an auto-assembled timeline.
268. Manual collections, like playlists.
269. Smart collections defined by a saved query.
270. Nested tags (`work/client-a/billing`) with tree navigation.
271. A "triage inbox" mode where each note must be filed before the next appears.
272. Auto-filing rules.
273. Starred notes with a dedicated view.
274. A trash with restore and automatic purge after N days.
275. "See also" related-notes strips at the bottom of every note.
276. Project-level daily summaries.

## Task evolution (277-284)
277. Task dependencies ("blocked by").
278. Natural-language quick-add ("call dentist tomorrow 3pm #health").
279. Time-blocking by dragging tasks onto a day timeline next to calendar events.
280. Pomodoro or focus timer per task, logging real minutes.
281. Waiting-for status with a follow-up date.
282. A someday/maybe list kept out of the daily view.
283. Context tags (@home, @computer, @errands) with filter chips.
284. A weekly planner distributing tasks across days using your average capacity.

## Notifications & habits (285-290)
285. Quiet hours and a do-not-disturb mode that follows fullscreen apps or a special workspace.
286. A daily capture streak with gentle reminders.
287. A morning briefing notification.
288. An evening wrap-up prompt.
289. Simple habit tracking shown on the Timeline.
290. A notification centre listing everything that fired.

## Data portability & interop (291-295)
291. Full export to JSON, Markdown bundle and CSV, with a schema document.
292. Import from Apple Notes, Google Keep, Notion and Evernote exports.
293. A documented open API with an optional token.
294. An MCP server so other local AI clients can search your notes and tasks (read-only by default).
295. SQLite schema versioning notes and a read-only query console.

## Experimental & fun (296-300)
296. A "memory palace" 3D view of notes clustered by embedding position.
297. A weekly "time capsule" that resurfaces a note from a year ago or a random past note.
298. An "interview me" mode that turns rough ideas into structured notes.
299. A daily "focus theme" auto-suggested from open tasks.
300. Optional, subtle achievement badges for milestones.

# Part 4: Ideas 301-400

## Micro-interactions & quick wins (301-312)
301. `Esc` closes the drawer, clears search and blurs the capture bar, in that order.
302. Auto-focus the capture bar when the window regains focus (toggleable).
303. Relative timestamps that expand to exact time on hover.
304. Copy buttons on every note field.
305. Double-click a tag chip to filter, Alt-click to exclude.
306. A "paste as note" shortcut (`Ctrl+Shift+V`).
307. Remember scroll position and open note per view.
308. A subtle fading highlight on new notes.
309. Character and word counters in the capture bar.
310. Smart paste for URLs ("save as link note" or "fetch page text").
311. Tooltips showing the keyboard shortcut on every icon button.
312. Window title reflecting current view and processing counts.

## Search internals (313-322)
313. Boolean and field operators (`tag:work`, `-draft`, `before:2026-09-01`, `type:voice`).
314. "Did you mean" typo suggestions using the n-gram vectorizer.
315. Hybrid search weighting sliders (keyword vs. semantic).
316. Result grouping by day, tag or project.
317. A search-as-you-type preview pane.
318. Exact-phrase and proximity search.
319. Transcript search with audio timestamps that jump the player.
320. A "find similar" action on any note or text selection.
321. "Not relevant" feedback that lowers a note's rank for that query.
322. A query log with a "most searched" list.

## Capture pipeline (323-332)
323. A visible pipeline stepper (queued, transcribing, enriching, syncing) with timings.
324. Per-stage retry buttons.
325. Priority lanes so text captures skip ahead of long video transcriptions.
326. Cancel and pause for any in-flight job.
327. Duplicate capture detection.
328. A dead-letter list for repeatedly failing captures, with raw-input export.
329. Chunked transcription for long audio with progress and partial results.
330. Voice activity detection to trim silence before transcribing.
331. Optional filler-word removal in dictation.
332. Idempotent capture IDs so CLI or client retries never create duplicates.

## Timeline depth (333-342)
333. Window-title breadcrumb inside each session.
334. Annotate a session with a note that flows into reports.
335. Auto-group sessions into "work blocks".
336. Show git branch and repo next to terminal and editor sessions.
337. A gap-filler prompt ("You were away 2h, what happened?") with one-tap options.
338. Record which Hyprland workspace each session ran on.
339. Overlay tasks completed and notes captured on the timeline.
340. Per-app idle thresholds (video players shouldn't count as idle).
341. A rewind scrubber that replays your day.
342. Export sessions as CSV or a timesheet with project mapping.

## Reports & reflection (343-350)
343. Report length slider.
344. A "highlights only" mode with the top five accomplishments.
345. A "questions for tomorrow" section from loose ends.
346. A weekly diff of focus versus last week, in plain English.
347. A reflection journaling prompt after the report, saved as a linked note.
348. Custom report sections with their own prompts.
349. A "report playground" to test prompt changes against yesterday's data.
350. Evidence mode: expand any report sentence to its source sessions.

## Sharing & presentation (351-358)
351. Export a note, collection or report as a self-contained HTML page.
352. A print stylesheet for PDFs.
353. A "share safely" preview highlighting sensitive content.
354. A static site generator for publishing selected notes.
355. Copy-as-rich-text and copy-as-Markdown buttons.
356. A shareable summary image of the Timeline day bar.
357. Email-ready weekly digest formatting (copy only, no sending).
358. A project "handoff" document compiling notes, open tasks and decisions.

## Visual design & theming (359-368)
359. A theme editor with live preview and import/export.
360. Accent colour extracted from your wallpaper.
361. Follow the Omarchy theme file so Fleeting restyles with the desktop.
362. Optional glassmorphism surface style, off by default.
363. A variable-font typography scale with a mono option for transcripts.
364. An iconography consistency pass across the icon set.
365. Animated micro-illustrations for empty and success states.
366. A compact icon-only sidebar rail mode.
367. Per-view accent colours.
368. A focus-ring and selection style pass checked for contrast.

## Learning & knowledge work (369-378)
369. Spaced-repetition cards from selected notes with a daily queue.
370. A highlight-and-annotate layer on transcripts and articles.
371. An auto-built concept glossary.
372. Reading-progress tracking for long notes and videos.
373. A Zettelkasten view with "next link" prompts.
374. A "teach me" quiz mode on a tag or project.
375. Citation capture with bibliography export.
376. A question bank tracked until answered.
377. Learning goals with milestones.
378. A weekly "what did I learn" extraction.

## System & hardware (379-388)
379. Pause heavy jobs when the machine is busy or on battery.
380. A battery-saver profile with a longer poll interval.
381. Detect when Ollama isn't running and offer to start it.
382. Unload the model after N idle minutes to free VRAM.
383. A disk-usage monitor with a "free up space" wizard.
384. Microphone selection and a test-level meter.
385. Push-to-talk on a hardware key or foot pedal via evdev.
386. A systemd timer option for the nightly report.
387. Wake-from-sleep catch-up for missed scheduled jobs.
388. A thermal or fan-noise guard that throttles transcription.

## Testing, observability & ops (389-396)
389. Structured JSON logging with a log-level toggle.
390. A lightweight local metrics page (jobs per hour, median enrichment time, error rate).
391. Property-based tests for the markdown parser and vault round-trip.
392. Snapshot tests for LLM prompts.
393. A fixture library of audio, videos and edge-case notes.
394. Visual regression tests for key screens and the HUD.
395. A "diagnostics bundle" button (logs, redacted config, version).
396. A dev-mode chaos switch that randomly fails LLM or whisper calls.

## Community & project growth (397-400)
397. Demo GIFs and a short screencast in the README.
398. A public roadmap file derived from `docs/superpowers/plans`.
399. A contributor guide and `good first issue` labels.
400. A starter pack of example prompts and themes, installable in one click.

# Part 5: Ideas 401-500

## Smart suggestions & proactivity (401-410)
401. A "suggested captures" tray for things you probably meant to save.
402. Proactive task extraction from the Timeline.
403. A resume-where-I-left-off card on launch.
404. Related-note nudges while typing in the capture bar.
405. Stale-note prompts after 90 days.
406. Smart default tags based on the app you captured from.
407. Meeting-prep cards that gather relevant notes before a calendar event.
408. Auto-attach the active window title and URL to each capture.
409. A weekly "ideas that went nowhere" digest.
410. Smart reminders that fire when you open a relevant app.

## People & entities (411-418)
411. A lightweight people index built from names in notes.
412. A "last mentioned" date per person.
413. Per-person pages collecting notes, tasks and meeting snippets.
414. Company and project entity pages with alias merging.
415. A local birthday and anniversary reminder list.
416. An opt-in "who haven't I talked to in a while" list.
417. Name disambiguation when two people share a first name.
418. Entity-aware search ("everything about Priya in August").

## Review & maintenance workflows (419-426)
419. A daily inbox-zero ritual with a progress ring.
420. A swipe-style review mode (keep, archive, task, tag).
421. A monthly cleanup assistant proposing merges, renames and archives.
422. Orphan detection for single-use tags, unlinked tasks and untagged notes.
423. A backlog burndown chart for unprocessed items.
424. A review queue for low-confidence enrichments.
425. A tag audit view for rare, overlapping and misspelt tags.
426. Customisable weekly-review reminders.

## Dictation & text input (427-436)
427. HUD output modes: raw, cleaned, bullets, email, message, code comment.
428. Per-app dictation profiles.
429. A voice-punctuation commands toggle.
430. An undo-last-dictation shortcut that deletes what was typed.
431. A dictation history panel with re-insert and re-transcribe.
432. Custom replacements ("my email" expands to your address).
433. Opt-in local wake-word capture.
434. Auto-capitalisation and number-formatting rules.
435. A correction loop that adds fixed words to the vocabulary list.
436. A preview-before-type step for dictation into other apps.

## Calendar & scheduling (437-444)
437. A day planner combining tasks, events and focus blocks.
438. A free-slot finder for scheduling tasks.
439. ICS export of time-blocked tasks.
440. A post-meeting prompt to log decisions and actions.
441. Travel and deadline countdowns on the Inbox.
442. A weekly capacity gauge (planned time vs. available hours).
443. Time-zone aware dates.
444. Holiday import so due dates and streaks don't break.

## Writing & drafting tools (445-452)
445. "Draft from notes": select several notes and generate an outline or first draft.
446. A rewrite menu on selected text (shorter, clearer, friendlier, more formal).
447. Three alternative title suggestions.
448. A blog or newsletter assembler from a tagged collection.
449. A "turn into email" action.
450. In-place note translation with the original side by side.
451. A style-guide setting applied across rewrites.
452. Autocomplete from your own phrases and past notes.

## Safety nets & trust (453-460)
453. A "what will the LLM see?" preview of the exact context for any call.
454. An allow-list of directories for file-activity scanning, with live preview.
455. A confirm dialog with counts and samples before bulk destructive actions.
456. Soft-delete everywhere with a recoverable window.
457. A tamper-evident backup index using hashes.
458. A read-only demo mode that hides sensitive text.
459. Per-source "never use for AI" switches.
460. A clear status for fully offline vs. any network feature in use.

## Hyprland & Linux integration (461-470)
461. A Waybar module showing tracking status, current task and elapsed time.
462. IPC so Hyprland keybinds can call `flee` actions with arguments.
463. An xdg-desktop-portal global shortcuts path.
464. A `wl-clipboard` watcher for clipboard history, excluding password managers.
465. Proper `libnotify`/`mako`/`dunst` notifications with app name, icon and grouping.
466. A GNOME/KDE DBus activity backend.
467. Niri and River compositor adapters.
468. `.desktop` action list entries ("New capture", "Today's report").
469. Cursor-monitor aware HUD placement via compositor IPC.
470. A rofi/wofi script mode that searches notes and opens or inserts the result.

## Metadata & structure (471-478)
471. Typed custom fields on notes (rating, status, URL, due, cost).
472. Note-type templates with their own fields and enrichment prompts.
473. A filterable source/provenance field.
474. A review state per note (raw, enriched, reviewed, final).
475. A context snapshot saving the active project and branch at capture.
476. An auto-generated one-line tl;dr for list views.
477. A reading-time and word-count badge on each card.
478. Live pointers from derived notes back to their source video, file or page.

## Performance & scale (479-486)
479. Load testing with 100k notes and a published benchmark.
480. Cursor-based pagination everywhere with scroll anchoring.
481. FTS tuning (prefix indexes, tokenizer options) in advanced settings.
482. Pre-warm whisper and LLM models at startup with a status indicator.
483. An embedding cache keyed by content hash.
484. An ANN index (HNSW/sqlite-vec) past a vector-count threshold.
485. Streamed SSE payload diffs instead of full-object resends.
486. Image and audio thumbnail/waveform caching.

## UX for edge cases (487-494)
487. Actionable error messages with "copy details" and "fix it" buttons.
488. A first-run empty-vault state offering deletable sample notes.
489. A graceful read-only banner when the DB is locked by another process.
490. Long-operation indicators (re-embedding, backfill) with estimates and cancel.
491. Window-state restoration across monitor and resolution changes.
492. Chunked enrichment and a warning for extremely long pastes.
493. Offline-first UI states with timeouts and retry instead of endless spinners.
494. A "something looks wrong" self-heal tool checking FTS sync, orphaned rows and embeddings.

## Ecosystem & extensibility (495-500)
495. An offline-friendly theme and prompt marketplace format.
496. User-defined actions (a shell command triggered on note events).
497. A Python hooks API in `~/.config/fleeting/hooks/` with documented events.
498. An embeddable widget for showing today's tasks in a personal dashboard.
499. A documented plugin manifest for new capture sources, enrichers and views.
500. A "Fleeting for teams" read-only export of anonymised time and task stats.