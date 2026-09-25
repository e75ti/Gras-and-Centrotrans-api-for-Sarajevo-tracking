import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import requests
from pydantic import BaseModel, ValidationError
from sqlalchemy import Float, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

# -- Logging --
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s]: %(message)s")
logger = logging.getLogger("gras-tracker")

# -- Configuration (Now using Docker Secrets!) --
db_user = os.getenv("DB_USER", "gras")
db_host = os.getenv("DB_HOST", "db")
db_name = os.getenv("DB_NAME", "gras")
password_file = os.getenv("DB_PASSWORD_FILE", "/run/secrets/db_password")

# Safely read the password from the injected file
try:
    db_password = Path(password_file).read_text().strip()
except FileNotFoundError:
    logger.warning("Secret file not found. Falling back to default password.")
    db_password = "password"

DB_URL = f"postgresql+psycopg://{db_user}:{db_password}@{db_host}:5432/{db_name}"
INTERVAL = int(os.getenv("SCRAPE_INTERVAL_SECONDS", "30"))
API_URL = "https://javniprevozks.ba/public-api/public/lines/vehicle-positions"
HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Linux; Android 17) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7871.187 Mobile Safari/537.36",
    "Host": "javniprevozks.ba"
}

# -- SQLAlchemy 2.0 Typed Schema --
class Base(DeclarativeBase):
    pass

class VehicleLog(Base):
    __tablename__ = "vehicle_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    recorded_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    vehicle_code: Mapped[str] = mapped_column(String(10))
    vehicle_type: Mapped[str] = mapped_column(String(20))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)

engine = create_engine(DB_URL)
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine)

# -- Pydantic V2 Data Validation --
class RawVehicle(BaseModel):
    vehicle_code: str | None = None
    vehicle_type_id: int = 0
    operator_id: int
    latitude: float
    longitude: float

def classify_vehicle(raw: RawVehicle) -> dict[str, str | float] | None:
    # Filter out non-GRAS operators early
    if raw.operator_id != 1 or not raw.vehicle_code:
        return None

    code = raw.vehicle_code.strip()

    # Python 3.10+ Structural Pattern Matching
    match raw.vehicle_type_id:
        case 4:
            v_type = "Tram"
        case 3:
            v_type = "Trolleybus"
        case 2:
            v_type = "Bus"
        case 1:
            v_type = "Minibus"
        case 0 if code.isdigit():
            # Inferred classifications based on fleet numbering
            v_type = "Trolleybus" if len(code) == 2 else "Tram"
        case _:
            v_type = "Unknown"

    return {"code": code, "type": v_type, "lat": raw.latitude, "lon": raw.longitude}

# -- Main loop --
def run_scraper() -> None:
    logger.info(f"Started modern scraper. Polling GRAS API every {INTERVAL}s.")

    # Using requests.Session() to pool TCP connections efficiently
    with requests.Session() as session_http:
        session_http.headers.update(HEADERS)
        while True:
            try:
                response = session_http.post(API_URL, json={"limit": 2000}, timeout=10.0)
                response.raise_for_status()
                data = response.json()
            except requests.RequestException as e:
                logger.error(f"API fetch failed: {e}")
                time.sleep(INTERVAL)
                continue

            with SessionLocal() as db_session:
                logs_added = 0
                try:
                    for item in data:
                        try:
                            # Pydantic V2 parsing
                            raw = RawVehicle.model_validate(item)
                            enriched = classify_vehicle(raw)

                            if enriched:
                                db_session.add(VehicleLog(
                                    vehicle_code=str(enriched["code"]),
                                    vehicle_type=str(enriched["type"]),
                                    latitude=float(enriched["lat"]),
                                    longitude=float(enriched["lon"])
                                ))
                                logs_added += 1
                        except ValidationError:
                            continue

                    db_session.commit()
                    logger.info(f"Successfully logged {logs_added} active GRAS vehicles.")

                except Exception as e:
                    db_session.rollback()
                    logger.error(f"Database insertion failed: {e}")

            time.sleep(INTERVAL)

if __name__ == "__main__":
    run_scraper()
