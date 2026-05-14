#!/bin/bash
# Install dependencies for stock-macro skill (run once)
set -e

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "[stock-macro] Installing Python dependencies..."
pip3 install --quiet fredapi wbgapi yfinance python-dotenv 2>&1 | tail -5

# Create .env template if not exists
ENV_FILE="$SKILL_DIR/data/.env"
if [ ! -f "$ENV_FILE" ]; then
    cat > "$ENV_FILE" <<'EOF'
# Get free FRED API key at: https://fred.stlouisfed.org/docs/api/api_key.html
FRED_API_KEY=your_key_here
EOF
    echo "[stock-macro] Created $ENV_FILE — add your FRED API key."
else
    echo "[stock-macro] .env already exists."
fi

echo "[stock-macro] Setup complete."
