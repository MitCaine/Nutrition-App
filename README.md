# Nutrition App

A personal, local-first nutrition tracker for iPhone. You build a food library, publish reusable
recipes, scan nutrition labels with Apple Vision, search USDA FoodData Central, and compare daily
intake against personalized targets. Everything runs on the device in SQLite.

The app is in maintenance mode: it runs on one iPhone (17 Pro Max), and ongoing work is mostly
patching dependency vulnerabilities reported by Dependabot.
See the **[maintenance guide](docs/maintenance.md)**.

## What the app does

- Creates, edits, duplicates, favorites, searches, and soft-deletes personal Foods.
- Resolves serving-based and gram-based nutrition using decimal-safe calculations.
- Searches USDA FoodData Central directly from the local runtime and imports selected foods.
- Builds Recipes from Foods or published nested Recipes.
- Publishes immutable Recipe revisions that remain safe to log over time.
- Records Daily Logs as immutable nutrient snapshots so later Food or Recipe edits cannot rewrite historical totals.
- Recognizes nutrition labels on iOS with Apple Vision, parses structured observations, and preserves correction provenance after confirmation.
- Compares daily nutrition with personalized targets where supported and FDA Daily Values where appropriate.
- Provides favorites, recents, unified saved/USDA discovery, light/dark presentation, and accessibility-focused navigation/focus behavior.
- Supports a one-time PostgreSQL-to-SQLite transfer path for installations migrating from the preserved remote runtime.

## Stack

| Area | Technology |
| --- | --- |
| App | React Native 0.86, Expo 57, TypeScript, TanStack Query, Zod |
| Data | On-device SQLite (`expo-sqlite`) with a schema-version migration engine |
| OCR | Swift Expo module using Apple Vision |
| Nutrition data | USDA FoodData Central (personal API key stored on device) |
| Parked | Python 3.14 / FastAPI / PostgreSQL 16 backend in `apps/backend` |

## Repository layout

| Path | What's there |
| --- | --- |
| `apps/mobile` | The iPhone app |
| `apps/backend` | Parked FastAPI/PostgreSQL remote runtime (not used by the app) |
| `packages/shared-contracts` | Small shared contract references |
| `engineering/` | DRI reference-data generator and source data for nutrition targets |
| `docs/` | [Maintenance](docs/maintenance.md), architecture, feature guides, parked backend docs |
| `scripts/` | Backend test runner and local backend start/stop |

## Quick start

Commands for running the checks and installing on the iPhone (which needs a Mac with Xcode) are in
the [maintenance guide](docs/maintenance.md#running-checks-locally).

## Docs

Start at the [documentation index](docs/README.md). The data-integrity rules the code relies on are
in [design decisions](docs/architecture/decisions.md).
