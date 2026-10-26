# packaging

Native release assets, shared by `.github/workflows/release.yml`.

| File | Used by | Notes |
| --- | --- | --- |
| `app.spec` | PyInstaller (all platforms) | onedir build; includes QtWebEngine, `reader_web`, locales, token encodings, icons, license files |
| `../installer.nsi` | Windows job | installer payload is `dist/NoesisEbookTranslator/` |
| `macos/dmg.sh` | macOS job | `.app` + `/Applications` symlink + ad-hoc signature verification |
| `linux/nfpm-deb.yaml`, `linux/nfpm-rpm.yaml` | deb/rpm | `nfpm package -f ...` |
| `linux/noesis-ebook-translator.desktop` | deb/rpm/AppImage | desktop entry |
| `linux/noesis-ebook-translator.metainfo.xml` | deb/rpm | AppStream metadata |
| `linux/AppRun` | AppImage | launches the onedir binary |
| `linux/build-appimage.sh` | Linux job | assembles the AppDir and calls appimagetool |

The release workflow is the source of truth for the exact commands. Builds are
**onedir** on purpose: QtWebEngine needs its helper process and resources next
to the binary.
