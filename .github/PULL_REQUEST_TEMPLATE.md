## Summary

<!-- What does this change and why? Link the issue if there is one. -->

## Checklist

- [ ] `python -m pytest tests -q` passes (add tests for new behaviour)
- [ ] Docs updated (README, `docs/`, `CHANGELOG.md` under Unreleased) where behaviour changed
- [ ] No new request to another host, and no CDN link in a template (vendor it in `static/vendor/`)
- [ ] A change to how days are counted goes through the shared helpers in `app.py`, and `CHANGELOG.md` says what changed
- [ ] UI change? A screenshot is attached
