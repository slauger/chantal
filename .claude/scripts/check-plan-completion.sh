#!/bin/bash
# check-plan-completion.sh
# Wird vom Stop Hook aufgerufen
# Prüft ob task_plan.md aktualisiert werden sollte und erinnert an progress.md

set -e

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"
PLANNING_DIR="$PROJECT_DIR/.planning"
TASK_PLAN="$PLANNING_DIR/task_plan.md"

# Prüfe ob Planning existiert
if [ ! -d "$PLANNING_DIR" ]; then
    # Kein Planning aktiv - nichts zu tun
    exit 0
fi

if [ ! -f "$TASK_PLAN" ]; then
    # Kein task_plan.md vorhanden
    exit 0
fi

echo ""
echo "🔍 Planning Check bei Session-Ende"
echo ""

# Prüfe auf offene Tasks ([ ] Syntax)
OPEN_TASKS=$(grep -c "^- \[ \]" "$TASK_PLAN" 2>/dev/null || echo "0")

# Prüfe auf abgeschlossene Tasks in dieser Session (könnte über Git Diff gemacht werden, hier vereinfacht)
COMPLETED_TASKS=$(grep -c "^- \[x\]" "$TASK_PLAN" 2>/dev/null || echo "0")

# Prüfe auf offene Fragen
OPEN_QUESTIONS=$(grep -c "\*\*FRAGE:\*\*" "$TASK_PLAN" 2>/dev/null || echo "0")

# Status-Ausgabe
echo "📋 Task Plan Status:"
echo "   - $COMPLETED_TASKS erledigte Tasks"
echo "   - $OPEN_TASKS offene Tasks"
if [ "$OPEN_QUESTIONS" -gt 0 ]; then
    echo "   - ⚠️  $OPEN_QUESTIONS offene Fragen an User"
fi
echo ""

# Erinnerungen
echo "💡 Session-Ende Checkliste:"
echo ""
echo "   1. Aktualisiere task_plan.md:"
echo "      - Markiere abgeschlossene Tasks: [x]"
echo "      - Aktualisiere Phase-Status (🔄/✅/⏸️)"
echo "      - Update 'Letzte Aktualisierung' Timestamp"
echo ""
echo "   2. Erstelle Session-Eintrag in progress.md:"
echo "      - Was wurde gemacht?"
echo "      - Welche Ergebnisse?"
echo "      - Was kommt als nächstes?"
echo ""

# Prüfe ob task_plan.md heute aktualisiert wurde
LAST_MODIFIED=$(stat -f "%Sm" -t "%Y-%m-%d" "$TASK_PLAN" 2>/dev/null || date +%Y-%m-%d)
TODAY=$(date +%Y-%m-%d)

if [ "$LAST_MODIFIED" != "$TODAY" ]; then
    echo "   ⚠️  task_plan.md wurde heute noch nicht aktualisiert"
    echo ""
fi

# Hinweis auf offene Fragen
if [ "$OPEN_QUESTIONS" -gt 0 ]; then
    echo "   🔔 Es gibt $OPEN_QUESTIONS offene Fragen - stelle sie dem User bevor du stoppst!"
    echo ""
fi

exit 0
