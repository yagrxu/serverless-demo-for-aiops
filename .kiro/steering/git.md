# Git Rules

## Push

- Always use `--no-verify` when pushing to skip Code Defender pre-push hooks.
  ```bash
  git push --no-verify origin <branch>
  ```

## Branch model

- `main` — source of truth, all changes via PR
- `test` — deployment pointer for cloudops-demo (test account), force-push only
- `release` — deployment pointer for production (default profile)
  - Normal: fast-forward from main
  - Hotfix: accepts PR from hotfix/* branches (temporary workarounds that don't go into main)

## Feature branch workflow (normal)

1. Create feature branch from main: `git checkout -b feature/xxx`
2. Push and open PR to main
3. Squash-merge on GitHub
4. Deploy to test: `git push --no-verify --force-with-lease origin main:test`
5. Deploy to production: fast-forward release to main

## Deploying to test

```bash
git push --no-verify --force-with-lease origin main:test
```

## Deploying to production (normal)

```bash
git push --no-verify --force-with-lease origin main:release
```

## Hotfix workflow (emergency, code does NOT go into main)

1. Cut hotfix branch from release: `git checkout -b hotfix/xxx release`
2. Fix the issue (hardcoded workarounds are OK)
3. Push and verify on test: `git push --no-verify --force-with-lease origin hotfix/xxx:test`
4. Open PR: `hotfix/xxx → release`
5. Merge PR to release → triggers production deploy
6. When main has a proper fix later, force-push main to release to overwrite the hotfix:
   ```bash
   git push --no-verify --force-with-lease origin main:release
   ```
