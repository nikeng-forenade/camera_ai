## Version 0.17.55 - 2026-09-11

- Added an early visual mockup for the planned recordings and event timeline view: `docs/mockups/recordings-timeline.svg`.
- Added per-camera MP4 recording settings: mode, recording folder, retention and segment length. Recordings use ffmpeg stream copy and default to 10-second segments.
- Added an Inspelningar view with camera/date selection, MP4 playback, segment timeline and AI-event markers.
- Fixed the recordings view API request so it does not depend on a private frontend helper scope.
- Upgraded the recordings view to a 24-hour visual timeline with positioned video segments, a playback head and color-coded AI-event markers.
- Added a selectable recording time span with From/To fields and 1, 3, 6 and 24-hour quick filters.
# Ändringsnoteringar

## Version 0.17.53 - 2026-09-10
- Historikens stora bild med boxar öppnas nu som en tillfällig JPEG-blob i stället för en `data:image/jpeg`-URL, vilket undviker tom visning i webbläsare som inte hanterar data-URL:en korrekt.

## Version 0.17.52 - 2026-09-10
- Fixad storbildsöppning från Historik: boxbilden öppnas nu direkt som en färdig bild i stället för att försöka skriva till en isolerad blank flik.

## Version 0.17.51 - 2026-09-10
- Historikens stora bildvy ritar nu också detektionernas boxar när "Visa boxar" är aktiverat, även för äldre events med sparade detektionskoordinater.

## Version 0.17.50 - 2026-09-10
- Historikbilderna är fortsatt sparade utan överlägg, men Historik har nu ett valbart "Visa boxar"-reglage som ritar detektionernas boxar ovanpå miniatyrbilderna i webbläsaren. Valet sparas lokalt per webbläsare.

## 2026-09-08
- Version `0.17.49`: HACS-integrationen visar nu LPR – nya sensorer `sensor.camera_ai_last_plate` (senast uppläst skylt, global) och `sensor.camera_ai_<kamera>_last_plate` (per kamera) med attribut `plate`, `confidence`, `timestamp`, `count`. Hämtas från serverns `GET /api/lpr`.
- Version `0.17.48`: zonetiketter (ZON 1/2) nu mindre – en liten ruta i zonens hörn.
- Version `0.17.47`: dashboardens kameraväljare är nu också knappar (som i Inställningar) – en ny kamera ger en ny knapp.
- Version `0.17.46`: per-kamera LPR-inställningar – välj om LPR ska köra på kameran och vilken ström (huvudström hög upplösning / sub). Global LPR måste även vara på.
- Version `0.17.45`: kamerorna i Inställningar är nu knappar (inte dropdown) – en ny kamera ger en ny knapp, klicka för att redigera.
- Version `0.17.44`: System / Runtime visar main-strömsinfo; Dashboard har "🖥️ Visa main"-knapp (hämtar högupplöst main-bild via `/snapshot.jpg?main=1`). Mindre zonetiketter (ZON 1/2).
- Version `0.17.43`: kameraskanning deduplicerar nu strömmar (samma main/sub svarar på flera alias h264/h265/Preview) – visar bara bästa main + bästa sub (`h264Preview` föredras).
- Version `0.17.42`: fix kameraskanning – använder nu kamerans sparade inloggning (lösenordsfältet är tomt för befintliga kameror), och main-sökvägen härleds automatiskt från sub om skanningen inte hittar den. `main_path` sparas nu även för befintliga kameror.
- Version `0.17.41`: kameraskanning (som Blue Iris) – "🔍 Skanna strömmar" provar vanliga RTSP-sökvägar och fyller i sub/main automatiskt. Ny "🖥️ Testa main"-knapp som verifierar att main-strömmen är korrekt (upplösning/FPS/kod).
- Version `0.17.40`: valfri inställning "Main-ström sökväg" under Kameror. Lämnas den tom härleds main automatiskt från sub (`_sub` → `_main`); fyll i den bara om kameran avviker.
- Version `0.17.39`: LPR använder nu en högupplöst bild från huvudströmmen när YOLO fångat ett fordon på sub-strömmen. Boxen skalas till main-upplösning och OCR körs på den skarpare bilden (hämtas i bakgrunden, blockerar inte YOLO). Main-sökvägen härleds automatiskt (`_sub` → `_main`).
- Version `0.17.38`: bättre skyltläsning – snävare skyltzon (nedre centrala delen av fordonsrutan) + CLAHE-kontrastförstärkning, så tecken som N/E/D läses säkrare (t.ex. `RND 594` i stället för `RED594`).
- Version `0.17.37`: LPR-test-sidan kan nu hämta en REN bild (utan boxar/linjer) från vald kamera via "📷 Hämta ren bild" (`/api/live/{cam}/snapshot.jpg?clean=1`), så OCR:en inte störs av överlagringar från en dashboard-skärmdump.
- Version `0.17.36`: LPR-skyltläsning fixad för sub-strömmar. YOLO-boxen paddas nu (extra nedåt) så skylten inte klipps av, och vid behov beskärs den undre/centrala skyltzonen. Uppskalning upp till 4×.
- Version `0.17.35`: ny LPR-testsida (flik "🔎 LPR-test") + `POST /api/lpr/test`. Robustare skyltläsning: multi-scale-uppskalning (2×/3×) och lägre standard-min-konfidens (0.45 → 0.30) så skyltar på 640×360 sub-strömmen läses. README-fix av LPR-installkommandona (`\.venv` → `.\venv`).
- Version `0.17.34`: LPR-downloadknappen borttagen. README.md beskriver nu manuell installation i projektets `.venv`; GUI:t visar endast om EasyOCR/PaddleOCR är installerad eller saknas.
- Version `0.17.33`: LPR-installationen använder nu `pip --user` när appen körs med system-Python, vilket undviker Windows Access Denied mot skyddad system-`site-packages`. Virtuella miljöer använder fortsatt vanlig pip-installation.
- Version `0.17.32`: LPR-installationen visar nu tydliga faser (`download`, `install`, `complete`, `error`) och felkod i GUI:t i stället för en generell “installerar”-text.
- Version `0.17.31`: LPR-installationsknappen kontrollerar nu först om vald OCR-motor redan finns. EasyOCR visar direkt klar/installerad i stället för att starta en ny pip-installation.
- Version `0.17.30`: LPR visar nu installeringsstatus för EasyOCR och PaddleOCR/PaddlePaddle direkt i Inställningar, inklusive saknas/installerad och pågående installationsstatus.
- Version `0.17.29`: pixel-gaten använder nu även lokal rörelse, så mindre objekt som personer inte filtreras bort bara för att de ändrar färre pixlar än en bil. Global rörelse och zonmaskering behålls.
- Version `0.17.28`: LPR-sektionen har nu knappar för att installera vald OCR-motor från GUI:t. EasyOCR installeras separat; PaddleOCR installerar både `paddleocr` och `paddlepaddle`. Installationen sker i bakgrunden och LPR aktiveras inte automatiskt.
- Version `0.17.27`: valbart GUI-skydd under Inställningar → GUI-skydd med Basic Auth och PBKDF2-hashat lösenord. Skyddar GUI, API, snapshots och livebilder. HACS config flow kan spara samma credentials och skickar dem på alla API-anrop. Avstängt som standard.
- Version `0.17.26`: watchdogen räknar nu en färsk pixel-gate-kontroll som AI-aktivitet. Stillbild när pixel-gaten är aktiv startar därför inte om tjänsten felaktigt efter 90 sekunder; utan gate krävs fortsatt YOLO-inferens som tidigare.
- Version `0.17.25`: sparade Historik-/HA-eventbilder använder nu råbild utan YOLO-boxar, detektionslinjer eller zonöverlägg. Livebilden påverkas inte.
- Version `0.17.24`: mobil-dashboardens System/Runtime- och GPU-kort ligger nu i samma fulla bredd som Detected now.
- Version `0.17.23`: separat LPR-historik med registreringsnummer, kamera, tid, confidence och snapshot. Sparas i `data/lpr.json` och visas under Historik.
- Version `0.17.22`: egen LPR-sektion i Inställningar med val mellan EasyOCR och PaddleOCR. Motorn laddas först när LPR aktiveras; vanlig YOLO påverkas inte när LPR är av.
- Version `0.17.21`: valbar LPR-prototyp med EasyOCR på filtrerade fordonsrutor. Registreringsnummer visas i live-detektioner och skickas vidare som attribut i HA-resultat. Avstängd som standard; aktiveras via Inställningar → Live-detektering eller `LPR_ENABLED=true`.
- Version `0.17.20`: tydligare mobil-dashboard med kompakt header, svepbara flikar, större touchytor, fullbredds-livebild och mindre statusbrus på små skärmar.
- Version `0.17.19`: Dashboard v2 med bättre mobil layout, snabbstatus för kamera/YOLO/detektion, fullskärmsknapp för livebild och mer kompakt status på små skärmar. Layouten är scoped till `dashboard-v2` så den gamla dashboard-layouten kan återställas enkelt.
- Version `0.17.18`: pixel-gaten kalibrerar automatiskt bakgrundsbrus under 10 sekunder efter start/reconnect. Den effektiva tröskeln blir minst användarens val och höjs vid behov till cirka tre gånger uppmätt bakgrundsrörelse; det sparade värdet ändras inte.
- Version `0.17.17`: pixel-gaten respekterar röda maskzoner före YOLO och har en fem sekunders startgate efter start/reconnect så kamerans första bildflöde inte blockeras av gate-logiken.
- Version `0.17.16`: pixel-gate-fix. Referensbilderna nollställs vid RTSP-reconnect så första bilden från en ny stream inte jämförs med föregående stream. Ogiltig känslighet faller tillbaka till 5, och standarden sänks från 10 till 5 för att inte filtrera bort små/lokala rörelser.
- Version `0.17.15`: lägsta konfidens för Historik/HA-händelser (`events.min_conf` / `LIVE_EVENT_MIN_CONF`, default 0.6, 0–1). En svag gissning (t.ex. "bird 55 %" på ett litet avlägset djur) skapar inte längre en händelserad – bara detektioner med konfidens ≥ tröskeln räknas som "närvarande" av eventtrackern och hamnar i Historik/sammanfattning. Live-boxarna (överlägget) ändras inte – tröskeln gäller bara event. GUI: Inställningar → HA-event → "Lägsta konfidens för händelse (%)". Fälten: `_eval_events` (present + ev_dets filtreras med `min_conf`), `_event_defaults`, `status().event_min_conf`, `/api/settings` (GET/PUT), `example.env`.

## 2026-09-07
- Version `0.17.14`: ?-hjälpknapp vid "Rörelsekänslighet" (Inställningar → Live-detektering) som visar guiden (1–5 / 8–15 sweet spot / 15–25 / >30) i en popover. Stängs genom att klicka utanför eller på knappen igen.
- Version `0.17.13`: live pixel-rörelsemätare under känslighetsslidern. Servern mäter alltid en billig 128×72-pixeländring (`_motion_preview`, `status().motion_diff`) och Inställningar → Live-detektering visar "Rörelse nu: X · tröskel: Y" som uppdateras varje statuspoll och direkt när slidern dras (`updateDetGateLive`). Man ser alltså live om vald känslighet skulle utlösa YOLO innan man trycker Spara.
- Version `0.17.12`: pixel-motion-gate (av/på, av som standard) + ihopfällbara sektioner i Inställningar.
  - Pixel-gate (Inställningar → Live-detektering → "Pixel-gate – kör YOLO bara vid rörelse"): när på hoppar YOLO över bilder som inte ändrats (nedskalad gråbild jämförs mot referens, "rörelsekänslighet" = tröskel). Mindre GPU-last och färre falsklarm från skuggor/träd. Av som standard. Config `MOTION_GATE_ENABLED`/`MOTION_GATE_THRESHOLD`; `_gate_motion` i camera_stream.
  - Inställningar: varje kort fälls ihop/öppnas genom att klicka på rubrikraden (chevron) – läget sparas per sektion i webbläsaren (localStorage). `makeSettingsCollapsible` i app.js + `.settings-card-head`/`.card-collapse` i style.css.
- Version `0.17.11`: objektfilter, AI-watchdog och auto-städning av eventbilder.
  - Objektfilter (Inställningar → Live-detektering): extra lägsta konfidens, min/max-storlek (% av bildytan) och klass-specifik konfidens (t.ex. `car=0.6, person=0.5`) för att filtrera bort osäkra/pyttelika/enorma träffar (Frigate-style). `camera_stream._apply_obj_filters` + config `CAMERA_FILTER_MIN_SCORE/MIN_AREA/MAX_AREA/CLASS_SCORES`.
  - AI-watchdog: om YOLO-inferensen hänger (ingen ny inferens på 90 s, 3 kontroller) startas kameraworkern om automatiskt (cooldown 10 min, max 3 ggr/30 min innan den ber om tjänsteomstart). `_watchdog_loop`/`_start_watchdog` i camera_stream.
  - Media-städning: `media/event_*.jpg` som inte längre refereras av eventloggen (max 50 event) raderas vid start och efter varje nytt event (`_prune_event_media`).
- Version `0.17.10`: Historik/eventlistan slutar skapa nya rader för samma stillastående objekt vid längre flimmer. `_event_locations_suppress` håller reda på var varje klass nyligen larmats (fönster = max 60 s, `clear_after` × 10) och undertrycker återlarm när objektet bara dyker upp igen på samma plats. Ny plats/ny ankomst larmar fortfarande.
- Version `0.17.9`: Motion slutar trigga på parkerade bilar. `_mark_moving` fick ett tidsminne (`_motion_history`, fönster = eventens `clear_after`): ett objekt räknas som i rörelse bara om inget tidigare objekt av samma klass setts nära samma position nyligen - en parkerad bil som flimrar ur detektionen en bildruta räknas inte längre som rörelse (jämför Frigates stationära objekt).
- Version `0.17.8`: sök/filtrera i Historik (bil, person, djur, kamera…) och cache-busting av statiska filer så eventbilderna även dyker upp i telefonens webbläsare.
- Historik: sökfält filtrerar HA-eventen direkt på kamera, klasser, detektioner och sammanfattning (flera ord = alla måste matcha).
- Eventbilder på telefon: index.html hämtas nu via servern som ersätter `__VER__` med `config.VERSION`, så CSS/JS-URL:er får `?v=<version>` och telefonen inte längre visar gammal cachad kod utan bilder.
- Version `0.17.7`: robustare eventbilder med rå-JPEG-fallback och synlig felorsak i Historik.
- Eventbilder: lägger till rå-JPEG-fallback och visar orsaken i Historik om snapshot ändå saknas.
- Version `0.17.6`: synkar serverns GUI/API-version med HACS-integrationen och innehåller eventbildfixarna.
- Eventbilder: säkerställer att bekräftade HA-event får en JPEG även när annoteringen saknas, med råbild som fallback.
- Eventhistorik: eventet sparas även om snapshot-filen inte kunde skapas.
- Eventhistorik: visar en liten annoterad bild från detektionstillfället när ett nytt live-event skapas.
- Event-API:et exponerar sparade eventbilder som säkra `/media/...`-URL:er.

## 2026-09-04
- HACS v0.17.6: Motion-entiteten uppdaterad till rörelsebaserad status för människor, djur och fordon.
- HACS: Motion räknar nu faktisk förflyttning av människor, djur och fordon mellan bildrutor; närvaroräknarna är oförändrade.
- Kamerastatus: Dashboard visar nu ålder på senaste bild och YOLO-körning samt reconnect-antal/tid per kamera.
- Eventhistorik: Android-vyn visar laddnings-/felstatus, senaste uppdatering och uppdateras automatiskt när Historik är öppen.
- Eventhistorik: stabila event-ID:n, trådsäker åtkomst och atomisk filskrivning minskar risken för korrupt historik.
- Home Assistant: nya sensorer visar antal event senaste timmen och senaste eventets sammanfattning.
- Mobilvy: kamerastatusen visas som lättlästa kort på små skärmar.
- Tester: grundtester för event-API:ts sortering, limit och cache-headrar tillagda.
- Eventhistorik: Android-refresh tvingar nu fram aktuella event genom att kringgå klient- och servercache.
- Version `0.17.5`: beständig logg för de 50 senaste HA-detektionseventen med kamera, tid, klasser och sammanfattning.
- HA-eventlogg: sparar de senaste 50 live-detektionerna i `data/events.json` och visar dem under Historik.
- Version `0.17.4`: visar tydliga `ZON 1`, `ZON 2`-etiketter i rutornas övre vänstra hörn och under pågående dragning.
- Version `0.17.3`: tydligare zonnummer direkt på kamerabilden.
- Version `0.17.2`: numrerade och färgkodade zonmarkörer i mobilredigeraren.
- Version `0.17.1`: tar bort den flytande zonkontrollen från bildytan helt.
- Mobil zonredigering: zonens typväljare och borttagningsknapp visas under kamerabilden så att polygonhörn inte täcks.
- Desktopläget behåller zonens snabbkontroller ovanpå förhandsvisningen.
- Zonens flytande kontrollbox tas bort helt från bildytan; zonlistan under bilden används på alla skärmstorlekar.
- Zoner numreras visuellt på bilden och med matchande färgkodade rader under bilden för enklare mobilredigering.
- Zonnumren ritas nu som tydliga SVG-markörer i samma lager som polygonerna, med bättre kontrast.
