# DTMF Code für Home Assistant

[![Validate](https://github.com/vothmarkus/DTMF-Code-HA/actions/workflows/validate.yml/badge.svg)](https://github.com/vothmarkus/DTMF-Code-HA/actions/workflows/validate.yml)

`DTMF Code` sammelt die einzelnen DTMF-Ereignisse des
[Reolink SIP Gateway](https://github.com/vothmarkus/reolink-sip-gateway-ha),
prüft die eingegebene Ziffernfolge beim Drücken der Bestätigungstaste und stellt
für jedes Codeprofil eine eigene Home-Assistant-Ereignis-Entität bereit.

Ein Profil besteht aus:

- einem frei wählbaren Namen und einem 4 bis 12 Ziffern langen Code,
- einer Freigabe für eingehende und/oder ausgehende Anrufe,
- einer exakten Rufnummernfreigabe oder der ausdrücklichen Freigabe aller
  Gegenstellen.

Damit können mehrere Codes unabhängig voneinander unterschiedliche
Automatisierungen auslösen, beispielsweise für Bewohner, Lieferdienste oder
zeitweise Zutrittsberechtigungen.

> [!IMPORTANT]
> Die Integration benötigt `Reolink SIP Gateway` **1.0.0 oder neuer**. Die
> DTMF-Ereignisse müssen die Felder `remote_number` und `call_id` enthalten.

## Funktionsweise

1. Das Reolink SIP Gateway meldet jede gedrückte Taste als flüchtiges Ereignis.
2. DTMF Code sammelt Ziffern ausschließlich innerhalb desselben SIP-Anrufs.
3. `#` bestätigt die Eingabe, `*` verwirft sie (beides ist konfigurierbar).
4. Nur wenn Code, Anrufrichtung und Rufnummernregel passen, wird die
   Ereignis-Entität des betreffenden Profils aktualisiert.
5. Fehlversuche und temporäre Sperren erscheinen ausschließlich auf der
   gemeinsamen Ereignis-Entität `Sicherheit`.

Weder der eingegebene Code noch Teile davon werden als Ereignisdaten oder
Protokollmeldung ausgegeben. Konfigurierte Codes werden mit PBKDF2-SHA256 und
einem zufälligen Salt gespeichert.

## Installation

### HACS

1. Dieses Repository in HACS als benutzerdefiniertes Repository vom Typ
   **Integration** hinzufügen.
2. `DTMF Code` installieren.
3. Home Assistant neu starten.

### Manuell

Den Ordner `custom_components/dtmf_code` nach
`<config>/custom_components/dtmf_code` kopieren und Home Assistant neu starten.

## Einrichtung

Unter **Einstellungen > Geräte & Dienste > Integration hinzufügen** nach
`DTMF Code` suchen und das gewünschte Reolink SIP Gateway auswählen.

Gemeinsame Einstellungen:

| Einstellung | Standard | Bedeutung |
|---|---:|---|
| Bestätigungstaste | `#` | Prüft den bis dahin eingegebenen Code |
| Löschtaste | `*` | Verwirft die aktuelle Eingabe |
| Eingabezeitlimit | 10 s | Verwirft eine unvollständige Eingabe |
| Fehlversuche | 5 | Versuche pro Rufnummer und Anrufrichtung bis zur Sperre |
| Sperrdauer | 60 s | Dauer der temporären Sperre |

Anschließend wird direkt das erste Codeprofil angelegt. Weitere Profile lassen
sich auf der Integrationsseite über **Eintrag hinzufügen > Codeprofil**
erstellen. Bestehende Profile können dort umbenannt, eingeschränkt oder mit
einem neuen Code versehen werden.

### Rufnummernvergleich

Die Gegenstelle wird in eine kanonische Form gebracht. Beispielsweise werden
`sip:+49 170-123456@example.org` und `+49170123456` identisch behandelt.
Danach erfolgt immer ein **exakter** Vergleich; Suffixe und Platzhalter werden
nicht unterstützt. Bei ausgehenden Anrufen ist die im Gateway konfigurierte
Zielrufnummer die Gegenstelle.

## Automatisierungen

Jedes Codeprofil besitzt eine eigene Ereignis-Entität mit dem Ereignistyp
`accepted`. Dadurch muss der Zugangscode selbst nie in einer Automation stehen.

```yaml
alias: Haustür nach gültigem Familiencode öffnen
triggers:
  - trigger: event.received
    target:
      entity_id: event.dtmf_code_familie
    options:
      event_type:
        - accepted
actions:
  - action: lock.unlock
    target:
      entity_id: lock.haustuer
mode: single
```

Die Ereignisattribute enthalten nur nicht geheime Metadaten:

| Attribut | Beschreibung |
|---|---|
| `event_type` | `accepted`, `rejected` oder `locked_out` |
| `profile_id` / `profile_name` | Nur bei akzeptierten Codes |
| `remote_number` | Normalisierte Gegenstelle |
| `call_direction` | `incoming` oder `outgoing` |
| `call_id` | SIP-Anruf-ID |
| `received_at` | Empfangszeitpunkt des bestätigenden DTMF-Ereignisses |
| `instance_id` | Installations-ID des Reolink SIP Gateways |
| `lockout_seconds` | Nur bei `locked_out` |

> [!CAUTION]
> Ein DTMF-Code allein ist keine starke Authentifizierung. Für sicherheitskritische
> Aktionen empfiehlt sich eine zusätzliche Bedingung oder Bestätigung.

## Entwicklung

```bash
python -m pip install -r requirements_test.txt
ruff check .
pytest
```

Fehler und Vorschläge können über die
[GitHub Issues](https://github.com/vothmarkus/DTMF-Code-HA/issues) gemeldet werden.
