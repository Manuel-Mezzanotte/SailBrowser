# Sail

Sail è un browser basato su [Helium](https://github.com/imputnet/helium), che a sua volta è basato su Chromium.
Tutte le modifiche di Sail stanno in questa cartella. Così, quando si importano gli aggiornamenti di Helium, i conflitti restano pochi.

## Come funziona

La build prepara il codice come Helium (patch, sostituzione dei nomi, risorse). Alla fine lancia `sail/rebrand.py`: su Mac lo fa `prepare_sources` in `macos/devutils/shared.sh`, su Windows `windows/build.py` (con `--platform windows`). Lo script:

- **nome**: cambia "Helium" in "Sail" in tutti i testi dell'interfaccia, in ogni lingua, anche dove il nome è attaccato ad altre lettere (finlandese "Heliumin", coreano "Helium을", amarico "የHelium");
- **servizi online**: i "Servizi Helium" diventano "Servizi online" (vedi sotto);
- **indirizzi interni**: usa `sail://` al posto di `helium://`;
- **identità dell'app**: su Mac usa il bundle ID `com.manuelmezzanotte.sail`, la cartella dati `~/Library/Application Support/com.manuelmezzanotte.sail` e la voce del portachiavi "Sail Storage Key". Su Windows usa la cartella `%LOCALAPPDATA%\Sail\Sail`, chiavi di registro e un ID app propri (`{BC9170C5-6303-4228-AF17-46D482BEC3FA}`, lo stesso di `windows/installer/sail.nsi`), così Sail e Helium possono stare installati insieme;
- **crash report**: li disattiva, così non vengono mai inviati ai server di Helium;
- **icone e loghi**: copia quelli di `sail/resources/` sopra quelli di Helium, compresa l'icona della scheda Nuova scheda;
- **schermata di benvenuto**: mette il logo di Sail (anche nell'animazione di importazione), toglie il badge "Helium Partner" e collega privacy e termini a [`PRIVACY.md`](PRIVACY.md) e alla licenza;
- **flag** (`sail://flags`): nomi `#sail-…` e descrizioni con "Sail";
- **Chrome Web Store**: il pulsante dice "Aggiungi a Sail";
- **uBlock Origin**: liste "Sail filters" e pagina Informazioni di Sail;
- **crediti** (`sail://credits`): indicano il codice sorgente di Sail, come richiede la GPL-3.0.

Prima di tutto questo, lo script applica le patch di `sail/patches/`, nell'ordine del file `series`: sono le funzioni proprie di Sail (vedi sotto). Le patch sono scritte sul codice com'è dopo la preparazione di Helium. Quelle già presenti nell'albero vengono saltate. Se una non si applica più, per esempio perché un aggiornamento di Helium ha cambiato quel codice, lo script si ferma e dice quale.

Lo script si può rilanciare quante volte si vuole. Ogni modifica al codice è una corrispondenza esatta: se un aggiornamento di Helium cambia una di quelle righe, lo script si ferma e dice quale riga, invece di indovinare.

Per applicarlo a mano su un albero già preparato:

```bash
python3 sail/rebrand.py build/src
```

## Funzioni di Sail

### Picture in picture (`sail/patches/picture-in-picture/`)

Ripreso da Oblò, la versione per Zen in `~/Desktop/IdeeRandom/oblo-zen`.

- **Automatico**: se cambi scheda mentre un video va con l'audio acceso, il video esce in una finestra picture in picture. Esce anche quando un'altra app copre la finestra di Sail. Quando torni sulla scheda la finestra si chiude da sola.
- **Su tutti i siti**: non serve dare il permesso sito per sito e nella finestra non compare la domanda "Consenti / Blocca". Un sito si può comunque bloccare in Impostazioni → Privacy e sicurezza → Impostazioni sito, alla voce del picture in picture automatico.
- **⌥P**: apre il picture in picture del video della scheda e lo richiude. Dentro la finestra picture in picture, ⌥P riporta il video nella pagina senza metterlo in pausa. Il comando è nel menu Schede e la scorciatoia si può cambiare nelle impostazioni delle scorciatoie.
- **Pulsante sui video**: come in Zen, passando sopra un video della pagina compare a destra un pulsante che apre il picture in picture (o riporta indietro il video, se c'è già). Non compare sui video più corti di 45 secondi, su quelli piccoli e sulle anteprime di YouTube. È un'estensione interna (`components/sail_pip_button`), che non si vede nella pagina delle estensioni.
- **Da spegnere**: in `sail://flags`, con `#browser-initiated-automatic-picture-in-picture` (cambio scheda) e `#auto-picture-in-picture-on-window-occluded` (altre app).
- **Aspetto**: quello di Oblò. In alto a sinistra, in una pillola di vetro sfocato, ci sono chiudi e torna alla scheda. In alto a destra c'è il volume. Al centro ci sono play/pausa e i dieci secondi indietro e avanti. In basso ci sono il tempo trascorso, una barra sottile e il tempo rimanente, oppure "Live" per le dirette. Tutto cresce con la finestra; nelle finestre piccole i dieci secondi e i tempi spariscono. In alto non ci sono più sito e favicon.
- **Controlli**: compaiono quando muovi il mouse e quando il video parte o si ferma. Spariscono dopo un paio di secondi, ma restano mentre il video è in pausa e mentre il mouse è sopra un controllo. Il cursore sparisce con loro.
- **Spostare**: si trascina il video. La finestra passa da un monitor all'altro dove si toccano e si ferma contro i bordi liberi, la barra dei menu e il Dock, come in Arc. Se la lasci a metà sopra una barra dei menu, scende da sola. Dopo un ridimensionamento che la fa sbordare, rientra.
- **Grandezza**: dai bordi, con le proporzioni del video, fino a tutto lo schermo (Chromium si ferma all'80%).
- **Click e doppio click**: un click mostra o nasconde i controlli, un doppio click (o **F**) fa riempire lo schermo alla finestra, e un altro la riporta com'era.
- **Barra**: si ingrossa sotto il mouse; il video salta dove lasci il mouse.
- **Tasti**: **spazio** o **K** play/pausa, **← →** o **J L** dieci secondi, **↑ ↓** volume, **M** audio, **Esc** riporta il video nella scheda (o esce dallo schermo pieno), **⌥P** lo riporta nella pagina senza metterlo in pausa.
- **Volume**: passando sopra all'altoparlante scende il cursore. Un click toglie o ridà l'audio, la rotellina lo regola. È il volume della scheda, applicato sopra quello della pagina. Quando la finestra si chiude torna al 100%, così nella pagina conta di nuovo il suo controllo del volume.

Come per il pulsante dei controlli multimediali, funziona sulle pagine con un solo video. Nelle finestre in incognito il picture in picture automatico resta spento, come in Chromium.

### Nuova scheda (`sail/patches/new-tab-page/`)

- **Stile della pagina**: nel pannello della penna, in basso a destra nella Nuova scheda, c'è una sezione in più. Puoi cambiare la grandezza delle scorciatoie, mettere il vetro dietro le icone, togliere i nomi, mostrare un orologio grande con il saluto, e scurire e sfocare lo sfondo. Le modifiche si vedono subito; "Ripristina" torna allo stile di partenza.
- **Scorciatoie**: passandoci sopra l'icona si solleva, senza la cornice attorno; ⋮ compare subito, come un pallino di vetro sull'angolo dell'icona. Il menu Modifica/Rimuovi e il modulo per creare o modificare una scorciatoia hanno lo stile di Sail: scuri, arrotondati, con l'icona grande in alto nel modulo.
- **Icone tue**: ⋮ su una scorciatoia → Modifica → clic sull'icona grande (o "Cambia icona"). L'immagine viene ritagliata quadrata e riempie il riquadro, come l'icona di un'app. "Icona del sito" rimette quella del sito.
- **Icone nitide**: invece della favicon ingrandita, le scorciatoie mostrano l'icona grande che il sito dichiara. Le icone d'app (apple-touch-icon) riempiono tutto il riquadro; gli altri loghi grandi lo riempiono quasi. Per Gmail, Drive, Calendar, Docs e Meet si usano le icone ufficiali di Google. Sail legge la pagina del sito senza cookie, scarica l'icona con `chrome://image` (decodificata in un processo isolato) e la ricorda per una settimana. Se il sito non ne ha, resta la favicon, ora alla risoluzione dello schermo.
- Le scelte sono salvate nel profilo (`sail.ntp.look` e `sail.ntp.icons`), non sincronizzate.

## Passare da Zen a Sail

- **Preferiti e cronologia**: chiudi Zen, poi in Sail apri `sail://settings/importData` e scegli Zen (il profilo che usi, di solito "Default (release)"). L'importazione da Zen c'è già, l'ha aggiunta Helium.
- **Password**: Chromium non le importa più da altri browser. In Zen apri `about:logins`, menu ⋯ → Esporta password. In Sail apri `sail://password-manager/settings` → Importa password e scegli il file. Poi cancella il file: contiene le password in chiaro.
- **Account a cui sei collegato** (i cookie): con Zen e Sail chiusi lancia

  ```bash
  python3 sail/tools/import_zen_accounts.py
  ```

  macOS chiede il permesso di leggere la "Sail Storage Key" dal portachiavi. Lo script copia i cookie di Zen in Sail, cifrati come li salva Sail, e prima fa una copia dei cookie di Sail (`Cookies.before-zen-…` nella cartella del profilo). Con `--dry-run` conta soltanto. Lascia fuori i cookie scaduti e quelli dei siti incorporati in altri, che potrebbero sostituire quelli veri del sito e farti uscire. Alcuni siti chiedono comunque di rifare l'accesso: Google a volte si accorge che il browser è cambiato, e i siti che tengono l'accesso nei dati della pagina invece che nei cookie (WhatsApp Web, Discord…) non lo vedono.
- **Cosa non passa**: le estensioni (si reinstallano dal Chrome Web Store; uBlock in Sail c'è già), i dati salvati dai siti e i permessi dei siti.

## Logo e icone

La forma della vela è definita in un solo punto: `sail/branding/generate_assets.py`. Lo script genera tutto il resto in `sail/resources/`:

- `logo.svg`: il master vettoriale sulla griglia Apple (tela 1024, riquadro 824);
- `logo_1024.png`: lo stesso logo in PNG;
- icona macOS 26+ (`AppIcon.icon` compilata in `Assets.car`). macOS ci aggiunge l'effetto vetro e la disegna da sé a ogni misura, Finder compreso;
- icone per macOS precedenti (`app.icns`): a 16 e 32 px sono disegnate pixel per pixel, così albero e vela restano separati;
- loghi interni;
- favicon della Nuova scheda (16 e 32 px), nel grigio delle altre favicon di Chromium;
- icone vettoriali `.icon`;
- logo della schermata di benvenuto.

Il colore si sceglie con `PALETTE` (oppure `--color`): `nero` o `blu-notte`. Per vedere un colore senza toccare i file del repository:

```bash
python3 sail/branding/generate_assets.py --color blu-notte --out /tmp/anteprima
```

I file generati sono salvati nel repository, quindi la build normale non ha bisogno di rigenerarli. Dopo aver cambiato il logo:

```bash
python3 sail/branding/generate_assets.py
```

Servono ImageMagick, Xcode (per `actool` e `iconutil`) e il codice già preparato in `build/src`.

## Firma locale

`sign_and_package_app.sh` firma l'app con il certificato "Sail Local Signing", se nel portachiavi ce n'è uno con quel nome (il nome si può cambiare con `SAIL_LOCAL_SIGNING_IDENTITY`). Altrimenti la firma è ad-hoc.

Il certificato serve per la Sail Storage Key. Con la firma ad-hoc, per macOS ogni build è un'app nuova, quindi il portachiavi chiede di nuovo la password dopo ogni build. Con il certificato basta premere "Sempre" una volta.

Il certificato è autofirmato e vale solo su questo Mac. Per distribuire Sail ad altri servono comunque firma e notarizzazione Apple (vedi sotto).

## Cosa resta di Helium, di proposito

Nell'app il nome Helium non compare più. Restano, di proposito:

- **I server dei servizi online**: download delle estensioni, liste filtri di uBlock, `!bang`, aggiornamenti dei componenti. Sail usa ancora i server di Helium. Per questo nell'interfaccia si chiamano "Servizi online" e non "Servizi Sail", che farebbe pensare a server di Sail. [`PRIVACY.md`](PRIVACY.md) dice chiaramente chi li gestisce. Per essere del tutto indipendenti servirebbe un'istanza propria, configurabile in Impostazioni → Privacy e sicurezza → Servizi online.
- **Traduzioni dei servizi online**: inglese e italiano sono riscritti. Nelle altre lingue quelle circa 20 frasi compaiono in inglese finché qualcuno non le traduce.
- **Aggiornamenti automatici**: non ci sono, perché Sparkle è attivo solo nelle build ufficiali di Helium. Gli aggiornamenti si fanno ricompilando.
- **Nomi interni nel codice**: restano invariati (`helium::`, `kHeliumUIScheme`, nomi di file, preferenze e impostazioni). Non si vedono e rinominarli renderebbe difficile importare gli aggiornamenti.
- **Copyright e crediti**: le intestazioni "The Helium Authors" nei file e Helium tra i componenti in `sail://credits` restano, come richiede la GPL-3.0.

## Da fare prima di una release pubblica

- Rigenerare `macos/resources/dmg_dsstore` per `Sail.app` con `macos/devutils/generate_dmg_dsstore.sh`. Senza, nel DMG l'icona di Sail non è nella posizione prevista.
- Firma e notarizzazione con un account Apple Developer.
- Firma del codice su Windows. Senza, al primo avvio SmartScreen avvisa ("Ulteriori informazioni" → "Esegui comunque").
- Unire `sail/rebrand` in `main`: i link a privacy e termini nell'app puntano a `blob/main`.
- Tradurre le frasi dei "Servizi online" nelle lingue diverse da inglese e italiano.
