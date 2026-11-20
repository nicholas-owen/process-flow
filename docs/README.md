# docs

| File | What |
|---|---|
| `guide.md` | The long-form guide: the one command, and the Analyser walkthrough for pipeline authors |
| `build_user_guide.js` | Generates `../process-flow_User_Guide.docx`, the Word user guide |

The Word guide is generated, not hand-edited. To change it, edit the content
in `build_user_guide.js` and rebuild:

```bash
cd docs
npm install       # once: docx, and resvg to render the logo
npm run build
```

The build renders `../assets/process-flow_logo.svg` (the logo the viewer
shows) to `../assets/process-flow_logo.png` for the title page, and reads the
version from `../tools/version.py`, so neither can drift from the release.
Rebuild after changing either.
