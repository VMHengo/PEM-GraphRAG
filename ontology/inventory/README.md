# Begriffsinventar des Union-Graphen

Lesbare Auflistung aller Begriffe aus `ontology/merged/merged.ttl` (Ticket 06).
Erzeugt mit `ontology/make_inventory.py`. Stand 2026-09-08 (Ticket 23: domain-battery
0.18.6 → 0.20.2, siehe `manifest.json`); frühere Zahlen (Stand 2026-09-07,
0.18.6) sind darunter jeweils in Klammern mitgeführt.

Die Dateien sind semikolongetrennte CSV in UTF-8 mit BOM — Excel öffnet sie ohne
Import-Dialog korrekt. Spalten durchgängig: `quelle`, `label`, `synonyme`,
`oberklassen`, `erlaeuterung`, `iri`.

## Dateien

| Datei | Zeilen | Inhalt |
|---|---|---|
| `klassen.csv` | 4.608 (4.494) | alle benannten Klassen — die Kandidatenbasis für den Entitätstypensatz (Ticket 07) |
| `object_properties.csv` | 310 (309) | alle Object Properties — die Kandidatenbasis für das **Relations**schema (Ticket 07) |
| `data_properties.csv` | 32 | Datentyp-Properties (Werte, keine Relationen zwischen Entitäten) |
| `annotation_properties.csv` | 100 (92) | Annotationsproperties (Metadaten, für die Extraktion irrelevant) |
| `relation_candidates_raw.csv` | 310 (309) | Rohextraktion aller Object Properties mit Domain/Range/Definition/EMMO-Ast (Ticket 07) |
| `relationsschema_stufe1.csv` | 310 (309) | **Kandidatensatz Stufe 1** mit Entscheidung, Rationale und R4-Einschätzung — die Methodik-Tabelle des Kapitels |

`fehlend_in_0.20.2.csv` (114 Zeilen) ist mit dem Versionswechsel entfallen — ihr Zweck
(Entscheidungsgrundlage für Ticket 21) ist erfüllt, die Klassen sind jetzt im Merge
selbst enthalten.

## Warum 4.608 und nicht 4.725

Der Graph enthält 4.725 Subjekte vom Typ `owl:Class` (siehe `manifest.json`), davon sind
**117 Blank Nodes** — anonyme Klassenausdrücke (Restriktionen, Vereinigungen), die aus
der Axiomatik stammen und keine benennbaren Begriffe sind. Sie sind hier bewusst nicht
aufgeführt.

## Verteilung nach Quellontologie

**Klassen (4.608, zuvor 4.494):**

| Quelle | Klassen | zuvor (0.18.6) |
|---|---|---|
| EMMO-Kern | 2.433 | 2.433 |
| domain-electrochemistry | 888 | 888 |
| chemical-substance | 651 | 651 |
| domain-battery | 325 | 212 |
| CHAMEO | 201 | 201 |
| BTO | 51 | 51 |
| domain-manufacturing | 43 | 43 |
| BattINFO (Platzhalter) | 11 | 11 |
| schema.org / FOAF | 5 | 4 |

domain-battery trägt jetzt 325 statt 212 Klassen (+113, ein Rest der +114 aus Ticket 21
ging in eine IRI-Ersetzung ohne Netto-Zuwachs auf, siehe dort). Die 72 dabei
hinzugekommenen Geometrieklassen (`battery-cell-geometry`) sind für Fließtext praktisch
irrelevant, siehe Ticket 21s Relevanzbewertung.

**Object Properties (310, zuvor 309):**

| Quelle | Properties | zuvor (0.18.6) |
|---|---|---|
| EMMO-Kern | 214 | 214 |
| CHAMEO | 48 | 48 |
| domain-electrochemistry | 27 | 27 |
| BTO | 14 | 14 |
| domain-battery | 4 | 3 |
| schema.org | 2 | 2 |
| chemical-substance | 1 | 1 |

Bemerkenswert für Ticket 07: die eigentlich batteriespezifischen Relationen sind dünn
gesät — domain-battery steuert weiterhin nur **4** Object Properties bei (der
Versionswechsel brachte genau eine neue: `hasSurface`, geprüft und in Ticket 11
ausgeschlossen), das Gros der Relationsausdrucksmittel kommt aus dem EMMO-Kern
(mereologische und kausale Relationen) und aus CHAMEO (Charakterisierungsmethodik). Das
ist ein Befund, kein Mangel des Inventars, und dürfte die Ableitung des Relationsschemas
prägen.

## Hinweise zur Benutzung

- **Labels stammen aus `skos:prefLabel` *und* `rdfs:label`.** EMMO führt seine
  Primärlabels in `skos:prefLabel`; ein Skript, das nur `rdfs:label` liest, verliert rund
  40 % der Klassen (siehe `NOTES.md`, Korrektureintrag 2026-09-06).
- **Die Spalte `synonyme`** speist sich aus `skos:altLabel` (1.895 Tripel im Graph). Für
  das Mention-Matching in der Extraktion ist das die wertvollste Spalte nach `label`.
- **141 Klassen tragen überhaupt kein Label** und erscheinen mit leerer `label`-Spalte.
  Ohne Zusatzarbeit sind sie als Schematyp nicht verwendbar.
- **Vier Klassen tragen widersprüchliche `skos:prefLabel`** aus verschiedenen
  Quelldateien (`MaterialBySize`/`SizeDefinedMaterial` u. a.). In allen vier Fällen ist
  `dependencies.ttl` die abweichende Quelle; Empfehlung ist, der jeweils anderen Fassung
  zu folgen. Details in `ontology/merge_report.json`.
- **Quellstand und Lizenz:** Das Inventar beschreibt den gespeicherten Merge.
  Die aktuell vorliegende BattINFO-Quelldatei deklariert 0.7.0/Apache-2.0,
  waehrend das Manifest 0.8.0-beta/CC BY dokumentiert. Quelle und Merge
  stimmen nicht ueberein; siehe `ontology/README.md`. Vor Weitergabe und
  produktiver Nutzung die gewaehlte Quellversion und ihre Bedingungen pruefen.

## Relationsschema Stufe 1 (Ticket 07)

`relationsschema_stufe1.csv` führt alle 310 Object Properties mit den Spalten
`entscheidung` (kandidat/ausgeschlossen), `satzuebergreifend` (hoch/mittel/niedrig),
`dublette`, Metadaten und `rationale`.

**185 Kandidaten, 125 ausgeschlossen** (Ticket 23: +1 gegenüber den ursprünglichen 184 —
`hasSurface`, neu durch den domain-battery-0.20.2-Wechsel, kein bestehender Ausschluss
trifft zu, automatisch Kandidat). Ausschlussgründe unverändert, gruppenweise begründet in
`ontology/relation_decisions.json`:

| Gruppe | Anzahl |
|---|---|
| Peirce-Semiotik (Zeichen/Interpret/Ikon/Index) | 42 |
| Mereotopologie (Überlappungskalkül) | 20 |
| Parthood-Formalvarianten (redundant/distinct/junction …) | 17 |
| Tessellation (Kachelmodell) | 15 |
| IRI-Dubletten-Stubs | 11 |
| Symbol- und Einheiteninnenbau | 9 |
| abstrakte Wurzel-Properties | 5 |
| Metadaten/Provenienz | 4 |
| Negations-Konstrukte | 2 |

Kandidaten nach Quelle: EMMO-Kern 94, CHAMEO 46, domain-electrochemistry 27, BTO 13,
domain-battery 4 (zuvor 3), chemical-substance 1.

Kandidaten nach R4-Realisierbarkeit (satzübergreifend): **hoch 50**, mittel 115,
niedrig 20 (zuvor 19 — `hasSurface` neu, gleiche Einstufung wie `hasCellForm`).

## Neu erzeugen

```
.venv/Scripts/python.exe ontology/make_inventory.py
.venv/Scripts/python.exe ontology/extract_relation_candidates.py
.venv/Scripts/python.exe ontology/join_relation_decisions.py
```
