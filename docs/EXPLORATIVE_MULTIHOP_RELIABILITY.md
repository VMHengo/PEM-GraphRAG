# Exploratives Multi-Hop-Retrieval: Faehigkeiten und Zuverlaessigkeit

Stand: 2026-10-25. Diese Einschaetzung basiert auf dem lokalen Code und den
besprochenen Staging-Ergebnissen, nicht auf einer neuen Messung des laufenden
Servers.

## Ziel und aktueller Stand

Das Produkt soll bisher unbekannte, fachlich interessante Verbindungen zwischen
zwei oder mehr Batterie-Engineering-Themen sichtbar machen. Ein gefundener Pfad
soll eine **pruefbare Hypothese mit Quellen** sein, keine automatisch bewiesene
Kausalbehauptung. Gerade eine Kette aus vier oder fuenf Kanten kann ueber
Dokument-, Prozess- und Versuchsgrenzen hinweg plausibel aussehen, obwohl ihre
Glieder unter unterschiedlichen Bedingungen gelten.

Der aktuelle Code kann gerichtete Pfade mit `hop_depth` von 1 bis 5 suchen.
Standard ist jedoch `retrieval_strategy="normal"` und `hop_depth=2`;
`directed`, `combined` und `auto` sind optionale Strategien. Die Pfadsuche
benutzt semantische Endpunkte und eine begrenzte, gerankte Breitensuche. Nur
Pfade mit aufloesbaren Quell-Chunks gelangen in den gerichteten Antwortkontext.
Die normale Suche kann weiterhin Originaltext beisteuern. Siehe
[`lightrag/base.py`](../lightrag/base.py),
[`lightrag/directed_retrieval.py`](../lightrag/directed_retrieval.py) und
[`lightrag/operate.py`](../lightrag/operate.py).

**Einschaetzung:** Das System ist bereits fuer die *explorative Entdeckung von
Pfadkandidaten* brauchbar. Im isolierten synthetischen Stresstest wurde eine
viergliedrige Kette vollstaendig extrahiert. Das beweist weder die Auffindbarkeit
derselben Kette unter vielen konkurrierenden Kanten noch verlaessliche
Vier- oder Fuenf-Hop-Antworten aus realen PDFs. Im selben Test wurden auch
Vorzeichen vertauscht und unbelegte Ursachen erzeugt. Eine gefundene Kette
braucht deshalb derzeit eine fachliche Sichtpruefung jedes Hops.

## Wo Informationen verloren gehen oder Fehler entstehen

| Stufe | Typischer Verlust oder Fehler | Folge fuer eine lange Kette |
| --- | --- | --- |
| PDF-Parsing | Spalten, Tabellen, Formeln, Bildunterschriften, Einheiten oder Negationen werden falsch gelesen oder nicht als Text erfasst. | Eine Bedingung oder ein ganzes Glied fehlt bereits vor der Extraktion. |
| Chunking | Ein Mechanismus wird an einer Chunk-Grenze getrennt; Verweise wie "this" verlieren ihren Bezug. | Die naechste Kante wird ausgelassen oder dem falschen Subjekt zugeordnet. |
| LLM-Extraktion | Das Modell waehlt Entitaetsgrenzen und Praedikate, vereinfacht `decreases` zu `affects`, deutet Mehrdeutigkeit als Ursache oder verkehrt ein Vorzeichen. | Ein technisch falscher Hop wird als explizite Graph-Aussage gespeichert. |
| Normalisierung und Merge | Varianten werden getrennt gehalten oder verschiedene Begriffe zu frueh vereinigt. Zusammenfuehrung verdichtet Beschreibungen und Provenienz. | Echte Anschluesse fehlen; falsche Anschluesse entstehen. |
| Graphspeicherung | Der Graph behaelt strukturierte Aussagen und Quellen-IDs, aber nicht den gesamten sprachlichen und experimentellen Kontext in jeder Kante. Physische Neo4j-Kanten werden nach Knotenpaar gemergt; mehrere Assertions brauchen gesonderte Behandlung. | Bedingung, Geltungsbereich oder konkurrierende Aussage koennen beim Pfadbau uebersehen werden. |
| Ankerwahl und Retrieval | Embeddings, Keywords, Query-Routing, Relationstyp-Filter, Fanout-, Beam- und Token-Limits bestimmen, was ueberhaupt betrachtet wird. | Eine vorhandene richtige Kette wird nicht gefunden oder durch eine kuerzere, schwach belegte Kette verdraengt. |
| Kontextaufbereitung und Antwort-LLM | Ausgewaehlte Pfade und Quell-Chunks werden erneut gekuerzt und sprachlich zusammengefasst. Das Modell kann Luecken unbemerkt ueberbruecken. | Eine Antwort klingt sicherer und kausaler, als es die Belege erlauben. |

Die Stufen sind nicht einfach eine Folge identischer "LLM-Fehler": Parser,
Speicherung und deterministisches Ranking haben andere Fehlermuster. Auch
komprimiert der Graph **nicht die einzige erhaltene Information**: Text-Chunks
bleiben fuer normales beziehungsweise kombiniertes Retrieval verfuegbar.
Dennoch kann die gerichtete Pfadsuche nur mit den Aussagen und Ankern arbeiten,
die nach Extraktion und Merge noch erreichbar sind.

Eine oft genutzte Illustration lautet: Wenn jede Kante unabhaengig mit
Wahrscheinlichkeit 0,9 korrekt waere, haetten fuenf korrekte Kanten zusammen
eine Wahrscheinlichkeit von `0,9^5 = 0,59049`. Das ist **keine Messung dieses
Systems**. Fehler koennen korreliert sein, ein Dokument kann mehrere Glieder
gemeinsam stuetzen, und Retrieval- sowie Antwortfehler kommen zusaetzlich
hinzu. Fuer reale Qualitaet muessen vollstaendige Pfade gemessen werden.

## Kausalitaet ist mehr als ein gerichteter Pfad

`A -> B -> C` ist syntaktisch ein Pfad, aber nicht automatisch eine gueltige
Erklaerung. Fuer jedes Glied muss geprueft werden:

- Ist die Richtung belegt, und ist `causes` wirklich gemeint oder nur
  Assoziation, Messung, Zusammensetzung oder zeitliche Reihenfolge?
- Stimmen Vorzeichen, Einheit, Material, Zellchemie, Temperatur, Betriebszustand
  und Zeitpunkt entlang der gesamten Kette ueberein?
- Stammt die Aussage aus dem aktuellen Versuch, Hintergrundliteratur oder einer
  Hypothese? Ist sie negiert, eingeschraenkt oder umstritten?
- Fuehrt der Pfad ueber dieselbe fachliche Bedeutung eines Knotens, oder nur
  ueber gleich benannte Begriffe?

Ein `relation_importance`-Wert misst keine kalibrierte Wahrheit. Mehrere hohe
Kantengewichte lassen sich daher nicht ohne Weiteres zu einer
"Wahrscheinlichkeit der Gesamtkette" multiplizieren. Ein guter explorativer
Output zeigt den Pfad, jede Kantenbehauptung, ihre genaue Quelle und offene
Bedingungen; er kann auch "kein ausreichend belegter Pfad" melden.

## Warum die bisherigen Scores die Frage nicht entscheiden

Der UI-Graph-Score bewertet vor allem, ob vorgegebene Entitaeten und Relationen
gefunden wurden, teils mit semantischen Teilpunkten. Er ist kein vollstaendiger
Praezisionswert fuer **alle zusaetzlich erzeugten Kanten**. Metadata Coverage
prueft Feldbelegung, nicht fachliche Richtigkeit. Der strikte Artefakt-Audit
war umgekehrt bei Namensvarianten zu hart. In einem Staging-Stresstest wurden
alle vier Kanten einer synthetischen Kette erkannt, zugleich aber drei
vorab definierte verbotene Kanten gefunden. Weder der hohe UI-Wert noch die
niedrige rohe Exact-Match-Quote beschreibt allein diese Situation. Siehe
[`evaluation/benchmarks/pem_extraction_stress_v1.json`](../evaluation/benchmarks/pem_extraction_stress_v1.json)
und [`scripts/evaluate_extraction_stress.py`](../scripts/evaluate_extraction_stress.py).

Fuer das Produktziel sollten getrennt und auf einem **eingefrorenen,
versionierten Testset** gemessen werden:

1. **Extraktion:** Recall der belegten Gold-Kanten, Praezision einer manuell
   geprueften Stichprobe *aller* extrahierten Kanten, Richtungs-, Vorzeichen-
   und Konditionsfehler. Explizite, gepruefte Aliase zaehlen; Widersprueche nicht.
2. **Graphabdeckung:** Anteil der Goldketten, deren saemtliche Glieder nach
   Normalisierung und Speicherung im Graphen vorhanden und verbunden sind.
3. **Retrieval:** Anteil vorhandener Goldketten, die als Top-k-Pfad erscheinen,
   nach Hopzahl getrennt. Auch mit einem Oracle-Graphen testen: So werden
   Extraktions- und Suchfehler voneinander getrennt.
4. **Antwort:** Korrektheit, Vollstaendigkeit, Belegdeckung, unbelegte
   Schlussfolgerungen und angemessenes Abstinieren; gegen `normal` und
   `combined` vergleichen.
5. **Explorationsnutzen:** Fachleute beurteilen blind, ob zuvor unbekannte
   Pfade relevant, neu, nachvollziehbar und experimentell/praktisch
   weiterverfolgbar sind. Das ist ein anderes Ziel als reine Gold-Antwortquote.

Scorer-Version und Goldlabels nicht nach jedem Run verschieben, um eine
gewollte Zahl zu erhalten. Wenn ein Label nach fachlicher Pruefung falsch ist,
die Korrektur dokumentieren und **alle Vergleichsartefakte mit derselben neuen
Version erneut bewerten**. Sonst sind Vorher/Nachher-Scores nicht vergleichbar.

## Naechste technische Prioritaet

Zuerst die bereits vorliegenden Extraktionsartefakte ohne weitere Modellkosten
fallweise auditieren: Namens-Mismatch von echter Falschaussage trennen,
Vorzeichen und Mehrdeutigkeit absichern, Quellbelege pro Assertion pruefen.
Danach mit denselben Dokumenten testen, ob Goldketten im Graphen vorhanden,
im Top-k auffindbar und in der Antwort korrekt erklaert sind. Pfadpruning oder
graphkonformes Reasoning kann das *Retrieval und die Darstellung* verbessern,
aber keine falsch extrahierte Kante nachtraeglich wahr machen.
