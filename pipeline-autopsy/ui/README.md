# Pipeline Autopsy UI

The Vite + React interface shows recent executions from the schema-v2 read API. The run list filters by pipeline, verdict, time range, and entity ID; it refreshes every five seconds and follows the API cursor for pagination.

## Local development

```powershell
cd pipeline-autopsy/ui
npm install
npm run dev
```

Open `http://127.0.0.1:5173/ui/`. Configure a local API key from the top bar, or set `VITE_AUTOPSY_API_KEY` before building for a single-user local deployment. Keys stored in the browser remain in local storage.

## Container deployment

The Autopsy Docker image builds this UI and serves it from FastAPI at `http://127.0.0.1:8080/ui/`. Client-side run routes are served through the same entry point, so reloading a run detail URL works. Start the application and its database from `pipeline-autopsy` with `docker compose up --build`.

## Checks

```powershell
npm run build
npm test
npm run test:e2e
```

The browser test starts an isolated SQLite-backed Autopsy server and loads the three synthetic golden runs. Playwright installs Chromium in CI.
