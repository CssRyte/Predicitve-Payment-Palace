# Predictive Payment Palace (Flask MVP)

## Quick start

```bash
cd predictive-payment-palace
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # edit MySQL credentials
```

### MySQL

Create the app user and load schema + seed:

```bash
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS predictive_payment_palace; CREATE USER IF NOT EXISTS 'palace_app'@'localhost' IDENTIFIED BY 'your_password'; GRANT ALL ON predictive_payment_palace.* TO 'palace_app'@'localhost'; FLUSH PRIVILEGES;"
mysql -u palace_app -p predictive_payment_palace < database/schema.sql
mysql -u palace_app -p predictive_payment_palace < database/seed.sql
```

Verify:

```bash
curl http://127.0.0.1:5000/test-database
```

### Run

```bash
flask --app app run --debug
# or: python app.py
```

Open `/` for login, `/prep` for live forecasts (Wednesday dinner defaults to ~85 fried chicken plates → 91 recommended prep).

### Tests

```bash
pytest
```

## Architecture

- **Forecasting** (`services/forecasting.py`): weekday-segmented trailing averages + 6% prep buffer.
- **Conversion** (`services/conversion.py`): servings → supplier packages via recipes and case sizes.
- **Ollama** (`services/ollama_service.py`): narrative summary only; numbers come from Python.
