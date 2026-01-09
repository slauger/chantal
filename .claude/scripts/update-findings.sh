#!/bin/bash
# update-findings.sh
# Reminder-Script das nach Research-Tools (WebFetch, Read, Grep) aufgerufen wird
# Erinnert Claude daran, findings.md zu aktualisieren (2-Action Rule)

set -e

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"
PLANNING_DIR="$PROJECT_DIR/.planning"
COUNTER_FILE="$PLANNING_DIR/.research_action_counter"

# Stelle sicher dass Planning initialisiert ist
if [ ! -d "$PLANNING_DIR" ]; then
    echo "⚠️  .planning/ nicht vorhanden - bitte initialisieren"
    exit 0
fi

# Erstelle Counter-File falls nicht vorhanden
if [ ! -f "$COUNTER_FILE" ]; then
    echo "0" > "$COUNTER_FILE"
fi

# Lese aktuellen Counter
COUNTER=$(cat "$COUNTER_FILE")

# Inkrementiere Counter
COUNTER=$((COUNTER + 1))
echo "$COUNTER" > "$COUNTER_FILE"

# Tool-Name aus Umgebungsvariable oder Argument
TOOL_NAME="${CLAUDE_TOOL_NAME:-Research Tool}"

# Ausgabe je nach Counter
if [ "$COUNTER" -eq 1 ]; then
    echo "📊 Research action 1/2 ($TOOL_NAME)"
elif [ "$COUNTER" -ge 2 ]; then
    echo ""
    echo "📝 2-Action Rule: Zeit für findings.md Update!"
    echo ""
    echo "Nach $COUNTER Research-Aktionen solltest du findings.md aktualisieren mit:"
    echo "  - Neue Erkenntnisse aus der Recherche"
    echo "  - Relevante Code-Beispiele oder Konfigurationen"
    echo "  - Design-Implikationen"
    echo "  - Offene Fragen"
    echo ""
    # Reset counter
    echo "0" > "$COUNTER_FILE"
fi

exit 0
