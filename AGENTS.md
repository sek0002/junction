# Junction releases

For every user-requested update that is published, increment the app version once before publication. Use semantic versioning: patch for bug fixes, styling and small interface adjustments; minor for new backward-compatible features; major for breaking changes. Combine changes in one release using the highest applicable increment. Do not bump for reads, checks, server restarts or an unpublished work-in-progress edit.

`app/version.py` is the single version source for the header, footer and FastAPI metadata. Use `python3 scripts/bump_version.py patch|minor|major`. Do not hardcode a separate display version. Include the version source and script in distribution packages.
