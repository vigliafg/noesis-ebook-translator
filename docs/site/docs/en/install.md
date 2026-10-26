# Install

The first public release is **0.10.0**. Download the file for your platform
from [GitHub Releases](https://github.com/vigliafg/noesis-ebook-translator/releases).

| Platform | File |
| --- | --- |
| Windows 10/11 x64 | `NoesisEbookTranslator-windows-x64-setup.exe` |
| Windows 10/11 x64 (portable) | `NoesisEbookTranslator-windows-x64.zip` |
| macOS Apple Silicon | `NoesisEbookTranslator-macos-arm64.dmg` |
| macOS Intel | `NoesisEbookTranslator-macos-x64.dmg` |
| Linux x86_64 (Debian/Ubuntu) | `NoesisEbookTranslator-amd64.deb` |
| Linux x86_64 (Fedora) | `NoesisEbookTranslator-x86_64.rpm` |
| Linux x86_64 (portable) | `NoesisEbookTranslator-x86_64.AppImage` |

The packages include QtWebEngine (full reader, PDF/MOBI/AZW3/FB2/CBZ and PDF
export) and python-docx (DOCX export). Python is **not** required.

## Linux

```bash
sudo apt install ./NoesisEbookTranslator-amd64.deb
sudo dnf install --nogpgcheck ./NoesisEbookTranslator-x86_64.rpm
chmod +x NoesisEbookTranslator-x86_64.AppImage
./NoesisEbookTranslator-x86_64.AppImage
```

The minimum glibc is 2.35 (Ubuntu 22.04, Debian 12, Fedora 36 or newer). If
Chromium cannot start on a host without unprivileged user namespaces, run with
`QTWEBENGINE_DISABLE_SANDBOX=1` (diagnostic only: it reduces browser isolation).

## macOS

The build is **not signed/notarized**. On first launch, right-click the app and
choose **Open**; alternatively remove the quarantine flag:

```bash
xattr -dr com.apple.quarantine "/Applications/NoesisEbookTranslator.app"
```

Requires macOS 13 or newer.

## Windows

The build is **not code-signed**: SmartScreen may show *Windows protected your
PC*. Choose **More info → Run anyway**. The installer requires administrator
rights and installs for all users. Uninstalling does not delete your settings
(`%APPDATA%\noesis-ebook-translator`) or your library/cache
(`%LOCALAPPDATA%\noesis-ebook-translator`); remove those folders manually if you
want a clean slate.

## Versions

The application version (`0.10.0`) is separate from the verbatim engine version
(`v2.4.2`). You can see both in **Info → About**. The engine version is used for
configuration migrations and cache metadata and does not change with the app
release.
