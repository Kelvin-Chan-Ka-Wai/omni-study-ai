# Frontend

React + Vite workspace for lecture notes, timed assessments, wrong-question practice and voice tutoring. Note history/source links and backup tools are separate components under `src/components/layout`.

Run `npm ci` and `npm run dev -- --host 127.0.0.1`. Use http://127.0.0.1:5173 with the backend on http://127.0.0.1:8000. The API client establishes a local HttpOnly session; credentials are never saved in browser draft recovery storage. `VITE_BACKEND_URL` is available for isolated local UI testing.

`npm run build` checks TypeScript and produces the local production bundle. `dist/` and `node_modules/` stay out of Git. Existing Settings/GenAI fields and provider integration are preserved.
