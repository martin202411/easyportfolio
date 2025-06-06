easyportfolio Version 0.2

--- TERMINALBEFEHLE ---

venv aktivieren:
source venv/bin/activate
oder:
source /opt/easyportfolio_django_app/venv/bin/activate

Server starten:
python manage.py runserver
python manage.py runserver 0.0.0.0:8000


Startseite:
http://152.53.93.102:8000/portfolio/

Anmeldung:
martin
Server2025//


--- LOGS ---

Logs leeren:
sudo truncate -s 0 /opt/easyportfolio_django_app/logs/qcluster_error.log


--- STREAMLIT ---

Streamlit Neustart:
sudo systemctl restart streamlit_easyportfolio.service

Status prüfen:
sudo systemctl status streamlit_easyportfolio.service

Log Journal:
journalctl -u streamlit_easyportfolio.service -f


--- IMPORTJOBS AUSFÜHREN ---

Aktienkurse holen und aktualisieren
/opt/easyportfolio-streamlit/venv/bin/python data/import_prices.py

Wechselkurse holen und aktualisieren


--- CRON JOBS ---

Anzeigen:
sudo crontab -l

Bearbeiten:
sudo crontab -e


--- SQL Befehle ---

Tabellen anzeigen
SHOW TABLES;

Struktur der Tabelle anzeigen
SHOW CREATE TABLE wp_portf_historical_prices;


--- GITHUB ---

Auf GitHub speichern
git add .
git commit -m "Eine aussagekräftige Nachricht, was ich gemacht habe"

Auf GitHub übertragen
git push origin main

Von GitHub übernehmen
git pull origin main


BERECHNUNG VON WP PORTFOLIOS
Die Berechnung der Portfolio-Performance zielt darauf ab, die historische Wertentwicklung eines Portfolios
so realitätsnah wie möglich abzubilden. Eine besondere Herausforderung stellen dabei Wertpapiere innerhalb
des Portfolios dar, die zu unterschiedlichen Zeitpunkten mit der Datenlieferung beginnen oder temporäre
Lücken in ihren Kursdaten aufweisen. Die hier implementierte Logik stellt sicher, dass das
Portfolio-Ergebnis die tatsächliche Performance der jeweils aktiven und handelbaren Komponenten
widerspiegelt, gewichtet nach ihren relativen Zielgewichten.

Kernprinzip der dynamischen Gewichtung bei unterschiedlichen Startdaten:
Wenn ein Portfolio z.B. aus Wertpapier A (Zielgewicht 50%) und Wertpapier B (Zielgewicht 50%) besteht:

Solange nur Wertpapier A Kursdaten liefert, verhält sich das Portfolio zu 100% wie Wertpapier A (da WP A das einzige aktive Asset ist und somit temporär das gesamte für A&B vorgesehene Kapital bindet).
Sobald Wertpapier B ebenfalls Kursdaten liefert, wird die Performance des Portfolios ab diesem Zeitpunkt zu 50% von der Rendite von WP A und zu 50% von der Rendite von WP B bestimmt.
Schritte der Berechnungslogik:

Datenerfassung und -vorbereitung:

Identifikation der Bestandteile: Für jedes zu analysierende Portfolio werden alle Wertpapiere (security_id) und deren Zielgewichtungen (target_weight als Dezimalzahl, z.B. 0.5 für 50%) aus der Datenbank geladen.
Kursdatenabruf: Für alle relevanten Wertpapiere (aus den ausgewählten Portfolios, einzeln ausgewählte Wertpapiere und der Benchmark) werden die historischen Kurse (üblicherweise adj_close_price) für den vom Benutzer definierten Analysezeitraum abgerufen.
Erstellung eines Preis-DataFrames: Die abgerufenen Kurse werden in einem Pandas DataFrame zusammengeführt. Der Index dieses DataFrames ist das price_date, die Spalten sind die security_ids, und die Zellen enthalten die jeweiligen Kurse.
Sicherstellung eines kontinuierlichen Zeitindex: Der DataFrame wird auf einen kontinuierlichen Index von Geschäftstagen (freq='B') für den gesamten Analysezeitraum erweitert (reindex).
Umgang mit fehlenden Kursen (Lückenfüllung): Fehlende Kurswerte in diesem DataFrame werden per ffill() (forward fill) aufgefüllt. Das bedeutet:
Wenn ein Wertpapier nach seinem ersten Kurseintrag temporär keine Daten liefert (z.B. Handelsaussetzung, Wochenende, Feiertag), wird der letzte bekannte Kurs fortgeschrieben. Für die Renditenberechnung bedeutet das an diesen Tagen eine Rendite von 0 für dieses WP.
Wertpapiere, die erst später im Analysezeitraum starten, haben anfangs NaN-Werte. Diese bleiben nach ffill() erstmal NaN.
Berechnung der täglichen Renditen:

Für jedes Wertpapier im prices_df werden die täglichen prozentualen Renditen berechnet: daily_returns_df = prices_df.pct_change().
Die erste Zeile dieses daily_returns_df enthält für jedes Wertpapier NaN, da für den ersten Kurstag keine Vorperiode zur Renditeberechnung existiert. Auch Wertpapiere, die erst später starten, haben anfangs NaN-Renditen.
Iterative Berechnung der täglichen Portfoliorendite (für jedes ausgewählte Portfolio):

Für jeden Handelstag t im Index des daily_returns_df
(beginnend mit dem zweiten Tag, da der erste Tag NaN-Renditen hat):
a. Aktive Wertpapiere des Portfolios an Tag t:
Es werden diejenigen Wertpapiere identifiziert,
die * Teil des aktuellen Portfolios sind
(d.h., ein Zielgewicht > 0 haben).
* An Tag t eine gültige (nicht-NaN) Rendite im daily_returns_df aufweisen.
b. Keine aktiven Wertpapiere: Wenn für ein Portfolio an einem Tag keine
seiner Komponenten eine gültige Rendite liefert,
wird die Portfoliorendite für diesen Tag auf 0.0 gesetzt.
c. Aktive Wertpapiere vorhanden: i. Zielgewichte der Aktiven:
Es werden nur die Zielgewichte der an diesem Tag aktiven Wertpapiere betrachtet.
ii. Dynamische Normalisierung der Gewichte:
Die Summe dieser Zielgewichte der aktiven Komponenten wird berechnet.
Jedes einzelne dieser aktiven Zielgewichte wird dann durch diese Summe geteilt.
Das Ergebnis sind die effektiven, normalisierten Tagesgewichte, deren Summe 1.0 ergibt.
(Beispiel: Ziel A=0.5, B=0.5. Nur A aktiv -> effektives Gewicht A=1.0. A&B aktiv -> A=0.5, B=0.5).
iii. Gewichtete Tagesrendite des Portfolios: Die Rendite jedes aktiven Wertpapiers
an Tag t wird mit seinem gerade berechneten, normalisierten Tagesgewicht multipliziert.
Die Summe dieser Produkte ergibt die Tagesrendite des Portfolios.
R Portfolio,t = ∑ i∈AktiveWPs t(w norm,i,t ⋅ R i,t)
d. Die berechnete portfolio_return_today wird gespeichert.
Erstellung der Portfolio-Renditezeitreihe:

Aus den gesammelten täglichen Portfoliorenditen wird eine Pandas Series (portfolio_daily_returns_series) erstellt.
Eventuelle NaN-Werte in dieser Serie (falls z.B. an einem Tag alle aktiven WPs eine NaN-Rendite hatten, was durch dropna() in Schritt 3a eigentlich vermieden werden sollte) werden mit 0.0 gefüllt.
Indexierung der Performance-Zeitreihen (für Portfolios, einzelne WPs, Benchmark):

Jede zu plottende Zeitreihe (egal ob Portfolio, einzelnes WP oder Benchmark) wird auf einen Startwert von 100 indexiert, um Vergleichbarkeit herzustellen.
Basis für Indexierung: Die Indexierung startet an dem Tag, an dem die jeweilige Zeitreihe ihren ersten gültigen (nicht-NaN) Renditewert hat innerhalb des vom Benutzer gewählten Analysezeitraums.
Um einen korrekten Start des kumulativen Produkts bei 100 zu gewährleisten, wird der allerersten Rendite in der (für die cumprod-Berechnung vorbereiteten) Serie ein Wert von 0.0 zugewiesen (oft durch Einfügen eines "Tag 0" mit Rendite 0 und Wert 100 für die Basis).
Berechnung: indexed_performance = (1 + portfolio_daily_returns_series).cumprod() * 100.
Der erste Wert der indexed_performance-Serie wird explizit auf 100.0 gesetzt.
Eventuelle verbleibende NaN-Werte nach dem Start der Indexierung werden per ffill() aufgefüllt.
Die Werte werden auf eine sinnvolle Anzahl von Nachkommastellen gerundet (z.B. 4).
Vorbereitung für die Chart-Darstellung (JSON):

Die Daten (Datumspunkte und indexierte Werte) jeder Zeitreihe werden in ein für Plotly
js passendes JSON-Format gebracht. Dieses beinhaltet typischerweise Listen für dates und values,
sowie series_name, line_color, dash_style (für Benchmark) und die berechneten kpis.
Kennzahlen-Berechnung (KPIs):

Für jede erzeugte indexierte Performance-Zeitreihe (sei es ein Portfolio, ein einzelnes WP oder der Benchmark) wird ein separater DataFrame im Format {'datum': series.index, 'close': series.values} erstellt.
Dieser DataFrame wird an die Funktion calculate_all_kpis(kpi_input_df) aus dem Modul kpi_calculator.py übergeben.
Das Ergebnis ist ein Dictionary mit Kennzahlen (z.B. Gesamtrendite, CAGR, Volatilität p.a., Sharpe Ratio p.a., Max Drawdown), das zusammen mit den Chartdaten an das Frontend gesendet wird.


Verwendete Technologien/Bibliotheken:
Backend: Django, Python, Pandas, NumPy, SQLAlchemy (falls du die DB-Schicht aus Streamlit wiederverwendest oder eine ähnliche Abstraktion baust).
Frontend: HTML, CSS, JavaScript, Bootstrap, Plotly.js, Choices.js.
Datenbank: MariaDB

Datenquellen:
EODHD API für Kursdaten (OHLCV), Dividenden, Splits und Wertpapier-Stammdaten
(Geplant: Alpha Vantage für FX, yfinance für Fundamentaldaten)

Kernfunktionalitäten (kurze Stichpunkte):
Datenimport und -aktualisierung via EODHD.
Wertpapier-Stammdatenverwaltung.
Portfolio-Erstellung und -Management mit Zielgewichtungen.
Einzelwertpapieranalyse mit Charts und Filtern.
Expertenportfolio-Ansicht mit Vergleichs-Charts (Einzel-WPs, Portfolios, Benchmarks) und KPI-Anzeige.
Dynamische Portfolio-Performance-Berechnung (wie oben detailliert).
Interaktive Charts mit Zoom (Range Slider) und Re-Base-Funktion

Datenaufbereitung für Charts:
Verwendung von adj_close_price für Performanceberechnungen und Indexierung.
Umgang mit NaN-Werten durch ffill() und bfill() (je nach Kontext).

Wichtigkeit der Datenqualität:
Betonen, dass die Qualität der Analyse stark von der Qualität und Vollständigkeit der zugrundeliegenden
Kursdaten abhängt.

Handhabung von Kapitalmaßnahmen:
Verwendung von adj_close_price von EODHD, die bereits um Dividenden und Splits bereinigt sein sollten.
Zusätzliches Laden und Speichern von Split-Daten aus EODHD (für eventuelle manuelle Anpassungen oder
detailliertere Analysen, die nicht allein auf adj_close basieren).
