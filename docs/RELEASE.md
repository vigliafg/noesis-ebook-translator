# Release checklist — 0.10.0

La release è **non firmata**: macOS richiede click destro → Apri e Windows può
mostrare SmartScreen. Le note di release devono dirlo.

**0.10.0 non usa release candidate.** Il flusso è: dry-run → matrice manuale
sugli artefatti prodotti → tag `v0.10.0` → draft → pubblicazione.

## 0. Prima di taggare

- [ ] `APP_VERSION` in `noesis_ebook_translator/__init__.py` = `0.10.0`.
- [ ] `pyproject.toml` e il default di `installer.nsi` = `0.10.0`.
- [ ] `CHANGELOG.md` ha una sezione `## [0.10.0] - AAAA-MM-GG`.
- [ ] `README.md` e `docs/site/docs/{en,it}/install.md` hanno i nomi dei file
      della release e i limiti noti.
- [ ] `THIRD_PARTY_NOTICES.md` e `LICENSES/` aggiornati.
- [ ] `ENGINE_SOURCE.json` invariato (nessuna modifica al motore).
- [ ] `python -m unittest discover -s tests -v` verde.
- [ ] `python tools/scenario_harness.py` verde.
- [ ] `cd docs/site && mkdocs build --strict` verde.
- [ ] `python main.py --self-test --require-full --report /tmp/self.json` verde.
- [ ] `git status` pulito e nessun segreto (`opencode-go.txt`,
      `openrouter.txt` restano ignorati).

## 1. Dry-run della build

Actions → **release** → Run workflow (`workflow_dispatch`). Questo **non
pubblica**: produce solo gli artefatti e li collauda con `--self-test`,
`--self-test-reader`, installazione Windows, mount DMG e container deb/rpm.

- [ ] Tutti e quattro i job `build` verdi.
- [ ] `checksums` verde.
- [ ] Il job `release` non è partito (dispatch non pubblica mai).
- [ ] Scaricare gli artefatti del dry-run e verificare `SHA256SUMS`.

## 2. Matrice manuale (artefatti del dry-run)

Installare da zero, con profilo/config assente, su:

| Sistema | Cosa provare |
| --- | --- |
| Windows 10 22H2 e 11 | setup, prima apertura, SmartScreen, disinstallazione |
| macOS 13/14 (se disponibile) e 15 arm64/x64 | DMG, Gatekeeper (`Apri`), lettore full |
| Ubuntu 22.04 e 24.04 | deb, AppImage |
| Debian 12 | deb |
| Fedora 40 | rpm |

Per ogni piattaforma:

- [ ] onboarding, lingua e tema;
- [ ] apertura EPUB, TOC multilivello, figure;
- [ ] traduzione con motore fittizio o chiave reale, annullamento e ripresa;
- [ ] lettore **full**: EPUB, PDF, CBZ; navigazione e ricerca;
- [ ] export PDF e DOCX;
- [ ] `--self-test` e `--self-test-reader` dall'installazione;
- [ ] disinstallazione: restano solo i dati utente (documentato).

Problemi bloccanti: crash all'avvio, lettore full che non apre un EPUB, export
PDF/DOCX assente, cache persa, installer che non disinstalla, artefatto corrotto.

## 3. Release finale 0.10.0

```bash
git tag v0.10.0
git push origin v0.10.0
```

- [ ] La guardia accetta il tag solo con `APP_VERSION == 0.10.0`.
- [ ] La draft contiene i 6 artefatti + `SHA256SUMS`.
- [ ] `sha256sum -c SHA256SUMS` sui file scaricati.
- [ ] Pubblicare la draft (non pre-release) dopo il go/no-go.
- [ ] Controllare che i link download del README risolvano.

## 4. Dopo la release

- [ ] Aggiornare `CHANGELOG.md` con `## [Unreleased]` per la prossima versione.
- [ ] Aprire issue per il backlog noto: single-instance, ResourceWarning sqlite,
      test unitari su Windows/macOS, firma/notarizzazione, Linux arm64.
- [ ] Verificare che la pagina help (GitHub Pages) sia pubblicata.
