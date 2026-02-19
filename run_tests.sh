#!/bin/bash

# ShowWise Test Runner Script
# Makes it easy to run tests with various options

set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     ShowWise Webapp Test Runner Script     ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════╝${NC}"
echo ""

# Setup virtual environment if it doesn't exist
if [ ! -d "test_env" ]; then
    echo -e "${YELLOW}⚠️  Virtual environment not found. Creating...${NC}"
    python3 -m venv test_env
    echo -e "${GREEN}✓ Virtual environment created${NC}"
    echo ""
fi

# Activate virtual environment
source test_env/bin/activate

# Check if pytest is installed
if ! command -v pytest &> /dev/null; then
    echo -e "${YELLOW}⚠️  pytest not found. Installing test dependencies...${NC}"
    pip install -r requirements-test.txt
fi

# Default to running all tests
TEST_OPTION=${1:-"all"}

case $TEST_OPTION in
    "all")
        echo -e "${GREEN}Running all tests...${NC}"
        pytest test_all_functions.py -v
        ;;
    "quick")
        echo -e "${GREEN}Running quick test (no output)...${NC}"
        pytest test_all_functions.py -q
        ;;
    "coverage")
        echo -e "${GREEN}Running tests with coverage report...${NC}"
        pytest test_all_functions.py --cov=app --cov-report=html -v
        echo -e "${GREEN}✓ Coverage report generated: htmlcov/index.html${NC}"
        ;;
    "auth")
        echo -e "${GREEN}Testing Authentication routes...${NC}"
        pytest test_all_functions.py::TestAuthRoutes -v
        ;;
    "equipment")
        echo -e "${GREEN}Testing Equipment routes...${NC}"
        pytest test_all_functions.py::TestEquipmentRoutes -v
        ;;
    "events")
        echo -e "${GREEN}Testing Event routes...${NC}"
        pytest test_all_functions.py::TestEventRoutes -v
        ;;
    "chat")
        echo -e "${GREEN}Testing Chat routes...${NC}"
        pytest test_all_functions.py::TestChatRoutes -v
        ;;
    "2fa")
        echo -e "${GREEN}Testing 2FA routes...${NC}"
        pytest test_all_functions.py::TestTwoFactorAuth -v
        ;;
    "dashboard")
        echo -e "${GREEN}Testing Dashboard routes...${NC}"
        pytest test_all_functions.py::TestDashboardRoutes -v
        ;;
    "picklist")
        echo -e "${GREEN}Testing Picklist routes...${NC}"
        pytest test_all_functions.py::TestPicklistRoutes -v
        ;;
    "integration")
        echo -e "${GREEN}Testing Integration workflows...${NC}"
        pytest test_all_functions.py::TestIntegration -v
        ;;
    "models")
        echo -e "${GREEN}Testing Database Models...${NC}"
        pytest test_all_functions.py::TestDatabaseModels -v
        ;;
    "debug")
        echo -e "${GREEN}Running tests in debug mode...${NC}"
        pytest test_all_functions.py -vv -s --pdb
        ;;
    "failed")
        echo -e "${GREEN}Re-running last failed tests...${NC}"
        pytest test_all_functions.py --lf -v
        ;;
    "report")
        echo -e "${GREEN}Generating HTML report...${NC}"
        pytest test_all_functions.py -v --html=test_report.html --self-contained-html
        echo -e "${GREEN}✓ Report generated: test_report.html${NC}"
        ;;
    *)
        echo -e "${YELLOW}Unknown option: $TEST_OPTION${NC}"
        echo ""
        echo "Usage: ./run_tests.sh [option]"
        echo ""
        echo "Options:"
        echo "  all          - Run all tests (default)"
        echo "  quick        - Run all tests (quiet output)"
        echo "  coverage     - Run with coverage report"
        echo "  auth         - Test authentication routes"
        echo "  equipment    - Test equipment routes"
        echo "  events       - Test event routes"
        echo "  chat         - Test chat routes"
        echo "  2fa          - Test 2FA routes"
        echo "  dashboard    - Test dashboard routes"
        echo "  picklist     - Test picklist routes"
        echo "  integration  - Test integration workflows"
        echo "  models       - Test database models"
        echo "  debug        - Run with debugger"
        echo "  failed       - Re-run failed tests"
        echo "  report       - Generate HTML report"
        echo ""
        exit 1
        ;;
esac

if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}✓ All tests passed!${NC}"
else
    echo ""
    echo -e "${YELLOW}✗ Some tests failed${NC}"
    exit 1
fi
