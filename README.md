# poliquicks-site

Static marketing site for [Poliquicks](https://www.poliquicks.com/), migrated off Squarespace to GitHub Pages.

## Layout

- `mirror/` — raw `wget` dump of the live Squarespace site. Reference only; do not edit.
- `docs/` — deployable artifact. This is what GitHub Pages serves.

## Local dev

```
cd docs
npx serve .
```

## Deploy

Pushes to `main` are published automatically by GitHub Pages (Settings → Pages → source: `main`, folder: `/docs`).

## Load-bearing pages

- `/auth-action/` — Firebase email-verification / password-reset handler. Hit by real users from the mobile app. Any change to this page must be tested with live Firebase action URLs before merging.
- `/delete-account/` — required by App Store / Play Store policy.
- `/app-ads.txt` — AdMob verification for the Play Store app. Path is fixed by Google.
