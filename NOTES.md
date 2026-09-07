# Ändringsnoteringar

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
