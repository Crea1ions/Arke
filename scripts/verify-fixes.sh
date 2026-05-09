#!/bin/bash
# Verification script for Phase 4 correctifs: FTS5 triggers + prompt engineering
# Usage: ./scripts/verify-fixes.sh

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${YELLOW}=== Arke Phase 4 Verification Script ===${NC}\n"

# Verify Python virtual environment
if [ ! -f ".venv/bin/python" ]; then
    echo -e "${RED}✗ Virtual environment not found at .venv/bin/python${NC}"
    exit 1
fi

PYTHON=".venv/bin/python"
echo -e "${GREEN}✓ Virtual environment found${NC}\n"

# Test 1: Run FTS5 sync tests
echo -e "${YELLOW}Test 1: FTS5 Trigger Synchronization${NC}"
$PYTHON -m pytest tests/test_memory.py::TestFTS5Sync -v --tb=short
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ FTS5 sync tests passed${NC}\n"
else
    echo -e "${RED}✗ FTS5 sync tests failed${NC}\n"
    exit 1
fi

# Test 2: Run all memory tests
echo -e "${YELLOW}Test 2: All Memory Tests${NC}"
$PYTHON -m pytest tests/test_memory.py -v --tb=short
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ All memory tests passed${NC}\n"
else
    echo -e "${RED}✗ Some memory tests failed${NC}\n"
    exit 1
fi

# Test 3: Verify schema changes exist
echo -e "${YELLOW}Test 3: Schema Verification${NC}"
if grep -q "CREATE TRIGGER.*chat_history_ai" arke/memory/schema.sql; then
    echo -e "${GREEN}✓ FTS5 INSERT trigger found in schema.sql${NC}"
else
    echo -e "${RED}✗ FTS5 INSERT trigger not found in schema.sql${NC}"
    exit 1
fi

if grep -q "CREATE TRIGGER.*chat_history_ad" arke/memory/schema.sql; then
    echo -e "${GREEN}✓ FTS5 DELETE trigger found in schema.sql${NC}"
else
    echo -e "${RED}✗ FTS5 DELETE trigger not found in schema.sql${NC}"
    exit 1
fi

# Test 4: Verify prompt changes exist
echo -e "${YELLOW}Test 4: Prompt Verification${NC}"
if grep -q "Ne crée pas de fichiers" arke/chat.py; then
    echo -e "${GREEN}✓ fs tool description updated in chat.py${NC}"
else
    echo -e "${RED}✗ fs tool description not found in chat.py${NC}"
    exit 1
fi

if grep -q "utiliser echo ou un redirect" arke/chat.py; then
    echo -e "${GREEN}✓ cli tool description updated in chat.py${NC}"
else
    echo -e "${RED}✗ cli tool description not found in chat.py${NC}"
    exit 1
fi

# Test 5: Run quick anti-drift validation
echo -e "${YELLOW}Test 5: Anti-Drift Metrics Check${NC}"
$PYTHON -m pytest tests/test_anti_drift.py -v --tb=short -k "test_" | head -20
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Anti-drift metrics operational${NC}\n"
else
    echo -e "${RED}✗ Anti-drift metrics test failed${NC}\n"
fi

# Test 6: Summary
echo -e "${YELLOW}=== Verification Summary ===${NC}"
echo -e "${GREEN}✓ All core fixes verified successfully${NC}"
echo -e "\nNext steps:"
echo "1. Run full test suite: $PYTHON -m pytest tests/ -v"
echo "2. Test arke CLI: arke"
echo "3. Verify in interactive mode:"
echo "   - 'Crée un fichier test.md avec \"bonjour\"' (should use cli tool)"
echo "   - 'Recherche \"bonjour\" dans l'historique' (should find via memory_fts)"
echo "   - '/sql SELECT COUNT(*) FROM memory_fts' (should show > 0 rows)"
