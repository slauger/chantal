#!/bin/bash
# init-planning.sh
# Initialisiert .planning/ Verzeichnis mit Template-Dateien falls nicht vorhanden
# Wird vom SessionStart Hook aufgerufen

set -e

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"
PLANNING_DIR="$PROJECT_DIR/.planning"

# Prüfe ob .planning bereits existiert
if [ -d "$PLANNING_DIR" ]; then
    # Verzeichnis existiert bereits - prüfe ob Dateien vorhanden sind
    if [ -f "$PLANNING_DIR/task_plan.md" ] && \
       [ -f "$PLANNING_DIR/findings.md" ] && \
       [ -f "$PLANNING_DIR/progress.md" ]; then
        # Alle Dateien vorhanden - nichts zu tun
        echo "✓ Planning files already initialized"
        exit 0
    fi
fi

# Erstelle .planning Verzeichnis falls nicht vorhanden
mkdir -p "$PLANNING_DIR"

# Erstelle task_plan.md falls nicht vorhanden
if [ ! -f "$PLANNING_DIR/task_plan.md" ]; then
    cat > "$PLANNING_DIR/task_plan.md" << 'EOF'
# Task Plan: Chantal - Unified Repository Sync Tool

**Status:** Phase 1 - Recherche - Initialisierung
**Letzte Aktualisierung:** $(date '+%Y-%m-%d %H:%M:%S')

## Übersicht
Entwicklung eines einheitlichen CLI-Tools für vollständige Offline-Spiegelung von APT-, RPM- und PyPI-Repositories.

## Phasen

### Phase 1: Recherche & Tool-Analyse - 🔄 In Arbeit
**Ziel:** Systematische Analyse bestehender Tools (apt-mirror, aptly, reposync, bandersnatch, devpi) um Architektur-Entscheidungen fundiert zu treffen.

**Status:** Initialisierung

Aufgaben:
- [ ] Analyse apt-mirror (APT-Welt)
- [ ] Analyse aptly (APT-Welt)
- [ ] Analyse reposync (RPM-Welt)
- [ ] Analyse bandersnatch (PyPI-Welt)
- [ ] Analyse devpi (PyPI-Welt)
- [ ] Vergleichsmatrix erstellen
- [ ] Lessons Learned dokumentieren

**Nächster Schritt:** Beginne mit Analyse des ersten Tools gemäß PROMPT.md

---

### Phase 2: Anforderungs-Konsolidierung - ⏸️ Wartend
**Ziel:** Anforderungen kategorisieren (Must/Should/Nice) und offene Fragen mit User klären.

**Status:** Wartet auf Abschluss Phase 1

---

### Phase 3: Architektur-Design - ⏸️ Wartend
**Ziel:** Konkrete Architektur-Vorschläge basierend auf Recherche-Ergebnissen.

**Status:** Wartet auf Abschluss Phase 2

---

### Phase 4: Implementierungsplan - ⏸️ Wartend
**Ziel:** MVP-Scope definieren und Iterationsplan erstellen.

**Status:** Wartet auf Abschluss Phase 3

---

### Phase 5: Implementation - ⏸️ Wartend
**Ziel:** Schrittweise Implementation gemäß Plan.

**Status:** Wartet auf Abschluss Phase 4

---

## Offene Fragen
<!-- Füge hier Fragen an den User hinzu mit **FRAGE:** prefix -->

## Entscheidungslog
<!-- Wichtige Entscheidungen werden hier chronologisch dokumentiert -->
- **$(date '+%Y-%m-%d')** Planning-Struktur initialisiert
EOF
    echo "✓ Created task_plan.md"
fi

# Erstelle findings.md falls nicht vorhanden
if [ ! -f "$PLANNING_DIR/findings.md" ]; then
    cat > "$PLANNING_DIR/findings.md" << 'EOF'
# Findings: Unified Repository Sync Tool (RPMSync)

Erstellt: $(date '+%Y-%m-%d %H:%M:%S')

## Recherche-Ergebnisse

<!-- Tool-Analysen werden hier hinzugefügt -->
<!-- Format: siehe repo-architecture-research Skill -->

## Design-Entscheidungen

<!-- Wichtige Design-Entscheidungen mit Begründungen -->

## Code-Snippets & Beispiele

<!-- Relevante Beispiele aus analysierten Tools -->

## Referenzen

<!-- Links zu Dokumentation, Source Code, etc. -->
EOF
    echo "✓ Created findings.md"
fi

# Erstelle progress.md falls nicht vorhanden
if [ ! -f "$PLANNING_DIR/progress.md" ]; then
    cat > "$PLANNING_DIR/progress.md" << 'EOF'
# Progress Log: Unified Repository Sync Tool (RPMSync)

Gestartet: $(date '+%Y-%m-%d %H:%M:%S')

---

## Session $(date '+%Y-%m-%d %H:%M')

**Phase:** Initialisierung
**Ziel:** Planning-Struktur aufsetzen und ersten Workflow verstehen

### Durchgeführte Aktionen
- Planning-Dateien initialisiert
- Skills für Architektur-Recherche und Planning-Workflow konfiguriert

### Nächste Session
- [ ] Ersten Tool-Analyse starten (User-Entscheidung welches Tool zuerst)
- [ ] Recherche-Workflow testen

---
EOF
    echo "✓ Created progress.md"
fi

echo ""
echo "Planning system initialized in $PLANNING_DIR/"
echo "Files: task_plan.md, findings.md, progress.md"
