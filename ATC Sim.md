## Product Requirements Document

### Automated ATC Simulation System (ATC VectorSim) — Python Edition

---

### 1. Overview

**Objective:**
Develop an automated Air Traffic Control (ATC) simulation system in Python operating within a 3D vectorized airspace. The system simulates thousands of aircraft — each with live position vectors, operational parameters (fuel, souls on board, runway preferences), and mission intents (landing, overflight, diversion) — to model real-world air traffic behavior and demonstrate backend engineering mastery.

**Core Proposition:**

* A single-process, async-driven backend in Python capable of processing thousands of aircraft position updates per second.
* A deterministic physics engine with realistic ATC dynamics (holding patterns, ILS approaches, separation enforcement).
* Durable, replayable event logs persisted entirely in **local PostgreSQL** — zero cloud dependencies.
* Real-time 3D visualization via a three.js WebGL client over WebSocket.
* **Plug-and-play**: `docker compose up` → fully operational system. No external services, no cloud accounts, no API keys.

---

### 2. Key System Goals

* Simulate **thousands of concurrent aircraft** across multiple airspace sectors.
* Achieve **sub-100ms position update cycles** while maintaining determinism and full persistence.
* Prioritize landings dynamically using weighted decision functions (fuel, souls on board, runway constraints).
* Handle both landing and pass-through (overflight) aircraft logically.
* Provide **real-time 3D visualization** via a three.js WebGL interface.
* Provide full event replay and analytics for traffic density, delay, and prioritization metrics.
* **Zero cloud dependencies** — everything runs locally with Docker Compose.

---

### 3. Non-Functional Requirements

| Requirement | Target |
|---|---|
| Scalability | 5,000+ concurrent aircraft in single process |
| Update Latency | Engine tick → WebSocket push ≤ 100ms p95 |
| Throughput | ≥ 50,000 state updates/sec |
| Persistence | All events and state snapshots in PostgreSQL |
| Determinism | Identical seed → identical simulation output |
| Fault Tolerance | Graceful shutdown with state checkpoint; restart resumes |
| Consistency | Strong consistency (single-process, single Postgres) |
| Security | JWT auth on API endpoints |
| Observability | Structured logging, Prometheus metrics endpoint |
| Interoperability | REST API + WebSocket, JSON + MessagePack binary frames |

---

### 4. Core Subsystems

#### 4.1 Event Bus (In-Process)

**Purpose:** Decouple simulation engine from API/persistence layers without external message brokers.

**Implementation:**

* **Pattern:** In-process async pub/sub using Python `asyncio.Queue` channels.
* **Topics:** `aircraft.update`, `aircraft.spawn`, `aircraft.land`, `aircraft.conflict`, `sector.handoff`.
* **Serialization:** `msgpack` for binary WebSocket frames; `dataclasses` + JSON for REST.
* **Backpressure:** Bounded queues with configurable max size; drop-oldest policy for visualization stream.

**Replaces:** Kafka. For a local single-process simulation, an in-process event bus provides the same decoupling without infrastructure overhead.

---

#### 4.2 Simulation Engine

**Purpose:** Deterministic computation of aircraft state, conflict resolution, and landing prioritization.

**Implementation:**

* **Language & Runtime:** Python 3.12+ with `asyncio` event loop.
* **Framework:** Plain Python modules — no heavyweight frameworks for the simulation core.
* **Concurrency Model:** Single-threaded async loop with fixed-timestep ticks. Simulation runs on a dedicated `asyncio.Task` with configurable tick rate (default: 50ms / 20 Hz).
* **NumPy Vectorization:** All position/velocity computations use NumPy structured arrays for cache-friendly batch operations across all aircraft simultaneously.
* **Spatial Index:** Custom **Octree** in Python backed by NumPy arrays for 3D spatial queries. Provides O(log n) neighbor lookups for conflict detection.
* **Determinism:** `numpy.random.Generator` with `SeedSequence` for reproducible random numbers. All floating-point math uses consistent operations (no parallel reordering).

**Core Logic:**

* **Aircraft Classification:** `LANDING`, `OVERFLIGHT`, `HOLDING`, `DIVERTING`, `DEPARTING`, `EMERGENCY`.
* **Landing Priority Function:**
  ```
  priority = (w_fuel * fuel_urgency) + (w_souls * souls_normalized) + (w_emergency * emergency_flag) + (w_wait * hold_time_minutes) + (w_runway * runway_compatibility)
  ```
  Default weights: `w_fuel=0.35, w_souls=0.25, w_emergency=0.30, w_wait=0.05, w_runway=0.05`
* **Conflict Resolution:** Minimum separation enforcement (5 NM horizontal, 1000 ft vertical). When violated → vector aircraft apart using perpendicular offset vectors.
* **Deterministic Tie-breaking:** Hash of aircraft ID string → consistent ordering.
* **Holding Patterns:** Racetrack patterns at assigned fixes with standard 1-minute legs.
* **ILS Approach:** Glideslope interception at 3 degrees, localizer alignment within ±2.5 degrees.

**State Checkpointing:** Periodic snapshots (every 60s) written to PostgreSQL `simulation_snapshots` table. On restart, latest snapshot is loaded and simulation resumes.

---

#### 4.3 Spatial Indexing

**Purpose:** Efficient 3D spatial awareness for conflict detection among thousands of aircraft.

**Implementation:**

* **Octree:** Python implementation using NumPy arrays for node storage. Loose octree variant for efficient updates as aircraft move.
* **Cell Resolution:** 10 km³ cells at the leaf level.
* **Neighbor Queries:** Return all aircraft within a configurable radius (default: 10 NM / ~18.5 km) for conflict checks.
* **Rebuild Strategy:** Full octree rebuild every N ticks (configurable, default: 10) rather than per-aircraft incremental updates — simpler and fast enough with NumPy.

**Performance Target:** Neighbor query for 5,000 aircraft completes in < 5ms.

---

#### 4.4 State Store (PostgreSQL)

**Purpose:** Authoritative persistent state store, event log, and analytics backend.

**Implementation:**

* **Database:** PostgreSQL 16+ running in Docker.
* **Driver:** `asyncpg` for async, high-throughput operations.
* **Schema:**
  * `aircraft_states` — Current state of each aircraft (upsert on tick).
  * `event_log` — Append-only log of all simulation events (spawns, landings, conflicts, diversions).
  * `simulation_snapshots` — Periodic full-state snapshots (JSONB) for replay/resume.
  * `analytics_metrics` — Aggregated KPIs (traffic density, avg delay, throughput) per time bucket.
  * `sectors` — Sector definitions and boundaries.
  * `runways` — Runway configurations and availability.
* **Write Strategy:** Batch inserts using `asyncpg.copy_records_to_table()` for event log (high throughput). Upsert for aircraft states.
* **Indexing:** B-tree on timestamps, BRIN on event_log for time-range queries, GiST for spatial queries on position data.
* **Partitioning:** `event_log` table partitioned by day for efficient archival and queries.

**Replaces:** Redis (hot state) + Kafka (event log) + S3 (archival) + TimescaleDB (analytics). PostgreSQL handles all four roles locally.

---

#### 4.5 API Layer

**Purpose:** Expose control and query endpoints; WebSocket for real-time visualization stream.

**Implementation:**

* **Framework:** **FastAPI** with Uvicorn ASGI server.
* **WebSocket:** FastAPI native WebSocket endpoints. Binary frames using `msgpack` for position updates.
* **Endpoints:**
  * `POST /api/simulation/start` — Start simulation with config parameters.
  * `POST /api/simulation/stop` — Graceful shutdown with state checkpoint.
  * `POST /api/simulation/pause` / `POST /api/simulation/resume` — Pause/resume.
  * `POST /api/aircraft` — Spawn aircraft with parameters.
  * `DELETE /api/aircraft/{id}` — Remove aircraft.
  * `GET /api/aircraft/{id}` — Get single aircraft state.
  * `GET /api/aircraft` — List all aircraft (paginated).
  * `GET /api/sectors` — List sector definitions.
  * `GET /api/analytics` — Get current KPI metrics.
  * `GET /api/analytics/history?from=&to=` — Historical metrics.
  * `POST /api/replay/start` — Start replay from snapshot.
  * `GET /api/replay/snapshots` — List available snapshots.
  * `WS /ws/stream` — Real-time aircraft position stream (msgpack binary frames).
  * `WS /ws/events` — Real-time event stream (JSON).
  * `GET /health` — Health check.
  * `GET /metrics` — Prometheus metrics.
* **Auth:** JWT tokens via `python-jose`. Configurable via environment variable (can be disabled for local dev).
* **CORS:** Open for local development; configurable origins.

---

#### 4.6 Visualization Layer

**Purpose:** Render live 3D simulation in the browser.

**Implementation:**

* **Framework:** Vanilla JavaScript + **three.js** for 3D WebGL rendering.
* **Build:** No build step required — static HTML/JS/CSS served by FastAPI.
* **Data Flow:** WebSocket connection to `/ws/stream` receives msgpack binary frames → decoded in browser → aircraft positions updated via three.js Object3D transforms.
* **Features:**
  * 3D airspace visualization with grid floor and altitude indicators.
  * Aircraft rendered as colored arrows/cones (color = status: green=cruising, yellow=holding, red=emergency, blue=landing).
  * Flight path trails (last N positions as fading lines).
  * Sector boundary wireframes.
  * Runway visualization with ILS approach cones.
  * Aircraft info popup on click (callsign, altitude, speed, fuel, status).
  * Camera controls: orbit, pan, zoom (three.js OrbitControls).
  * Dashboard overlay: aircraft count, avg delay, conflicts active, simulation time, tick rate.
  * Interpolation between server updates for smooth 60fps rendering.
* **Fallback:** If WebSocket disconnects, UI shows "Disconnected" overlay and auto-reconnects.

---

#### 4.7 Replay Engine

**Purpose:** Replay past simulation runs from PostgreSQL snapshots and event logs.

**Implementation:**

* **Replay Controller:** Python module that reads events from `event_log` table within a time range and replays them at configurable speed (1x, 2x, 5x, 10x).
* **API:** Replay is exposed via the same WebSocket stream — client doesn't need to know if it's live or replay.
* **Validation:** SHA-256 checksum of simulation state at snapshot points; replay must produce matching checksums for determinism verification.

---

#### 4.8 Analytics

**Purpose:** Compute and expose operational KPIs.

**Implementation:**

* **Computation:** In-process aggregation computed during simulation ticks. Metrics accumulated in memory, flushed to `analytics_metrics` table every 10 seconds.
* **KPIs:**
  * Total aircraft active / landed / diverted / in conflict.
  * Average holding time before landing.
  * Average fuel remaining at landing.
  * Traffic density per sector.
  * Conflict events per minute.
  * Landing throughput (aircraft/hour).
* **Dashboards:** Metrics exposed at `/metrics` in Prometheus format; optional Grafana dashboard via Docker Compose.

---

### 5. Data Model

**Aircraft Entity:**

```python
@dataclass
class Aircraft:
    id: str                          # Unique identifier (e.g., "UAL1234")
    callsign: str                    # ATC callsign
    aircraft_type: str               # e.g., "B737", "A320"
    status: AircraftStatus           # LANDING, OVERFLIGHT, HOLDING, etc.
    position: np.ndarray             # [x, y, z] in km (float64)
    velocity: np.ndarray             # [vx, vy, vz] in km/s
    heading: float                   # degrees (0-360)
    altitude_ft: float               # feet MSL
    speed_knots: float               # knots
    vertical_speed_fpm: float        # feet per minute
    fuel_remaining_kg: float         # kilograms
    fuel_burn_rate_kg_s: float       # kg per second
    souls_on_board: int              # passenger + crew count
    origin: str                      # ICAO code
    destination: str                 # ICAO code
    assigned_runway: Optional[str]   # assigned runway ID
    sector_id: str                   # current sector
    spawn_time: float                # simulation timestamp
    priority_score: float            # computed landing priority
    intent: AircraftIntent           # LAND, OVERFLY, DIVERT
    holding_fix: Optional[str]       # assigned holding fix
    holding_start_time: Optional[float]
```

**Sector Entity:**

```python
@dataclass
class Sector:
    id: str
    name: str
    bounds_min: np.ndarray           # [x, y, z] min corner
    bounds_max: np.ndarray           # [x, y, z] max corner
    capacity: int                    # max aircraft
    active: bool
```

**Runway Entity:**

```python
@dataclass
class Runway:
    id: str
    airport_icao: str
    heading: float
    length_m: float
    ils_available: bool
    position: np.ndarray             # [x, y, z] threshold
    approach_heading: float
    occupied: bool
    occupant_id: Optional[str]
```

---

### 6. Realism Considerations

* **Physics:** Realistic turn rates, climb/descent profiles per aircraft type. Bank angle limits. Speed envelope enforcement (Vmin to Vmo).
* **Holding Patterns:** Standard racetrack at assigned fixes. Right turns, 1-minute legs, 1000ft vertical separation between stacked holds.
* **ILS Approach:** Aircraft intercept localizer at assigned heading, capture glideslope at ~3 degrees. Go-around if not stabilized by decision altitude.
* **Fuel Modeling:** Continuous burn rate with increased consumption during holds. Diversion triggered below minimum fuel threshold.
* **Pass-through Traffic:** Overflight aircraft maintain altitude and heading, transit sectors without landing intent.
* **Communications Jitter:** Optional configurable delay (0-500ms) on state updates to simulate realistic ATC communication lag.
* **Weather (stretch):** Optional wind vectors affecting ground speed and approach stability.

---

### 7. Observability

* **Logging:** Python `logging` module with structured JSON output (via `python-json-logger`).
* **Metrics:** Prometheus client (`prometheus-client`) exposing at `/metrics`: tick duration histogram, aircraft count gauge, event rates, WebSocket client count.
* **Profiling:** `cProfile` / `py-spy` for hot-path analysis during load tests.

---

### 8. Testing & Validation

* **Unit Tests:** `pytest` for all core modules (physics, octree, priority, conflict resolution).
* **Property Tests:** `hypothesis` for fuzzing physics engine and priority calculations.
* **Integration Tests:** `pytest` + `asyncpg` against real PostgreSQL (via Docker).
* **Determinism Tests:** Run simulation twice with same seed, compare state checksums at every snapshot point.
* **Load Tests:** Custom Python script spawning N aircraft and measuring tick performance.
* **CI:** GitHub Actions with PostgreSQL service container.

---

### 9. Security & Access Control

* JWT authentication on API endpoints (configurable, disabled by default for local dev).
* No TLS in local mode (handled by reverse proxy in production).
* API rate limiting via `slowapi`.

---

### 10. Project Structure

```
ATC_sim/
├── docker-compose.yml              # PostgreSQL + app
├── Dockerfile                       # Python app container
├── pyproject.toml                   # Dependencies and project config
├── README.md                        # Setup and usage guide
├── .env.example                     # Environment variable template
├── alembic/                         # Database migrations
│   ├── alembic.ini
│   ├── env.py
│   └── versions/
├── src/
│   ├── __init__.py
│   ├── main.py                      # FastAPI app entry point
│   ├── config.py                    # Settings (pydantic-settings)
│   ├── models/
│   │   ├── __init__.py
│   │   ├── aircraft.py              # Aircraft dataclass + enums
│   │   ├── sector.py                # Sector dataclass
│   │   ├── runway.py                # Runway dataclass
│   │   └── events.py                # Event types
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── simulation.py            # Main simulation loop
│   │   ├── physics.py               # Aircraft motion + physics
│   │   ├── priority.py              # Landing priority function
│   │   ├── conflict.py              # Conflict detection + resolution
│   │   ├── holding.py               # Holding pattern logic
│   │   ├── approach.py              # ILS approach logic
│   │   └── spawner.py               # Aircraft spawning logic
│   ├── spatial/
│   │   ├── __init__.py
│   │   └── octree.py                # Octree spatial index
│   ├── events/
│   │   ├── __init__.py
│   │   └── bus.py                   # In-process event bus
│   ├── persistence/
│   │   ├── __init__.py
│   │   ├── database.py              # asyncpg connection pool
│   │   ├── repositories.py          # CRUD operations
│   │   └── migrations.py            # Schema setup
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes.py                # REST endpoints
│   │   ├── websocket.py             # WebSocket handlers
│   │   ├── schemas.py               # Pydantic request/response models
│   │   └── auth.py                  # JWT auth middleware
│   ├── analytics/
│   │   ├── __init__.py
│   │   └── metrics.py               # KPI computation + Prometheus
│   └── replay/
│       ├── __init__.py
│       └── controller.py            # Replay engine
├── client/
│   ├── index.html                   # Main visualization page
│   ├── css/
│   │   └── style.css
│   └── js/
│       ├── app.js                   # Main application
│       ├── scene.js                 # three.js scene setup
│       ├── aircraft.js              # Aircraft 3D objects
│       ├── websocket.js             # WebSocket client + msgpack decode
│       ├── ui.js                    # Dashboard overlay + controls
│       └── lib/
│           ├── three.min.js         # three.js library
│           ├── OrbitControls.js     # Camera controls
│           └── msgpack.min.js       # MessagePack decoder
├── tests/
│   ├── __init__.py
│   ├── conftest.py                  # Fixtures (DB, engine)
│   ├── test_physics.py
│   ├── test_octree.py
│   ├── test_priority.py
│   ├── test_conflict.py
│   ├── test_simulation.py
│   ├── test_api.py
│   └── test_replay.py
└── scripts/
    ├── seed_airports.py             # Seed airport/runway data
    └── load_test.py                 # Load testing script
```

---

### 11. Deliverables

* Complete Python backend with simulation engine, API, persistence, analytics, and replay.
* PostgreSQL schema with migrations (Alembic).
* three.js 3D visualization client (no build step).
* Docker Compose stack for one-command setup.
* Test suite (unit + integration + determinism).
* Load testing script.
* README with setup instructions.

---

### 12. Success Criteria

* `docker compose up` → working system with visualization accessible at `http://localhost:8000`.
* Simulation runs 2,000+ aircraft at 20 Hz tick rate on a standard dev machine.
* Aircraft visually move in real-time in the 3D WebGL client.
* Landing priority correctly orders aircraft by fuel/souls/emergency.
* Conflict detection prevents aircraft from violating minimum separation.
* Events persisted in PostgreSQL; replay produces identical visualization.
* All tests pass.

---

### 13. Tech Stack Summary

| Component | Technology |
|---|---|
| Language | Python 3.12+ |
| Web Framework | FastAPI + Uvicorn |
| Database | PostgreSQL 16 (Docker) |
| DB Driver | asyncpg |
| Migrations | Alembic |
| Spatial Math | NumPy |
| Serialization | msgpack (WebSocket), JSON (REST) |
| 3D Visualization | three.js (vanilla JS) |
| Auth | python-jose (JWT) |
| Metrics | prometheus-client |
| Logging | python-json-logger |
| Testing | pytest + hypothesis |
| Containerization | Docker + Docker Compose |
| Settings | pydantic-settings |

---

### 14. Implementation Phases

**Phase 1 — Foundation (Commits 1-10):**
Project structure, Docker Compose, PostgreSQL schema, data models, config.

**Phase 2 — Core Engine (Commits 11-25):**
Physics engine, octree spatial index, simulation loop, conflict detection, landing priority, holding patterns, ILS approach.

**Phase 3 — Persistence & API (Commits 26-35):**
Database repositories, event logging, state snapshots, FastAPI endpoints, WebSocket streaming.

**Phase 4 — Visualization (Commits 36-45):**
three.js client, aircraft rendering, camera controls, dashboard overlay, WebSocket integration.

**Phase 5 — Polish & Testing (Commits 46-55):**
Replay engine, analytics, comprehensive tests, determinism validation, load testing.

**Phase 6 — Documentation & Hardening (Commits 56-60):**
README, .env.example, final bug fixes, CI config.
