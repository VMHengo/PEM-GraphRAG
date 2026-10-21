# PEM GraphRAG: Forschungsstand und Verbesserungsplan

Stand: 2026-10-19. Analysierter Code: `2b146577` auf
`feature/azure-batch-extraction`. Dieses Dokument plant Verbesserungen;
die beschriebenen Erweiterungen sind noch nicht implementiert. Der
Batch-Teil von P0 wurde danach lokal umgesetzt und getestet; die Abschnitte
zu normalem Provider, Retry, idempotentem Merge und alle weiteren Pakete
bleiben geplant.

## 1. Entscheidung und Lesepfad

Die bestehende Codebasis weiterentwickeln. Sie hat bereits die benoetigten
Eintrittspunkte fuer isolierte Prompt-Vergleiche, erneute Extraktion,
gerichtete Pfade, Quellenbelege und versionierte Benchmarks. Ein Austausch
des Frameworks wuerde diese Funktionen erneut erfordern und behebt die
beobachteten Verluste beim Import nicht automatisch.

Empfohlene Reihenfolge:

1. Vollstaendigkeit von Extraktionsantworten und korrekte Herkunft absichern.
2. Fachliche Qualitaet von Extraktion, Retrieval und Antworten getrennt messen.
3. Prompt, Relationstypen und Kontextbehandlung gemeinsam verbessern.
4. Mehrere Aussagen zwischen denselben Entitaeten verlustfrei erhalten.
5. Ankerwahl, Pfadrelevanz und belegte Antwortgenerierung verbessern.
6. Erst danach vier und fuenf Hops und aufwendigere Lernverfahren bewerten.

Lesepfad: [Architektur](PEM-GRAPHRAG-ARCHITECTURE.md),
[Code-Aenderungsstellen](PIPELINE_CHANGE_GUIDE.md),
[Bewertung](BENCHMARK_SCORING.md),
[fruehere reale Benchmark-Diagnose](BENCHMARK_REVIEW_2026-10-16.md).

## 2. Untersuchungsumfang und Aussagekraft

Geprueft wurden die lokalen Implementierungen in `pipeline.py`, `operate.py`,
`adaptive_retrieval.py`, `directed_retrieval.py`, `relation_ontology.py`,
`api/azure_batch.py`, `extraction_revisions.py`, den Evaluation-Modulen,
`relation_identity.py`, Neo4j, MCP, den PEM-Prompt-Samples und den beiden
Supervisor-Prompts.
Ein fokussierter lokaler Testlauf bestand mit 112 Tests; die Dateiliste
steht in Abschnitt 12. Das ist eine Implementierungspruefung mit Mocks und
Fixtures, keine neue Messung der fachlichen Extraktionsqualitaet.

In dieser Untersuchung wurde kein VPS-Zustand neu ausgelesen. Die Zahlen aus
dem Bericht vom 16.10. sind historische Beobachtungen, keine Bestaetigung der
heutigen Staging-Umgebung. Modellnamen, Promptdateien und Umgebungsvariablen
im Repository beweisen nicht die aktive Serverkonfiguration.

Recherche: Primaerquellen, Autoren-Repositories, Originalarbeiten und
Modellkarten, abgerufen am 19.10.2026. Beruecksichtigt wurden auch 2026er
Arbeiten. Die Auswahl ist problemorientiert, keine vollstaendige systematische
Literaturuebersicht und kein Beleg fuer ein universell bestes Verfahren.
Fremde Ergebniszahlen sind ohne identisches Korpus, Goldstandard,
Antwortmodell und Bewertungsverfahren nicht mit unserem Overall vergleichbar.

## 3. Verifizierter Implementierungsstand

| Teil | Bereits vorhanden | Grenze / naechster Bedarf |
| --- | --- | --- |
| Ingestion | Chunk-first Upload, normale oder Azure-Batch-Extraktion; neue Batch-Jobs erhalten ein Submission-Manifest | Normalen Provider, Retry und idempotente Wiederaufnahme absichern |
| Parsing | Routing zu legacy/native/MinerU/Docling; Multimodalpfade | Qualitaet und Seitenbelege pro Dokument messen, nicht nur Parser-Erfolg |
| Chunks | Mehrere Strategien, ueblich 1200 Tokens und 100 Overlap | Das ist keine Garantie fuer geschlossene Mechanismen oder Provider-Tokenlimits |
| Extraktion | JSON und Legacy-Parser; Richtung, Predicate, Importance, Chain-Rolle | Zitatspannen, Bedingungen, Negation und Aussageart fehlen als verbindlicher Vertrag |
| Versionierung | Revision/Fingerprint, Re-extraktion mit erhaltenen Dokumenten/URLs/Chunks; neue Batch-Jobs speichern Submission-Revision und Hashes | Alte Jobs haben keinen nachtraeglich beweisbaren Snapshot |
| Prompt Experiments | Isolierte Kandidaten, Screening/Validation/Final, Artefakte, Promotion | Screening nimmt Anfangschunks; Kandidatengraph und Inputabdeckung koennen verzerren |
| Graph | Neo4j, semantische Endpunkte; gerichtete Vektor-/Chunk-Identitaet fuer neue Relationen | Physische Kante und Merge gruppieren weiter nach ungeordnetem Endpunktpaar |
| Routing | Deterministische DE/EN-Regeln; `normal`, `directed`, `combined`, `auto` | Statische Predicate-Listen und begrenzte Spracherkennung |
| Pfadsuche | Gebatchte Neo4j-Nachbarn, Beam-begrenzte BFS, Quellenaufloesung | 1-3 Hops; keine freie 5-Hop-Abfrage im oeffentlichen Vertrag |
| Pfadranking | Importance, Richtungsfaktor, Predicate-Bonus, Laengenabzug | Keine direkte Query-Pfad-Relevanz oder Bedingungskompatibilitaet |
| Antworten | Normaler Kontext und optional belegte Directed Evidence Paths | Graph-Beleg bedeutet noch keine wissenschaftlich richtige Aussage |
| Evaluation | Scoring 2.0.0, partielle/exakte Matches, History, getrennte UI-Tabs | Erwartete Entitaeten werden auf Abdeckung, nicht vollstaendige Precision geprueft |

Wichtig: `mode="global"` in diesem Fork sucht ueber Relationsvektoren und
Graphkontext. Der gepruefte Querypfad implementiert keine Microsoft-GraphRAG-
Pipeline mit Leiden-Community-Berichten und Map-Reduce ueber solche Berichte.

## 4. Konkrete Engpaesse im Code

### 4.1 Unvollstaendige Batch-Ausgaben konnten als Erfolg gelten

Bis zum P0-Teilupdate pruefte [`_parse_output_jsonl`](../lightrag/api/azure_batch.py)
nur `response.status_code == 200` und las danach den Text. Es prueft nun bei
neuen und alten Jobs Responses-`status`/`incomplete_details`, Refusals und
Chat-Completions-`finish_reason`; JSON-Batch-Ausgaben muessen ein Objekt mit
genau `entities` und `relationships` als Arrays sein. Vor dem Merge wird die
vollstaendige, eindeutige Menge erwarteter Chunk-IDs validiert. Neue Jobs
speichern auch Content-/Request-Hashes sowie den eingereichten
Extraktions-Snapshot. Bei einem Validierungsfehler wird der Grund persistent
gespeichert und kein Merge aufgerufen.

Der JSON-Parser in [`operate.py`](../lightrag/operate.py) verwendet
`json_repair`, und fehlende Arrays werden als leere Arrays behandelt.
Das kann ausserhalb dieses abgesicherten JSON-Batch-Pfads weiterhin
abgeschnittene Entitaetenlisten in scheinbar gueltige Teilresultate
verwandeln. `completed` am Batch-Job ist deshalb erst nach der lokalen
Zeilenvalidierung eine Garantie fuer eine vollstaendige Batch-Antwortmenge.

Der fruehere Staging-Bericht dokumentiert bei einem damaligen Ausgabelimit
von 1200 Tokens 10/10 beziehungsweise 60/74 unvollstaendige Antworten in zwei
Dokumenten. Ein neuer Prompt oder ein besserer Retriever kann diese beim
Import verlorenen Relationen nicht wiederherstellen. Das Limit ist eine
historische Serverbeobachtung; `_max_output_tokens()` hat im Code keinen
festen 1200er Default.

Alte Jobs ohne Manifest bleiben aus Kompatibilitaetsgruenden importierbar,
werden aber als Legacy-Fall protokolliert und koennen ihre eingereichten
Chunks nicht nachtraeglich per Hash beweisen. Der normale Provider verliert
Completion-Metadaten weiterhin frueh. Ein fehlerfreier Graph-Merge nach
Netzwerkabbruch ist noch nicht idempotent wiederaufnehmbar.

### 4.2 Aussageverlust beim Merge

`merge_nodes_and_edges()` bildet `tuple(sorted(edge_key))`.
`_merge_relationship_metadata()` uebernimmt die Metadaten des nach Importance
und optionaler Richtungskonfidenz staerksten Kandidaten. Neo4j verwendet
`MERGE (source)-[r:DIRECTED]-(target)` ohne Predicate-Identitaet.
Mehrere Predicates oder gegensaetzliche Aussagen zu demselben Paar werden
damit nicht als eigenstaendige Aussagen erhalten. Richtungssensitive
Vektor-IDs allein loesen das physische Speicherproblem nicht.

### 4.3 Extraktion und Retrieval verwenden nicht dieselbe Ontologie

Die kompakten Prompts nennen `increases`, `decreases` und `prevents`.
`CAUSAL_RELATIONS` in [`adaptive_retrieval.py`](../lightrag/adaptive_retrieval.py)
enthaelt diese Labels nicht. `select_directed_edges()` filtert bei einer
kausalen Route alle nicht zugelassenen Predicate heraus. Eine fachlich gute
extrahierte Kante kann dadurch fuer die Frage unsichtbar sein.

Der Provider `get_directed_neighbor_edges_batch()` sortiert Nachbarn vor der
semantischen Filterung nach Importance und schneidet die Kandidatenliste ab.
Viele hoch bewertete, aber unpassende Beziehungen koennen relevante
Kandidaten bereits vor der Python-Filterung verdraengen. Der Response-Limit
begrenzt ausserdem nicht zwingend den Neo4j-Aufwand: die Abfrage sammelt
zunaechst Nachbarn und schneidet danach ab.

### 4.4 Ranking und Messung beantworten unterschiedliche Fragen

`_directed_path_anchors()` nimmt hoechstens fuenf Entity-Suchergebnisse.
`_score_path()` nutzt den Mittelwert der Kantenscores minus Hop-Abzug.
Fehlende Anker, generische Knoten und eine starke Bevorzugung kurzer Pfade
koennen deshalb lange, relevante Mechanismen verdraengen.

`score_query_cases()` verwendet normale Retrieval-Strategie und prueft
`must_include` sowie erwartete Dokumente im Referenzsatz. Die getrennte
Directed-Auswertung prueft Pfaddiagnostik mit Kontextabruf. Das ist noch kein
Vergleich der fachlichen Antworten aller vier Strategien.
`expected_answer` und `unacceptable_claims` sind im aktuellen Live-Scorer
keine fachlichen Bewertungskriterien. Darum koennen richtige Stichwoerter
bei falscher mechanistischer Erklaerung einen hohen Retrieval-Score ergeben.

Die partielle Bewertung hat weitere Risiken: Teilmengen von Entity-Tokens
erhalten 0.85; `Current` und `Local Current Nonuniformity` sind deshalb nicht
automatisch fachlich gleich. Die Predicate-Familien geben z.B. `produces`,
`contains` und `part_of` untereinander 0.78. Das ist eine Diagnoseheuristik,
keine ontologische Gleichwertigkeit. Auch `increases` und `decreases`
duerfen fuer wissenschaftliche Aussagen nicht als gleicher Effekt gelten.

## 5. Was aktuelle Forschung fuer uns hergibt

### 5.1 Pfade und Anker

**PathRAG (2025; Autoren-Code):** Nutzt flussbasierte, distanzabhaengige
Auswahl relationaler Pfade und eine pfadweise Kontextdarstellung. Fuer uns
interessant sind Redundanzabbau, Pfad-Relevanz und ein festes Kontextbudget.
Die Arbeit misst unter anderem paarweise Antwortpraeferenzen, keine
allgemeine Genauigkeit fuenfstufiger Kausalketten. Flussscores sind
Rangsignale, keine kalibrierten Wahrheitswahrscheinlichkeiten. Prioritaet P2,
nach gesicherter Extraktion; die komplette Implementierung zu ersetzen ist
nicht erforderlich. [Paper](https://arxiv.org/abs/2502.14902),
[Methodendetails](https://arxiv.org/html/2502.14902v1),
[Autoren-Repository](https://github.com/BUPT-GAMMA/PathRAG).

**HippoRAG 2 (ICML 2025):** Verbindet Passagen enger mit dem Graphen und nutzt
Personalized PageRank sowie eine queryabhaengige Auswahl von Tripeln.
Die uebertragbare Idee ist, Passagen und Relationen bei der Ankerwahl
einzubeziehen. Ein vollstaendiger PageRank-Umbau ist fuer unsere
expliziten Kausalketten nicht der erste Schritt. PPR ueber assoziative
Verbindungen garantiert keine kausal korrekte Orientierung. Zunaechst
Query-zu-Entity/Relation-Relevanz als isolierte Ablation testen.
[Paper](https://proceedings.mlr.press/v267/gutierrez25a.html),
[Code](https://github.com/OSU-NLP-Group/HippoRAG).

### 5.2 Graphkonforme Antworten und kausale Struktur

**DoG (ACL 2025):** Graph-aware constrained decoding begrenzt die
Tokenauswahl anhand gueltiger KG-Tripel. Das Original erfordert Eingriff in
das Decoding offener Modelle. Ein Prompt mit JSON-Ausgabe ueber unsere
gehostete API bietet diese Garantie nicht. Fuer uns praktikabel: Der
Generator waehlt ausschliesslich angebotene Pfad-/Assertion-IDs; der Server
prueft Existenz, Orientierung, Verbindung und Quellen vor der Ausgabe.
Das waere eine DoG-inspirierte Validierung, keine Reproduktion von DoG.
Ein graphkonformer Fehler bleibt moeglich, wenn schon der Graph falsch ist.
[Paper](https://aclanthology.org/2025.acl-long.1186/),
[Mechanismus](https://arxiv.org/html/2410.18415),
[Autoren-Code](https://github.com/leekum2018/Decoding-on-Graph).

**CausalRAG2 (ICML 2026 laut Autorenfassung; vorher HugRAG):** Untersucht
hierarchische Module, kausale Gates und die Auswahl nicht-spurioeser
Belege. Fuer uns wertvoll: Query-Relevanz von kausaler Verknuepfung trennen.
Die Gates verbinden Module und sind nicht selbst belegte gerichtete
Einzelbehauptungen. Solche Suchabkuerzungen duerfen nicht als neue
wissenschaftliche Kausalrelationen im PEM-Graphen landen. Ein eigener
Hierarchieindex lohnt sich erst bei nachgewiesenen Recall-Verlusten zwischen
Modulen. [Aktuelle Autorenfassung](https://arxiv.org/abs/2602.05143v2),
[Algorithmus und Einschraenkungen](https://arxiv.org/html/2602.05143v2).

**HCG-RAG / Structure Over Scale (2026, Preprint):** Schlaegt kompakte
Graphen mit einer vorgegebenen kausalen Variablenstruktur vor. Das passt
zum Wunsch nach weniger, aber bedeutungsvollen Kanten. Fuer PEM sollte
zunaechst ein kuratiertes Mechanismen-Schema als zusaetzliche Sicht getestet
werden. Ein festes Schema fuer das gesamte Korpus koennte neue Materialien
und Mechanismen ausschliessen. Befunde auf medizinischen Daten sind noch
kein Nachweis fuer Batterieproduktion.
[Preprint](https://arxiv.org/abs/2607.22592),
[Volltext](https://arxiv.org/html/2607.22592v1).

### 5.3 Evaluation und Prompt-Optimierung

**GraphRAG-Bench (2025, Fassung 2026):** Bewertet Konstruktion, Retrieval
und Generierung und untersucht, wann Graphen gegenueber normalem RAG
helfen. Uebernehmen: gleicher Datenstand, gleiche Modelle, getrennte
Aufgabentypen und eine echte Vektor-RAG-Baseline. Es gibt keinen
Automatismus, dass mehr Graphstruktur jede Frage verbessert.
[Arbeit](https://arxiv.org/abs/2506.05690v3).

**RAGChecker (NeurIPS 2024):** Trennt Retrieval- und Generierungsfehler
mit feingranularer Bewertung. Fuer uns folgt daraus eine zusaetzliche
Claim-Pruefung: Ist jede Aussage aus der Antwort durch die Belege gestuetzt,
und sind benoetigte Aussagen enthalten? Ein solcher Pruefer muss auf
Batterietexten gegen menschliche Urteile validiert werden.
[Paper](https://proceedings.neurips.cc/paper_files/paper/2024/hash/27245589131d17368cccdfa990cbf16e-Abstract.html),
[Code](https://github.com/amazon-science/RAGChecker).

**GRADE (Findings EMNLP 2025):** Trennt Hop-Zahl und semantische Distanz.
Unser Stress-Test sollte diese Dimensionen ebenso ausweisen und kurze,
schwierige Entity-Linking-Fragen nicht mit langen, leicht paraphrasierten
Ketten vermischen. Die fremden News-Datensaetze sind keine PEM-Goldfaelle.
[Paper](https://aclanthology.org/2025.findings-emnlp.236/).

**GEPA (ICLR 2026):** Optimiert Prompts anhand von Ausfuehrungsspuren,
sprachlichem Feedback und konkurrierenden Kandidaten. Das passt spaeter
auf die vorhandenen isolierten Prompt Experiments. Erst verwenden, wenn
Bewertungsfehler und Train/Dev/Test-Trennung geklaert sind; sonst optimiert
es die Schwachstellen unseres Scorers. Suchbudget, Datenzugriff und Kosten
muessen begrenzt bleiben. Zunaechst drei handgepruefte Varianten vergleichen.
[Paper](https://arxiv.org/abs/2507.19457v2),
[Autoren-Code](https://github.com/gepa-ai/gepa).

## 6. Vortrainierte Modelle als Unterstuetzung

Ja: kleine spezialisierte Modelle koennen Kandidaten liefern, Belege sortieren
und Fehler markieren. Ihr Nutzen ist gezielt zu messen. Keines der folgenden
Modelle ist bereits als neue Pipeline-Komponente eingebaut; ihre allgemeinen
Benchmarks beweisen keine fachliche Kausalitaet in unserem Korpus.

| Kandidat | Geeignete Aufgabe | Integration / Grenze | Pilotprioritaet |
| --- | --- | --- | --- |
| `fastino/gliner2-base-v1` | Schemaorientierte Entity-Kandidaten und Relation-Experimente | Separater Worker vor der LLM-Extraktion; English-Modellkarte, deutsche Daten separat testen; Kandidaten duerfen fehlende Entities nicht hart ausschliessen | Hoch nach P0/P1 |
| `Qwen/Qwen3-Reranker-0.6B` | Query-Passage- oder Query-Pfad-Relevanz | Ein Pfad muss als kompakte Textfolge mit Beleg serialisiert werden; Relevanzscore validiert keine Wahrheit | Hoch |
| `BAAI/bge-reranker-v2-m3` | Multilinguale Cross-Encoder-Baseline fuer dieselbe Rangaufgabe | Mit Qwen auf identischen Kandidaten vergleichen; Sigmoid ist keine fachliche Konfidenzkalibrierung | Hoch, Alternative zu Qwen |
| `Qwen/Qwen3-Embedding-0.6B` | Neue Embedding-Baseline, Alias-/Anker-Suche | Eigener Index mit passender Query-Instruktion; bestehende Vektoren nicht mischen | Mittel |
| `MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli` | NLI-Signal fuer Widerspruch / fehlende Textstuetzung | Nur Review-Flag, Englisch und Fachsprache gesondert kalibrieren; nicht als automatisches Wahrheitsgericht | Mittel bis niedrig |
| Docling-Layout-/Tabellen-/Formelmodelle | Wiederherstellung lesbarer Evidenz aus PDFs | Vorhandenen HTTP-Adapter nutzen; Herkunft bis Seite/Block erhalten; Modelllizenzen getrennt von Code pruefen | Hoch bei belegtem Parserproblem |

GLiNER2 stellt eine vortrainierte, schemaorientierte Extraktionsschnittstelle
bereit. Der Bibliothekscode und die genannte Modellkarte nennen Apache-2.0;
der englische Checkpoint muss mit Revision fixiert werden. Das aktuelle
Repository enthaelt auch neuere Varianten; ein Wechsel ist ein neues
Experiment und kein stilles Upgrade.
[Paper](https://arxiv.org/abs/2507.18546),
[Bibliothek](https://github.com/fastino-ai/GLiNER2),
[Modellkarte](https://huggingface.co/fastino/gliner2-base-v1),
[Relation-Tutorial](https://github.com/fastino-ai/GLiNER2/blob/main/tutorial/6-relation_extraction.md).

Qwen3 stellt kleine, instruktionsfaehige multilinguale Embedding- und
Reranking-Modelle bereit. Die genannten Karten nennen Apache-2.0.
Start mit 0.6B und begrenzten Sequenzen; ein groesseres Modell erst nach
dem gleichen fachlichen Vergleich.
[Embedding-Modellkarte](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B),
[Reranker-Modellkarte](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B).
Die BGE-Alternative wird ebenfalls unter Apache-2.0 veroeffentlicht.
[BGE-Modellkarte](https://huggingface.co/BAAI/bge-reranker-v2-m3).

Der NLI-Kandidat wurde auf allgemeinen Inferenz-/Verifikationsdaten trainiert;
er kennt damit nicht automatisch unsere Einheiten, Protokolle und
Kausalbedingungen. [NLI-Modellkarte](https://huggingface.co/MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli).
Docling kann strukturierte Dokumente mit Layout und Provenienz darstellen.
Eine lesbare Formel oder erkannte Abbildung ist trotzdem noch keine
validierte physikalische Interpretation.
[Dokumentmodell](https://github.com/docling-project/docling/blob/main/docs/concepts/docling_document.md).

### Ressourcen und Modelltraining

Auf dem frueher beobachteten VPS mit rund 4 GiB RAM sollten Neo4j, Ollama,
zwei App-Stacks und zusaetzliche Transformer nicht gemeinsam erweitert werden.
Inferenz auf einen Uni-Worker auslagern, App/Index auf dem VPS behalten oder
spaeter gemeinsam auf eine ausreichend dimensionierte Uni-VM migrieren.

Als Planungsbudget fuer einen kleinen separaten CPU-Pilot: 4 vCPU, 8-16 GiB
RAM, 20-40 GiB freier Arbeits-/Modellspeicher, genau ein Modellprozess.
Das ist eine Engineering-Schaetzung, kein gemessener Mindestbedarf.
Bei 0.6B Parametern brauchen allein die Gewichte ca. 1.2 GB bei 16 Bit
oder 2.4 GB bei 32 Bit; Laufzeit, Sequenzen und Batches kommen dazu.
Fuer mehrere Modelle/GPU-Tests sind 16-32 GiB Host-RAM und eine separat
dimensionierte GPU sinnvoll; Maximal-Kontextlaengen nicht als Standardbatch
verwenden. Peak-RSS/VRAM, p95-Latenz und Durchsatz im Pilot messen.

Fine-Tuning erst nach Fehleranalyse und hinreichend vielen fachlich
annotierten Beispielen. Fuer einen ersten Versuch sind etwa 200-500
reviewte Absaetze ein Planungsziel, keine statistische Garantie. Gegen
Zero-shot, Few-shot und LLM-Baseline auf anderen Dokumenten vergleichen.
SciBERT oder andere vortrainierte wissenschaftliche Encoder allein sind
noch kein Batterie-Relationsmodell: ein trainierter Kopf, Labels und
Aufgabendaten waeren zusaetzlich erforderlich.

## 7. Prompts aus anderen Projekten und vom Supervisor

Fremde Prompts als nachvollziehbare Varianten testen. Nicht allein wegen
des Projektnamens oder einer dort berichteten Verbesserung uebernehmen.

| Herkunft | Konkret nutzbare Bausteine | Was fuer PEM angepasst werden muss |
| --- | --- | --- |
| Microsoft GraphRAG `extract_graph.py` | Expliziter Ausgabe-Vertrag, Beispiele, getrennte Extraktions-/Zusammenfassungsaufgaben | Breite Entity-/Relationship-Sammlung durch Mechanismenfokus ersetzen; unsere Richtung und JSON-Felder beibehalten |
| Microsoft GraphRAG `extract_claims.py` | Belegte Aussagen, Zitatstellen und Status als eigene Information | Nicht die dortigen TRUE/FALSE-Labels unkritisch als wissenschaftliche Wahrheit interpretieren; Beobachtung, Vorschlag, Simulation, Negation modellieren |
| HippoRAG `triple_extraction.py` | Relationsextraktion mit Entity-Liste und aufgeloesten Pronomen | Geschlossenes PEM-Predicate-Mapping, Belege und Bedingungen ergaenzen; nicht beliebige offene Predicates uebernehmen |
| PathRAG | Pfade als zusammenhaengende Belege und Redundanzabbau | Allgemeine Antwortpraeferenz-Prompts ersetzen keine fachliche Aussagepruefung; direkte Wiederverwendung erst nach dateispezifischer Lizenzpruefung |
| Supervisor `stage1_system_prompt.txt` | Erwaehnungen, stabile lokale IDs, Koreferenz, ungeloste Referenzen | Sentence-Splitting und ID-Schema brauchen einen Adapter; Konzept und konkrete Probe getrennt identifizieren |
| Supervisor `stage2_system_prompt.txt` | Feste Argument-IDs, Belegsaetze, Predicate-Disziplin, Inversenregeln | 57 Labels auf versionierte PEM-Ontologie abbilden; Effektzeichen, Bedingungen und Aussageart explizit speichern |

Gepruefte Originaldateien:
[GraphRAG Graph-Extraktion](https://github.com/microsoft/graphrag/blob/main/packages/graphrag/graphrag/prompts/index/extract_graph.py),
[GraphRAG Claims](https://github.com/microsoft/graphrag/blob/main/packages/graphrag/graphrag/prompts/index/extract_claims.py),
[HippoRAG Tripel](https://github.com/OSU-NLP-Group/HippoRAG/blob/main/src/hipporag/prompts/templates/triple_extraction.py).
Beide Repositories fuehren MIT-Lizenzen:
[Microsoft](https://github.com/microsoft/graphrag/blob/main/LICENSE),
[OSU](https://github.com/OSU-NLP-Group/HippoRAG/blob/main/LICENSE).

Beim Uebernehmen von Text/Code: Originaldatei, Commit-SHA, Lizenz und
Aenderungshinweis in der neuen Profilquelle dokumentieren und erforderliche
Copyright-/Lizenzhinweise beilegen. Paper, Bibliothek und Modellgewichte
koennen verschiedene Lizenzen haben. In dieser Dokumentationsaenderung
wurde kein fremder Prompt kopiert.

### Fachliche Korrekturen an den Supervisor-Vorlagen

Die Vorlagen sind ein guter Ausgangspunkt fuer eine **optionale** zweistufige
Extraktion. Sie sind keine direkt ladbaren PEM-YAML-Profile. Der aktuelle
Parser erwartet Namen/Typ/Beschreibung und Relationen nach Namen, nicht
lokale `e1`-IDs und `evidence_sentence_indices`. Ein blosses Austauschen der
Datei reicht daher nicht.

Die Formulierung, `isCauseOf` behaupte die alleinige Ursache, sollte entfernt
werden: eine Ursache muss nicht hinreichend oder die einzige sein. Auch
`directlyCauses` setzt explizite Direktheit voraus; das Fehlen eines genannten
Zwischenschritts beweist sie nicht. `precedes` beschreibt Zeitfolge und ist
nicht transitiv als `causes` zu interpretieren. `affects` und `influences`
sind im heutigen Code noch keine verlaessliche Kodierung eines Vorzeichens.

Verbatim-Erwaehnung und kanonischer Name trennen: Im ECM-Satz steht
`voltage and temperature RMSE`; eine koordinierte Erwaehnung kann den
gemeinsamen Kopf `RMSE` nur einmal enthalten. Der kanonische Begriff
`Voltage RMSE` darf daraus rekonstruiert werden, ohne einen falschen
woertlichen Quellenspan zu behaupten. Probenbezug und lokale Koreferenz
duerfen nicht allein durch einen global gleichen kanonischen Namen
zusammengefuehrt werden.

Drei Ablationen bei gleichem Modell und sauberen Outputs:

1. Aktuelles kompaktes Ein-Aufruf-Profil als Kosten-/Qualitaetsbaseline.
2. Ein-Aufruf-Profil mit Belegsaetzen, Effektzeichen, Bedingungen und
   wenigen fachlichen Negativbeispielen.
3. Zweistufig: Entity-Erwaehnungen/Koreferenz, dann Relationen ueber IDs;
   fehlende Argumente markieren und nur gezielt nacharbeiten.

Zwei Aufrufe sind nicht automatisch besser. Entity-Recall der ersten Stufe
begrenzt die zweite. Der Vergleich muss neue False Positives, Laufzeit und
Kosten je akzeptierter Relation zeigen, nicht nur Anzahl gefundener Kanten.

## 8. Zielvertrag fuer wissenschaftliche Aussagen

Vorgeschlagener Zusatz zur bisherigen Relation, noch nicht implementiert:

```json
{
  "assertion_id": "stable-source-local-id",
  "source_entity_id": "entity-id-a",
  "target_entity_id": "entity-id-b",
  "relation_type": "influences",
  "directionality": "directed",
  "effect_sign": "positive",
  "negated": false,
  "epistemic_status": "author_proposed",
  "conditions": {"operating_phase": "subsequent charging"},
  "evidence": [{"chunk_id": "chunk-id", "sentence_indices": [2, 3]}],
  "relation_importance": 0.9,
  "extraction_revision": "fingerprint"
}
```

Dies ist ein Schemaentwurf, kein fachliches Beispiel oder gueltiger heutiger
API-Payload. `effect_sign` beschreibt den Einfluss auf das Ziel; Bedeutung
und Bezugsskala muessen pro Predicate definiert sein. `unknown` ist erlaubt.
`relation_importance` bleibt Nuetzlichkeit. Eine spaetere
`evidence_confidence` waere separat zu kalibrieren.

Canonical Entity, Mention und Assertion unterscheiden. Claims behalten
Dokument/Chunk/Offset, Revision, Bedingungen und Probe. Eine abgeleitete
Kette referenziert Assertions, wird aber nicht automatisch als neue
experimentell bestaetigte Kante zurueckgeschrieben. Gleichnamige Temperatur-
oder Widerstandsknoten reichen nicht, um verschiedene Experimente logisch
zu verbinden.

Die Aussageidentitaet muss Predicate, semantische Endpunkte und relevante
Herkunfts-/Bedingungsinformation erhalten. Praktischer Einstieg: Assertion-KV
mit stabilen IDs als Quelle der Wahrheit und kompatible Graphprojektion.
Danach optional parallele Neo4j-Beziehungen mit `assertion_id` einfuehren.
Die Entscheidung zwischen Assertion-Knoten und parallelen Beziehungen durch
einen kleinen gemeinsamen Test fuer Import, Loeschen, Rebuild und Retrieval
treffen. Bestehende Paar-Edges waehrend der Migration weiter lesen.

## 9. Arbeitsplan mit Abnahmekriterien

Schaetzungen sind aktive Arbeitszeit einer entwickelnden Person mit Codex,
einschliesslich fokussierter Tests und Review. Modellwartezeit, Uni-Freigaben
und Fachannotation kommen hinzu. Nach jedem Paket Ergebnis pruefen;
spaetere Forschungspakete haengen vom gemessenen Fehlerbild ab.

| Paket | Aufwand | Ergebnis | Abhaengigkeit |
| --- | --- | --- | --- |
| P0 Import-Integritaet und Reproduzierbarkeit | 1-2 Tage | Keine still akzeptierten Teilantworten, Submission-Snapshot | Sofort |
| P1 Messung und Goldstandard | 2-4 Tage + Fachreview | Fehler nach Stufe, Precision und Claim-Pruefung | P0 fuer reale Extraktionsbaseline |
| P2 Predicate-Konsistenz und Prompt-Ablation | 1-2 Tage | Zentrale Predicate-Regeln und faire Profilvergleiche | P0/P1 |
| P3 Evidenz, Bedingungen, zweistufiger Pilot | 3-5 Tage | Optionaler Extraktionsadapter und erweiterter Artefaktvertrag | P2 |
| P4 Aussageerhalt und sichere Migration | 3-6 Tage | Kein Verlust paralleler/bedingter Assertions | P3-Schemaentscheidung |
| P5 Anker, Reranking, Pfadselektion | 2-4 Tage | Queryrelevante, belegte Pfade unter Budget | P1; P4 fuer verlustfreie Langketten |
| P6 Antwortvalidierung und 4-5-Hops-Pilot | 2-4 Tage | Gepruefte Pfad-IDs und separat gemessene Langketten | P3-P5 |
| P7 Optional GLiNER/GEPA/Fine-Tuning | Je 2-5 Tage Pilot, Annotation separat | Nur bei messbarem Vorteil weiterfuehren | Saubere Testsplits und P1 |

P0-P2 sind der erste kleine Release, grob 4-8 Arbeitstage plus Fachreview.
P0-P6 umfassen grob 14-27 Arbeitstage, nicht einen einzelnen 15-Minuten-Task.
Diese Reihenfolge verspricht keine bestimmte Verbesserung in Prozentpunkten.

### P0: Batch- und normale Extraktion gegen Datenverlust absichern

**Teilstand 2026-10-19:** Batch-JSON-Ausgaben sind vor dem Merge gegen
unvollstaendige/abgewiesene Antworten, ungueliges Schema und fremde,
doppelte oder fehlende Chunk-IDs abgesichert. Neue Jobs speichern ein
Submission-Manifest mit Chunk-/Request-Hashes, Endpoint, Modell,
Outputbudget, Prompt-Hash und Extraktionsrevision; der Import verwendet diese
eingereichte Revision. Validierungsfehler werden auf Job- und
Dokumentmetadaten gespeichert. Lokale Regressionstests pruefen den
vollstaendigkeitskritischen Pfad. Noch offen bleiben normaler Provider,
begrenzte Einzelchunk-Retries und idempotente Wiederaufnahme nach Fehlern
waehrend des Merges.

Aenderungsstellen: [`api/azure_batch.py`](../lightrag/api/azure_batch.py),
[`operate.py`](../lightrag/operate.py),
[`extraction_revisions.py`](../lightrag/extraction_revisions.py),
[`document_routes.py`](../lightrag/api/routers/document_routes.py),
[`llm/openai.py`](../lightrag/llm/openai.py).

Vertrag: Zuerst Transport- und Completionstatus pruefen, dann striktes
JSON/Schema, dann Chunkzuordnung und Merge. `json_repair` darf reparierbare
Formatfehler bei explizit vollstaendigen Antworten behandeln, aber keine
abgeschnittene Antwort als vollstaendig auszeichnen. Gueltige leere Ergebnisse
bleiben erlaubt; null Relationen allein ist kein Retry-Grund.

Der normale Provider gibt bisher hauptsaechlich Inhalt als String zurueck.
Completionstatus daher vor diesem Informationsverlust pruefen oder als
internes Ergebnis mit Metadaten weiterreichen. Den oeffentlichen String-/
Streaming-Vertrag und andere LLM-Rollen dabei kompatibel halten; ein
Kommentar im Provider ersetzt keine tatsaechliche Statusvalidierung.

Bei Einreichung Chunk-IDs/-Hashes, Prompt-Snapshot/-Hash, Batch-Deployment,
Endpoint, Schema, Outputbudget und Code-Revision speichern. Beim Import
fehlende, doppelte, fremde und veraenderte Chunks erkennen. Jede Fehlzeile
erhaelt einen persistierten Grund. Bereits valide Artefakte behalten,
nur problematische Chunks mit begrenzter Retryzahl nacharbeiten.

Erst alle erwarteten Zeilen validieren, dann importieren. Ein Verbindungsfehler
waehrend des anschliessenden Merges kann weiterhin Teilwrites verursachen;
dafuer idempotente Wiederaufnahme und Dokument-Rebuild vorsehen. Ein
Validierungsfehler soll dagegen keinerlei Graphwrites ausloesen.
Dokument erst bei vollstaendiger erfolgreicher Verarbeitung als aktuell markieren.

Tests: HTTP 200 + `incomplete`, `finish_reason=length`, Refusal, fehlerhaftes
Schema, Fremd-ID, doppelte/fehlende Zeile, geaenderter Chunk, legitimes
Leerresultat, Modellwechsel vor Import, Retry ohne Duplicate-Write.
Pilot: 5-10 diverse Chunks, Outputbudget z.B. 8192 als Testwert, echte
Completionrate/Tokenverteilung/Kosten erfassen. Keine pauschale Neu-Extraktion
aller Dokumente zur Diagnose.

### P1: Evaluation in vier getrennte Fragestellungen aufteilen

Aenderungsstellen: [`live_benchmark.py`](../lightrag/evaluation/live_benchmark.py),
[`semantic_matching.py`](../lightrag/evaluation/semantic_matching.py),
[`run_history.py`](../lightrag/evaluation/run_history.py),
[`evaluation_routes.py`](../lightrag/api/routers/evaluation_routes.py),
[`EvaluationManager.tsx`](../lightrag_webui/src/features/EvaluationManager.tsx),
`evaluation/benchmarks/`.

1. **Extraktion:** Entities und Assertions auf vollstaendig annotierten
   Absaetzen; Precision/Recall/F1, Richtung, Vorzeichen, Bedingungen,
   Quellenbezug und ueberfluessige Objekte. Bei nur teilweise annotierten
   Dokumenten unbewertete Zusatzkanten als `unreviewed` behandeln, nicht
   pauschal als False Positives. Entity-Matching eins-zu-eins vornehmen.
2. **Pfad-Engine:** Kuratierter Goldgraph ohne LLM-Extraktion; richtiger
   Anker, Orientation, erlaubte Predicates, zusammenhaengender Pfad und
   Budget. Trennt Suchfehler von fehlenden Kanten.
3. **Evidenz-Retrieval:** Bei fixiertem Graphen Goldbelege Recall@k/MRR,
   falsche Quellen und Treffer innerhalb des gleichen Kontextbudgets messen.
4. **End-to-end-Antworten:** Erforderliche Claims, Negation, Bedingungen,
   verbotene Behauptungen und Belegstuetzung bewerten. `expected_answer`
   als Referenz, nicht als woertlichen Pflichttext behandeln. Antworten je
   Strategie tatsaechlich erzeugen und den verwendeten Kontext archivieren.

Scoring 2.0.0 als Historie behalten; Aenderungen der Predicate-/Claim-
Bewertung erhalten eine neue Scoringversion. Metadata bleibt Diagnose,
Keyword-/Reference-Coverage bleibt als eigene Abdeckungsmetrik sichtbar.
Nicht durch ein kleineres Gewicht aus einer Abdeckungsmetrik eine fachliche
Korrektheitsmetrik machen. Einen Overall erst nach dokumentiertem neuen
Profil vergleichen; Komponenten und Exact/Partial getrennt anzeigen.

Startdaten: 30-50 vollstaendig annotierte Absaetze und 40-60 reviewte Fragen
als Pilot; spaeter erweitern. Ganze Paperfamilien auf Train/Dev/Test aufteilen,
inklusive paraphrasierter und Reverse-Fragen derselben Kette. Dieselbe
Quelle nicht ueber unterschiedliche Textfenster in beide Splits legen.
Richtiges Verhalten bei fehlender Evidenz, nicht-kausaler Zeitfolge,
negierten Effekten und widersprechenden Protokollen gehoert in den Test.

Abnahme: Jeder hoch bewertete fachlich falsche Fall aus dem alten Bericht
loest jetzt mindestens einen erklaerten Fehler aus. Quellenbelege werden
auf Aussageebene geprueft. Neues Modell/Judge nur gegen eine fachlich
reviewte Teilmenge freigeben; Judge-Uneinigkeit sichtbar halten.

### P2/P3: Prompt, Ontologie und Extraktionskontext

Aenderungsstellen: [`relation_ontology.py`](../lightrag/relation_ontology.py),
[`adaptive_retrieval.py`](../lightrag/adaptive_retrieval.py),
[`directed_retrieval.py`](../lightrag/directed_retrieval.py),
[`prompt.py`](../lightrag/prompt.py),
[`operate.py`](../lightrag/operate.py),
[`llm_roles.py`](../lightrag/llm_roles.py),
[`prompt_experiments.py`](../lightrag/evaluation/prompt_experiments.py),
[`prompts/samples/`](../prompts/samples/).

Eine zentrale versionierte Tabelle beschreibt Label, Definition, Domain/
Range, Inverse, Symmetrie, Effektzeichen und Routingfamilie. Surface-Aliases
von schwacher semantischer Aehnlichkeit trennen. `contains`/`part_of` als
inverse Bedeutung nur mit getauschten Endpunkten vergleichen; `produces`
nicht mit ihnen gleichsetzen. Vorzeichenkonflikte erhalten keinen
Aequivalenzbonus. Freie Labels zunaechst als unknown reviewen; Schema nicht
so eng machen, dass explizite neue Fachrelationen unsichtbar verschwinden.

Legacy-Prompt und Schema v1 bleiben lesbar. Evidenz-/Bedingungsfelder muessen
durch Parser, Zwischenartefakte, Serialisierung, Merge, Speicherung, Abfrage,
Revision und Evaluation gehen. Zusaetzliche YAML-Anweisungen allein speichern
diese Daten nicht. Der Zwei-Stufen-Adapter bekommt einen eigenen Modus,
einen geprueften Sentence-Splitter, lokale Entity-IDs und eine explizite
Uebersetzung zum heutigen Speichervertrag. Rollenmodellbau ueber `llm_roles.py`
erweitern, nicht separat im Provider hardcoden.

Screening-Sample deterministisch ueber relevante Abschnitte und Dokumentlaenge
verteilen. Ein Benchmark darf nur fuer im Sample enthaltene Evidenz bewertet
werden; alle Kandidaten bekommen dieselben Chunk-IDs. Die vorhandene
Korpusabdeckungspruefung auf Dateiebene reicht dafuer nicht. Auf Anfangschunks
der Paper dominieren sonst Autoren und Einleitung statt Mechanismen.

Abnahme: koordinierte ECM-Metriken, Passiv/Inversen, Pronomen, mehrere Proben,
Negation und bedingte Effekte bestehen; F1 und Kosten je akzeptierter Assertion
sind auf Dev und unangetastetem Test ausgewiesen. Promotion nur aus Final;
URLs und Dokumentidentitaet bleiben bei Re-extraktion nachweislich erhalten.

### P4: Aussagen verlustfrei erhalten

Aenderungsstellen: `merge_nodes_and_edges`, `_merge_edges_then_upsert`,
`_merge_relationship_metadata` in [`operate.py`](../lightrag/operate.py),
[`relation_identity.py`](../lightrag/relation_identity.py),
[`utils.py`](../lightrag/utils.py),
[`base.py`](../lightrag/base.py),
[`kg/neo4j_impl.py`](../lightrag/kg/neo4j_impl.py),
[`utils_graph.py`](../lightrag/utils_graph.py),
`areextract_doc_kg` in [`lightrag.py`](../lightrag/lightrag.py).

Erst Assertions dual speichern und einen kleinen read-only Provider darauf
setzen. Dann Migration nach Dokument/Revision mit Zaehlern und Rollback
testen. Abgeleitete Vektoren, Chunktracking und Loeschpfade muessen dieselbe
Identitaet verwenden. Alte ungeordnete Paar-Beziehungen bleiben kompatibel
lesbar; nicht per Cypher nur Pfeile umdrehen und Vollstaendigkeit behaupten.

Abnahme: `A increases B`, `A measures B` und eine andere, bedingte Aussage
bleiben separat erhalten. Wiederimport ist idempotent. Loeschen eines Dokuments
erhaelt die Evidenz anderer Dokumente. Revision und Quellen ueberleben Rebuild.

### P5/P6: Gerichtetes Retrieval verbessern, normalen Modus erhalten

Aenderungsstellen: `_directed_path_anchors`, `_build_query_context` und
Quellenaufloesung in [`operate.py`](../lightrag/operate.py),
[`directed_retrieval.py`](../lightrag/directed_retrieval.py),
[`kg/neo4j_impl.py`](../lightrag/kg/neo4j_impl.py),
[`rerank.py`](../lightrag/rerank.py),
[`base.py`](../lightrag/base.py),
[`query_routes.py`](../lightrag/api/routers/query_routes.py),
[`lightrag_client.py`](../lightrag_mcp/lightrag_client.py).

Start mit Ankern aus expliziten Query-Mentions plus Entity-/Relationssuche.
Exakte Namen/Aliases bevorzugen, Reranker nur auf begrenztem Kandidatensatz.
Predicate/Richtung vor dem Provider-Cutoff filtern und Querykosten begrenzen.
Pfadselektion bewertet Queryrelevanz, Belegabdeckung, Bedingungskompatibilitaet,
Laenge und Redundanz getrennt. PathRAG-Fluss als optionale Ablation gegen
die heutige Beam-BFS testen; nicht gleichzeitig alle Scoringvarianten aendern.

Normaler Modus bleibt Standard und ruft keinen Directed-Provider auf.
`combined` hat ein Gesamtbudget fuer normalen Kontext und Pfadbelege.
Jede Aussage der Kette braucht ihre eigene belegte Assertion. Die heutige
Aufloesung auf Chunk-/Pfadniveau durch exakt zugeordnete Belegspannen
ergaenzen, bevor ein Pfad als wissenschaftlich bestaetigt dargestellt wird.

Fuer Antwortvalidierung nur vorhandene Pfad-IDs und kurze belegte Claims
waehlen lassen. Der Server prueft IDs/Connectivity/Orientation/Quellen.
Eine Auswahlgueltigkeit beweist noch keine Textimplikation; strittige Claims
zusaetzlich pruefen oder qualifizieren. Keine Anforderung an verborgene
Reasoning-Texte; sichtbare Belegkette und Unsicherheit reichen.

Erst dann Hop-Limit 3 -> 5 in Python, REST, MCP, UI und Evaluation konsistent
erweitern. BFS/Beam beibehalten und Depth, Fanout, Frontier, besuchte Kanten,
Graphlaufzeit, Gesamtpfade und Kontexttokens deckeln. Ein Wechsel zu DFS
verbessert weder Belegqualitaet noch die Behandlung falscher Kanten.
Laengenabzug so testen, dass korrekte 5-Hop-Pfade nicht von mehreren
irrelevanten 1-Hop-Pfaden aus dem Prompt verdraengt werden.

Abnahme: Goldanker und frei gesuchte Anker getrennt messen, Pfad-Recall@k,
Praezision der behaupteten Ketten, Tokenbudget und p95-Latenz ausweisen.
`normal` beantwortet bestehende Tests unveraendert; Fehlanwendung von
`auto` faellt auf eine dokumentierte sichere Strategie zurueck.

## 10. Embedding, Parsing und Chunking mit dem besten Aufwand/Nutzen

Vor neuem Embedding-Modell die vorhandene Nomic-Konfiguration auditieren:
genauen Ollama-Modell-Digest, tatsaechliches Kontextlimit, Query-/Dokument-
Praefixe und ueberlange Inputs. Die Karte von Nomic v1.5 verlangt passende
Suchpraefixe; die Runtime kann ein anderes Modell unter dem Alias verwenden.
Darum erst `ollama show`/Runtime-Snapshot pruefen.
[Nomic-Modellkarte](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5).

Code: [`api/config.py`](../lightrag/api/config.py),
[`api/lightrag_server.py`](../lightrag/api/lightrag_server.py),
[`llm/ollama.py`](../lightrag/llm/ollama.py).
Chunk-Tokens des LLM-Tokenizers sind nicht dieselben wie Embedding-Tokens.
Auch zusammengefuehrte Entity-/Relationsbeschreibungen werden eingebettet;
kleine Dokumentchunks garantieren deshalb keinen erfolgreichen Import.
Silent Truncation messen und vermeiden; Beschreibungsteilung oder
belegtreue Zusammenfassung vor dem Embedding testen.

Ein neuer Embeddingraum bekommt eigene Collection/Verzeichnisse und neue
Entity-, Relation- und Chunkvektoren. Gleiches Dimensionsmass bedeutet
nicht Kompatibilitaet. Einen laufenden Datenbestand fuer den Vergleich
nicht loeschen. Top-k-Recall und Ankerqualitaet auf demselben Goldstandard
vergleichen; erst bei gesichertem Vorteil umschalten.

Fuer Parsing einen kleinen PDF-Satz mit Zweispaltenlayout, Tabellen,
Formeln, Referenzen und Abbildungen auf relevante Seitenbelege pruefen.
Vorhandene Adapter: [`parser/routing.py`](../lightrag/parser/routing.py),
[`parser/external/docling/`](../lightrag/parser/external/docling/),
[`parser/external/mineru/`](../lightrag/parser/external/mineru/).
Section-aware Chunking und ein eng begrenztes Nachbarfenster vor der
Extraktion testen. Benachbarter Kontext ist kein Beleg fuer erfundene
Verbindungen. Seiten-/Block-IDs bis zum Benchmark erhalten. Selektive
VLM-Beschreibung nur fuer wirklich benoetigte Grafiken einsetzen und
explizit von Textbelegen unterscheiden.

## 11. Erfolgsziel fuer vier und fuenf Hops

Die bisherige Implementierung erlaubt oeffentlich maximal drei Hops.
Deshalb ist kein aktueller Score ein nachgewiesener 5-Hop-Erfolg.
Auch der kleine ECM-Test mit 100 bei fuenf Entities ist nur ein bestandener
Entity-Abdeckungstest, keine Evidenz fuer wissenschaftliche Kausalitaet.

80% kann ein Ziel fuer ein klar abgegrenztes, kuratiertes Testset werden.
Es ist noch keine realistische Zusage fuer beliebige neue Batteriepapers.
Unter einer rein illustrativen Unabhaengigkeitsannahme braucht eine feste
Kette fuer 0.8 gemeinsame Kantenkorrektheit etwa
`0.8 ** (1/5) = 0.956` je Kante. Das laesst Ankerfehler, fehlende Kanten,
Belegabruf und Antwortfehler weg; echte Fehler sind ausserdem korreliert.
Importance ist keine solche Wahrscheinlichkeit und sollte nicht als
Wahrheitsprodukt ausgegeben werden.

Fuer Langketten zwei Quoten berichten: Recall der gesuchten Goldpfade und
Precision der tatsaechlich behaupteten Ketten. Zusaetzlich Coverage und
korrekte Enthaltung messen; 80% nur auf wenigen beantworteten Fragen ist
ein anderer Betriebspunkt als 80% bei voller Abdeckung. Konfidenzintervalle
auf unabhaengigen Mechanismen/Papern bootstrappen; Forward-/Reverse-
Paraphrasen nicht als unabhaengige Stichproben behandeln.

MCTD-KG und GRADE aus dem frueheren Bericht koennen Ideen fuer Struktur
und Schwierigkeit liefern. Ihre Accuracy ist mit unserem heutigen
gewichteten Coverage-Overall nicht gleichzusetzen.

## 12. Verifikation dieses Dokumentationsstands

Lokaler Lauf ohne externe Dienste / neue Modellaufrufe:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/retrieval/test_adaptive_retrieval.py `
  tests/retrieval/test_directed_retrieval_edge_selection.py `
  tests/retrieval/test_directed_path_traversal.py `
  tests/kg/neo4j_impl/test_neo4j_directed_neighbors.py `
  tests/evaluation/test_live_benchmark.py `
  tests/evaluation/test_semantic_benchmark_matching.py `
  tests/evaluation/test_prompt_experiments.py `
  tests/evaluation/test_quality_docs_benchmarks.py `
  tests/extraction/test_extraction_revisions.py -q
```

Ergebnis am 19.10.2026: **112 passed**. Diese Tests bestaetigen die
geprueften bestehenden Vertraege, nicht die noch geplanten neuen Gates,
Modelle, Claim-Pruefer oder 5-Hop-Funktionen. Fuer jede kuenftige Aenderung
sind die im Arbeitspaket genannten Regressionen zu ergaenzen.

Zusaetzliche reine Offline-Proben bestaetigten: `_parse_output_jsonl()`
akzeptiert eine HTTP-200-Zeile mit `body.status="incomplete"`;
`text_match("Local Current Nonuniformity", "Current")` liefert 0.85;
`predicate_similarity("produces", "contains")` und
`predicate_similarity("increases", "decreases")` liefern jeweils 0.78.
Diese Reproduktionen sind Befunde am Ist-Zustand, keine gewuenschten
Abnahmewerte fuer das naechste Release.

## 13. Naechster umsetzbarer Auftrag

P0 zuerst in einem separaten Staging-Commit implementieren: einen gemeinsamen
Completion-/Schema-Validator mit Regressionstests und ein unveraenderliches
Batch-Submission-Manifest. Rohantworten mit Fehlergruenden erhalten,
Graphwrites bei ungueltigen Outputs verhindern und die Revision aus dem
Submission-Snapshot ableiten. Danach einen kleinen bezahlten Pilot explizit
starten und anhand echter Outputs entscheiden, welche Chunks neu extrahiert
werden muessen. Prompt-Optimierung erst auf dieser sauberen Baseline messen.
