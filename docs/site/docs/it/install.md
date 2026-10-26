# Installazione

La prima release pubblica è la **0.10.0**. Scarica il file per la tua
piattaforma da [GitHub Releases](https://github.com/vigliafg/noesis-ebook-translator/releases).

| Piattaforma | File |
| --- | --- |
| Windows 10/11 x64 | `NoesisEbookTranslator-windows-x64-setup.exe` |
| Windows 10/11 x64 (portatile) | `NoesisEbookTranslator-windows-x64.zip` |
| macOS Apple Silicon | `NoesisEbookTranslator-macos-arm64.dmg` |
| macOS Intel | `NoesisEbookTranslator-macos-x64.dmg` |
| Linux x86_64 (Debian/Ubuntu) | `NoesisEbookTranslator-amd64.deb` |
| Linux x86_64 (Fedora) | `NoesisEbookTranslator-x86_64.rpm` |
| Linux x86_64 (portable) | `NoesisEbookTranslator-x86_64.AppImage` |

I pacchetti includono QtWebEngine (lettore full, PDF/MOBI/AZW3/FB2/CBZ ed
export PDF) e python-docx (export DOCX). **Non serve Python.**

## Linux

```bash
sudo apt install ./NoesisEbookTranslator-amd64.deb
sudo dnf install --nogpgcheck ./NoesisEbookTranslator-x86_64.rpm
chmod +x NoesisEbookTranslator-x86_64.AppImage
./NoesisEbookTranslator-x86_64.AppImage
```

Serve glibc ≥ 2.35 (Ubuntu 22.04, Debian 12, Fedora 36 o successivi). Se
Chromium non parte su un host senza user namespace, avvia con
`QTWEBENGINE_DISABLE_SANDBOX=1` (solo diagnostica: riduce l'isolamento del
browser).

## macOS

La build **non è firmata né notarizzata**. Al primo avvio: click destro
sull'app → **Apri**; in alternativa rimuovi il flag di quarantena:

```bash
xattr -dr com.apple.quarantine "/Applications/NoesisEbookTranslator.app"
```

Richiede macOS 13 o successivo.

## Windows

La build **non è firmata**: SmartScreen può mostrare *Windows protected your
PC*. Scegli **Ulteriori informazioni → Esegui comunque**. L'installer richiede
i privilegi di amministratore e installa per tutti gli utenti. La
disinstallazione non cancella le impostazioni
(`%APPDATA%\noesis-ebook-translator`) né libreria e cache
(`%LOCALAPPDATA%\noesis-ebook-translator`); elimina quelle cartelle a mano se
vuoi ripartire da zero.

## Versioni

La versione dell'**app** (0.10.0) è separata da quella del **motore** verbatim
(v2.4.2). Le vedi entrambe in **Info → About**. La versione del motore guida le
migrazioni della configurazione e i metadati della cache e non cambia con le
release dell'app.
