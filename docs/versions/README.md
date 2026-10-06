# Version bundles

`future_ideas.md` holds 500 raw ideas. These files re-cut them into **shippable
releases**: one file = one version = one coherent theme that can land in a single
branch and a single release.

Idea numbers (`#123`) refer to `future_ideas.md`. Keep them — they are the shared
vocabulary between the ideas list, the bundles and any plan/spec written later.

| Version | Theme | Ideas |
| --- | --- | --- |
| [0.3](0.3-capture-and-dictation.md) | Capture & dictation ergonomics | 1-12, 87-91, 427-436 |
| [0.4](0.4-notes-and-inbox.md) | Notes, Inbox & organisation | 13-26, 267-276, 471-478 |
| [0.5](0.5-tasks-and-planning.md) | Tasks & day planning | 27-40, 277-284, 437-444 |
| [0.6](0.6-search-and-recall.md) | Search & recall | 41-52, 313-322 |
| [0.7](0.7-timeline-and-activity.md) | Timeline & activity depth | 53-66, 333-342 |
| [0.8](0.8-reports-insights-charts.md) | Reports, insights & charts | 67-74, 163-172, 245-254, 343-350 |
| [0.9](0.9-assistant-and-ai-quality.md) | Assistant & AI quality | 92-96, 101-112, 255-266, 445-452 |
| [0.10](0.10-vault-integrations-sharing.md) | Vault, integrations & sharing | 113-134, 351-358 |
| [0.11](0.11-privacy-security-portability.md) | Privacy, security & portability | 135-144, 291-295, 453-460 |
| [0.12](0.12-desktop-shell-cli-linux.md) | Desktop shell, CLI & Linux | 145-162, 461-470 |
| [0.13](0.13-ui-theming-a11y-perf.md) | UI polish, theming, a11y, i18n, perf | 75-86, 173-188, 301-312, 359-368, 479-486 |
| [0.14](0.14-capture-pipeline-reliability.md) | Capture pipeline reliability | 323-332 |
| [0.15](0.15-knowledge-and-writing.md) | Knowledge work, learning & writing | 201-210, 369-378 |
| [0.16](0.16-proactivity-and-habits.md) | Proactivity, notifications & habits | 197-200, 285-290, 401-410 |
| [0.17](0.17-cross-device-and-mobile.md) | Cross-device, mobile & sync | 219-234 |
| [0.18](0.18-dx-testing-ops-ecosystem.md) | DX, testing, ops & ecosystem | 189-196, 389-396, 397-400, 495-500 |

## Rules for a bundle

- One theme, one release. If an idea does not serve the theme, it moves.
- Anything already shipped is checked off with the version that shipped it — do
  not re-add.
- Duplicated ideas are merged into their canonical number and marked *merge into
  #N* rather than implemented twice.
- Data-model changes land **first** in the bundle that needs them; later bundles
  depend on that bundle, not on each other's cherry-picks.

## Ordering

0.3 → 0.4 → 0.5 are sequential (capture writes notes, notes feed tasks).
Everything else is independent and can be taken in any order once 0.4 is out.
0.11 (privacy) is best done early even though it is listed late.
