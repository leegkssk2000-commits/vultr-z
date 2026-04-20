cat > /home/z/z/bootstrap_missing.sh <<'SH'
set -e
BASE=/home/z/z

# 디렉터리
mkdir -p "$BASE/config" "$BASE/ensembles" "$BASE/logs"

# config/app.yml
[ -f "$BASE/config/app.yml" ] || cat > "$BASE/config/app.yml" <<'YML'
server:
  host: 127.0.0.1
  port: 8000
  workers: 2
db:
  path: /home/z/z/db/z.sqlite
  timeout: 30
scheduler:
  enabled: true
  timezone: UTC
YML

# config/features.yml
[ -f "$BASE/config/features.yml" ] || cat > "$BASE/config/features.yml" <<'YML'
dashboard:
  enabled: true
datasets_api:
  enabled: false
logging:
  level: INFO
YML

# ensembles/*.yml
if [ ! -f "$BASE/ensembles/tiers.yml" ]; then
cat > "$BASE/ensembles/tiers.yml" <<'YML'
tiers:
  - name: basic
    max_positions: 5
    capital: 10000
  - name: pro
    max_positions: 20
    capital: 100000
YML
fi

if [ ! -f "$BASE/ensembles/regimes.yml" ]; then
cat > "$BASE/ensembles/regimes.yml" <<'YML'
regimes:
  - name: bull
    volatility: low
  - name: bear
    volatility: high
YML
fi

if [ ! -f "$BASE/ensembles/risk.yml" ]; then
cat > "$BASE/ensembles/risk.yml" <<'YML'
risk:
  max_drawdown: 0.2
  stop_loss: 0.03
  take_profit: 0.06
YML
fi

if [ ! -f "$BASE/ensembles/markets.yml" ]; then
cat > "$BASE/ensembles/markets.yml" <<'YML'
markets:
  - symbol: BTCUSDT
    venue: BINANCE
  - symbol: ETHUSDT
    venue: BINANCE
YML
fi
