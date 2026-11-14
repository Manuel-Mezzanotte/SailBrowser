# Sail

Sail è un browser per macOS e Windows basato su [Helium](https://github.com/imputnet/helium), che a sua volta è basato su Chromium.

## Scaricare Sail

- **Windows (x64)**: l'installer `Sail-…-setup.exe` esce dalla build cloud, nella scheda [Actions](https://github.com/Manuel-Mezzanotte/SailBrowser/actions/workflows/windows.yml) → l'ultima build riuscita → *Artifacts* → `sail-windows-x64`. L'installer non è firmato: al primo avvio Windows SmartScreen avvisa, basta premere "Ulteriori informazioni" → "Esegui comunque".
- **macOS (Apple Silicon)**: il DMG si crea sul Mac, con la build descritta sotto.

## Com'è organizzato il repository

| Cartella | Cosa contiene |
| --- | --- |
| [`sail/`](sail/) | Tutto ciò che è di Sail: rebrand, patch delle funzioni (picture in picture, nuova scheda…), icone, strumenti. Vale per entrambi i sistemi. Vedi [`sail/README.md`](sail/README.md). |
| [`macos/`](macos/) | La build per Mac, presa da [helium-macos](https://github.com/imputnet/helium-macos): patch e risorse per macOS, script di build, firma e DMG. |
| [`windows/`](windows/) | La build per Windows, presa da [helium-windows](https://github.com/imputnet/helium-windows): patch e risorse per Windows, `build.py`, `package.py` e l'installer NSIS. |
| `helium-chromium/` | Il codice comune di Helium (submodule), usato da entrambe le build. |
| `.github/` | La build cloud per Windows (GitHub Actions). |
| `build/` | Non è nel repository: il codice di Chromium preparato (`build/src`), la cache dei download e i pacchetti finiti. Mac e Windows usano la stessa posizione, ognuno sulla propria macchina. |

Le due build preparano il codice come fa Helium e alla fine lanciano `sail/rebrand.py`, che applica Sail sopra Helium.

## Build per Mac

Servono Xcode, ImageMagick e circa 100 GB liberi. La prima build dura qualche ora.

```bash
cd macos
./build.sh
```

Per riprendere una build interrotta senza ripartire da zero:

```bash
cd macos
source devutils/shared.sh && helium_build -j 4 chrome/installer/mac && ./sign_and_package_app.sh
```

Il DMG finisce in `build/sail_<versione>_macos.dmg`.

## Build per Windows

Non serve un PC Windows: la build gira sui server di GitHub. Nella scheda *Actions* scegli **Windows build** → *Run workflow*, oppure:

```bash
gh workflow run windows.yml --ref main
```

Chromium è grande, quindi la build è divisa in tappe da 5 ore e mezza (un job di GitHub può durare al massimo 6 ore) e in tutto richiede circa 1-2 giorni. Ogni tappa salva il lavoro e la successiva riparte da lì. Alla fine `windows/package.py` crea l'installer, il mini installer e lo zip portatile.

Per compilare su un PC Windows, segui [`windows/README.helium.md`](windows/README.helium.md) e lancia `python windows\build.py` dalla cartella del repository.

## Licenza

GPL-3.0, come Helium. Vedi [`LICENSE`](LICENSE). Le intestazioni "The Helium Authors" e "The Chromium Authors" nei file restano, come richiede la licenza.
