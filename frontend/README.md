# Traceback desktop UI

The `frontend/` package is Traceback's desktop-only Next.js interface. It is not a standalone hosted product: it proxies same-origin `/api/v1/*` requests to the local FastAPI backend and attaches the API bearer token on the server, keeping that token out of browser JavaScript.

Implemented screens include Tasks, Inbox, all six fixed categories, projects and nested folders, note detail/editing, manual and quick note creation, search, Archive, Skills, and task creation. `/` opens Tasks. There is no Today page or mobile implementation.

## Configuration

The FastAPI backend must already be running. Copy the committed placeholder and replace its token with the value from the repository-root `.env`:

```sh
cp .env.local.example .env.local
```

The resulting ignored `frontend/.env.local` contains:

```dotenv
TRACEBACK_API_BASE_URL=http://127.0.0.1:8000
TRACEBACK_API_TOKEN=<same value as the repository-root .env>
```

Never expose the token through a `NEXT_PUBLIC_*` variable and never commit `.env.local`.

## Development

```sh
npm install
npm run dev
```

Open `http://localhost:3000`. Use `localhost`, rather than `127.0.0.1`, for the development UI because Next.js development-origin handling can otherwise block its own assets.

The optional local processor is a separate Python service. Manual UI operations work without it. Task quick add and AI-assisted note placement remain saved and show recoverable states when processing is unavailable.

## Checks

```sh
npm test -- --run
npm run typecheck
npm run lint
npm run build -- --webpack
```

The final verified baseline at commit `916d557` was 29 frontend tests passing, with type checking, lint, and the webpack production build passing.

Private development notes are kept locally under ignored `docs/` in the repository root.
