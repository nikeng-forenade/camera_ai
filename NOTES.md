# Ändringsnoteringar

## 2026-09-04
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
