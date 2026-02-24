#!/bin/bash
# Install git hooks for Ouroboros

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
HOOKS_DIR="$REPO_DIR/.git/hooks"

echo "🔧 Installing git hooks..."

# Create hooks directory if needed
mkdir -p "$HOOKS_DIR"

# Copy pre-push hook
cat > "$HOOKS_DIR/pre-push" << 'HOOK_EOF'
#!/bin/bash
# Ouroboros pre-push hook
# Runs smoke tests before allowing push to remote

set -e

# Check if tests are enabled (can be disabled via env var)
if [ "${OUROBOROS_PRE_PUSH_TESTS}" = "0" ]; then
    echo "⊘ Pre-push tests disabled (OUROBOROS_PRE_PUSH_TESTS=0)"
    exit 0
fi

# Check if tests directory exists
if [ ! -d "tests" ]; then
    echo "⊘ No tests/ directory found, skipping pre-push tests"
    exit 0
fi

echo "🔍 Running pre-push smoke tests..."

# Run smoke tests
if command -v python &> /dev/null; then
    PYTHON_CMD=python
elif command -v python3 &> /dev/null; then
    PYTHON_CMD=python3
else
    echo "⚠️  Python not found, skipping pre-push tests"
    exit 0
fi

# Run pytest with verbose output
if $PYTHON_CMD -m pytest tests/test_smoke.py -v --tb=short; then
    echo "✅ Pre-push tests passed"
    exit 0
else
    echo "❌ Pre-push tests failed"
    echo ""
    echo "To bypass this check (not recommended):"
    echo "  export OUROBOROS_PRE_PUSH_TESTS=0"
    echo "  git push ..."
    echo ""
    echo "Or fix the failing tests and try again."
    exit 1
fi
HOOK_EOF

chmod +x "$HOOKS_DIR/pre-push"
echo "✅ Pre-push hook installed"

echo "🎉 Git hooks installation complete!"
