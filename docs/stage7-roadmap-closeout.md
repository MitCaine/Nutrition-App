# Stage 7D: Roadmap closeout and release-QA backlog

## Original roadmap status

| Stage | Scope | Implementation | Automated contract | Outstanding release QA |
| --- | --- | --- | --- | --- |
| 1 | Monorepo, backend/mobile foundation, migrations, canonical nutrition domain, Decimal-safe utilities | Complete | Complete | Environment-specific release build verification |
| 2 | Manual Foods, servings, snapshot-based Daily Logging and aggregation | Complete | Complete | Populated device lifecycle and keyboard checks |
| 3 | USDA search, preview, normalized import, provenance, and reuse in logging | Complete | Complete | Live USDA/network failure checks with production configuration |
| 4 | Recipes, immutable publication revisions, current/historical logging | Complete | Complete | Populated nested-Recipe device flows |
| 5 | Apple Vision native OCR bridge and still-camera capture | Complete | Complete | Physical camera, overlay, and permission QA |
| 6 | Parser, golden fixtures, confirmation, Food creation, privacy, recovery, and service-immutable / append-only traces | Complete | Complete | Physical capture and overlay QA before release |
| 7 | FDA Daily Values, optional personal targets, comparison/progress presentation, recents, favorites, and source labels | Complete | Complete | Populated discovery, accessibility, theme, and live retry QA |

The original Stage 1–7 roadmap is implementation-complete and automated-contract-complete. Manual release QA is not represented as complete. Recipe favorites, recommendations, ranking, coaching, notifications, synchronization, and other broader product capabilities are intentional expansion rather than missing roadmap implementation.

## Release-QA backlog

- [ ] Physical-device OCR camera capture and Apple Vision runtime behavior.
- [ ] OCR overlay alignment across supported device sizes and orientations.
- [ ] Photo-library and camera permission denial, recovery, and Settings handoff.
- [ ] Populated favorite/unfavorite transitions for Manual, USDA, scanned-label, and duplicated Foods.
- [ ] Populated recency transitions: repeated use, past-date log, newest-log deletion, and deterministic ordering.
- [ ] Favorited/recent Food soft deletion and remaining lifecycle presentation.
- [ ] Saved Foods search plus logging and Recipe ingredient selectors with representative source types.
- [ ] Light and dark theme visual pass.
- [ ] VoiceOver on iOS and TalkBack on Android, including preview headings, source labels, selected state, and retries.
- [ ] Keyboard avoidance, dismissal, and restored scroll position on production device sizes.
- [ ] Live network failure and retry for discovery, logging, USDA, OCR confirmation, and target settings.
- [x] PostgreSQL concurrent favorite creation; keep the PostgreSQL concurrency suite in release validation.
- [ ] Resolve or formally accept the known React test-renderer `act()` warnings.
- [ ] Upgrade or formally accept the Starlette/httpx deprecation warning.
