# Z-OS Codex Operating Instructions

## Scope
Work only in:

frontend/z-os-app-source

Do not modify unrelated backend, engine, tests, backup, root, workflow, or deployment files unless explicitly requested.

## Required pre-check
Before editing, verify:

pwd
ls -la frontend/z-os-app-source
cat frontend/z-os-app-source/package.json
npm run --prefix frontend/z-os-app-source validate

If frontend/z-os-app-source is missing, stop and report:
"frontend/z-os-app-source missing in this checkout."

## Build / validate
After any change, run:

npm run --prefix frontend/z-os-app-source validate

If relevant, also run:

npm run --prefix frontend/z-os-app-source build
npm run --prefix frontend/z-os-app-source validate

## Deployment
Do not SSH into VPS.
Do not manually deploy from Codex.

Deployment is handled only by GitHub Actions:

Actions → Deploy z-os-app-source to VPS → Run workflow

## Output format
At the end of each task, report:

1. changed files
2. validation result
3. whether GitHub Actions deploy should be run
4. risks / rollback notes
