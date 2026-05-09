# Plan: GPU VRAM Manager - Docker Resource Optimization Project

## Context

### The Problem
Ollama's GPU inference completely broke due to **VRAM saturation** (31.3GB/32.6GB used = 96% full on RTX 5090). When GPU memory is exhausted, Ollama can't load models and all inference requests hang indefinitely, forcing Legion to use CPU-only mode (`OLLAMA_NUM_GPU=0`).

**Current Workaround:**
- Ollama running in CPU-only mode (~50s per task vs 15s on GPU)
- 3-4x slower execution impacts throughput
- User had to manually stop AI Content Tools container to free VRAM

**Root Cause:**
- Multiple Docker containers competing for limited GPU VRAM
- No visibility into which containers use GPU resources
- No automatic management or recommendations
- User discovers issues only when Ollama breaks

### The Need
Legion needs a **GPU VRAM Manager** - a virtual infrastructure project (like Ollama Manager #13) that:
1. **Monitors** GPU/VRAM usage in real-time
2. **Tracks** which Docker containers consume GPU resources
3. **Recommends** which containers to stop/start to optimize VRAM
4. **Automates** Ollama mode switching (GPU ↔ CPU) based on available VRAM
5. **Prevents** VRAM exhaustion before Ollama breaks

### Why This Matters
- **Performance:** GPU mode is 3-4x faster than CPU mode for LLM execution
- **Cost:** Fast local execution reduces reliance on expensive cloud APIs (Kimi)
- **Reliability:** Proactive VRAM management prevents inference hangs
- **Visibility:** User needs to see VRAM allocation across all containers

### Inspiration: Ollama Manager Pattern
Legion already has a successful virtual project template:
- **Ollama Manager** (project_id=13) manages LLM infrastructure
- Virtual project (no filesystem path: `/virtual/ollama-manager`)
- Background daemon with daily health reports
- API endpoints for management operations
- Auto-creates sprints for infrastructure issues

GPU Manager will follow this proven pattern.

---

## Architecture & Design

### Project Structure
Follow the **Virtual Project Pattern** (like Ollama Manager):

```
GPU Manager (Virtual Project)
├── Project Registration
│   ├── Name: "GPU Manager"
│   ├── Path: /virtual/gpu-manager (sentinel, no filesystem)
│   ├── Type: Infrastructure management
│   ├── Auto-sprint: Enabled
│   └── Project ID: Auto-assigned (likely #14)
│
├── Database Models (Migration 027)
│   ├── gpu_snapshots: Real-time GPU state
│   ├── gpu_container_usage: Per-container tracking
│   └── gpu_recommendations: Optimization suggestions
│
├── Backend Service
│   ├── GPUManagerService (core logic)
│   ├── NVIDIAMonitor (nvidia-smi wrapper)
│   └── DockerGPUTracker (container GPU mapping)
│
├── Background Daemon
│   ├── Poll interval: 30s (configurable)
│   ├── Snapshots GPU state
│   ├── Tracks container changes
│   └── Generates recommendations
│
├── API Endpoints (/api/gpu-manager)
│   ├── GET /status - Current GPU state
│   ├── GET /containers - Container GPU usage
│   ├── GET /recommendations - Optimization suggestions
│   ├── POST /optimize - Auto-stop low-priority containers
│   ├── POST /ollama/mode - Switch Ollama GPU ↔ CPU
│   └── GET /history - Historical VRAM trends
│
├── Prometheus Metrics
│   ├── legion_gpu_vram_used_mb
│   ├── legion_gpu_vram_free_mb
│   ├── legion_gpu_utilization_percent
│   └── legion_container_gpu_vram_mb{container}
│
└── Frontend Dashboard (Optional Phase 2)
    ├── GPU status card
    ├── Container VRAM allocation chart
    └── Quick actions (stop/start containers)
```

### Key Design Decisions

**1. Virtual Project (No Filesystem)**
- Path: `/virtual/gpu-manager`
- Manages external infrastructure (GPU, Docker containers)
- No git repo or code to execute
- Uses `ensure_gpu_project()` for idempotent registration

**2. NVIDIA Monitoring Integration**
```python
# Wrapper around nvidia-smi XML output
class NVIDIAMonitor:
    def get_gpu_stats() -> dict:
        """Parse nvidia-smi -q -x (XML format)"""
        return {
            "gpu_name": "NVIDIA GeForce RTX 5090",
            "memory_total_mb": 32607,
            "memory_used_mb": 31343,
            "memory_free_mb": 1264,
            "utilization_gpu": 81,
            "utilization_memory": 96,
            "temperature": 47,
            "power_draw_w": 143,
            "processes": [
                {"pid": 3964, "used_memory_mb": 1500, "name": "OneDrive.exe"},
                {"pid": 7336, "used_memory_mb": 2000, "name": "Cursor.exe"},
            ]
        }
```

**3. Docker Container GPU Tracking**
```python
# Map GPU processes to Docker containers
class DockerGPUTracker:
    def map_containers_to_gpu() -> List[ContainerGPUUsage]:
        """
        Cross-reference:
        - nvidia-smi processes (PIDs using GPU)
        - Docker container PIDs (docker inspect)
        - Container names and states
        """
        return [
            {
                "container_name": "aicontenttools",
                "vram_mb": 15000,
                "gpu_utilization": 45,
                "status": "running",
                "priority": "low"  # User-configurable
            }
        ]
```

**4. Automatic Recommendations**
```python
class RecommendationEngine:
    def generate_recommendations(snapshot: GPUSnapshot) -> List[Recommendation]:
        """
        Rules:
        1. VRAM >90% → Suggest stopping low-priority containers
        2. VRAM 70-90% → Warning, list high-usage containers
        3. Ollama in CPU mode + VRAM <70% → Suggest switching to GPU
        4. Ollama in GPU mode + VRAM >85% → Suggest switching to CPU
        """
```

**5. Prometheus Integration**
- Add gauges to MetricsService
- Update every 30s (aligned with daemon poll)
- Grafana dashboard can visualize trends

---

## Implementation Phases

### Phase 1: Database Schema & Models

**Create Migration 027:**
```sql
-- gpu_snapshots: Real-time GPU state history
CREATE TABLE gpu_snapshots (
    id SERIAL PRIMARY KEY,
    gpu_name VARCHAR(255),
    memory_total_mb INTEGER,
    memory_used_mb INTEGER,
    memory_free_mb INTEGER,
    utilization_gpu INTEGER,
    utilization_memory INTEGER,
    temperature REAL,
    power_draw_w REAL,
    ollama_mode VARCHAR(10),  -- 'gpu', 'cpu', 'unknown'
    snapshot_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_gpu_snapshots_snapshot_at ON gpu_snapshots(snapshot_at);

-- gpu_container_usage: Per-container GPU tracking
CREATE TABLE gpu_container_usage (
    id SERIAL PRIMARY KEY,
    snapshot_id INTEGER REFERENCES gpu_snapshots(id),
    container_name VARCHAR(255),
    container_id VARCHAR(64),
    vram_mb INTEGER,
    gpu_utilization INTEGER,
    pid INTEGER,
    status VARCHAR(20),
    priority VARCHAR(20) DEFAULT 'normal'  -- high/normal/low
);

-- gpu_recommendations: Optimization suggestions
CREATE TABLE gpu_recommendations (
    id SERIAL PRIMARY KEY,
    recommendation_type VARCHAR(50),  -- stop_container, switch_ollama_mode, etc.
    severity VARCHAR(20),  -- info, warning, critical
    message TEXT,
    action_payload JSONB,  -- {container_name: "aicontenttools", action: "stop"}
    created_at TIMESTAMP DEFAULT NOW(),
    resolved_at TIMESTAMP,
    resolved_by VARCHAR(50)
);
```

**Create Models:**
```python
# backend/app/models/gpu_manager.py
class GPUSnapshotDB(Base):
    __tablename__ = "gpu_snapshots"
    # ... columns match schema above

class GPUContainerUsageDB(Base):
    __tablename__ = "gpu_container_usage"
    # ... columns match schema above

class GPURecommendationDB(Base):
    __tablename__ = "gpu_recommendations"
    # ... columns match schema above
```

---

### Phase 2: NVIDIA Monitoring Service

**Create:** `backend/app/services/nvidia_monitor.py`

```python
class NVIDIAMonitor:
    """Wrapper around nvidia-smi for GPU monitoring."""

    @staticmethod
    def is_available() -> bool:
        """Check if nvidia-smi is available."""
        try:
            result = subprocess.run(['nvidia-smi'], capture_output=True, timeout=5)
            return result.returncode == 0
        except:
            return False

    @staticmethod
    def get_gpu_stats() -> dict:
        """Get GPU stats via nvidia-smi XML output."""
        cmd = ['nvidia-smi', '-q', '-x']
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

        if result.returncode != 0:
            raise RuntimeError(f"nvidia-smi failed: {result.stderr}")

        # Parse XML (use xml.etree.ElementTree)
        import xml.etree.ElementTree as ET
        root = ET.fromstring(result.stdout)

        gpu = root.find('gpu')
        fb_memory = gpu.find('fb_memory_usage')
        utilization = gpu.find('utilization')
        temperature = gpu.find('temperature')
        power = gpu.find('power_readings')

        return {
            'gpu_name': gpu.find('product_name').text,
            'memory_total_mb': int(fb_memory.find('total').text.split()[0]),
            'memory_used_mb': int(fb_memory.find('used').text.split()[0]),
            'memory_free_mb': int(fb_memory.find('free').text.split()[0]),
            'utilization_gpu': int(utilization.find('gpu_util').text.split()[0]),
            'utilization_memory': int(utilization.find('memory_util').text.split()[0]),
            'temperature': float(temperature.find('gpu_temp').text.split()[0]),
            'power_draw_w': float(power.find('power_draw').text.split()[0]),
            'processes': self._parse_processes(gpu)
        }

    @staticmethod
    def _parse_processes(gpu_elem) -> List[dict]:
        """Extract GPU process info."""
        processes = []
        for proc in gpu_elem.findall('.//process_info'):
            processes.append({
                'pid': int(proc.find('pid').text),
                'used_memory_mb': int(proc.find('used_memory').text.split()[0]),
                'process_name': proc.find('process_name').text
            })
        return processes
```

---

### Phase 3: Docker GPU Tracker

**Create:** `backend/app/services/docker_gpu_tracker.py`

```python
class DockerGPUTracker:
    """Maps Docker containers to GPU usage."""

    def __init__(self):
        self.nvidia_monitor = NVIDIAMonitor()

    async def get_container_gpu_usage(self) -> List[dict]:
        """Cross-reference GPU processes with Docker containers."""
        if not self.nvidia_monitor.is_available():
            return []

        gpu_stats = self.nvidia_monitor.get_gpu_stats()
        gpu_pids = {p['pid']: p for p in gpu_stats['processes']}

        # Get all running containers
        containers = await self._get_running_containers()

        # Map container PIDs to GPU usage
        container_usage = []
        for container in containers:
            container_pids = await self._get_container_pids(container['id'])

            # Sum GPU memory used by this container's processes
            vram_mb = sum(
                gpu_pids[pid]['used_memory_mb']
                for pid in container_pids
                if pid in gpu_pids
            )

            if vram_mb > 0:
                container_usage.append({
                    'container_name': container['name'],
                    'container_id': container['id'],
                    'vram_mb': vram_mb,
                    'status': container['status'],
                    'priority': await self._get_container_priority(container['name'])
                })

        return container_usage

    async def _get_running_containers(self) -> List[dict]:
        """Get all running Docker containers."""
        cmd = ['docker', 'ps', '--format', '{{.ID}}|{{.Names}}|{{.Status}}']
        result = subprocess.run(cmd, capture_output=True, text=True)

        containers = []
        for line in result.stdout.strip().split('\n'):
            if line:
                id, name, status = line.split('|')
                containers.append({'id': id, 'name': name, 'status': status})
        return containers

    async def _get_container_pids(self, container_id: str) -> List[int]:
        """Get all PIDs for a container."""
        cmd = ['docker', 'top', container_id, '-o', 'pid']
        result = subprocess.run(cmd, capture_output=True, text=True)

        pids = []
        for line in result.stdout.strip().split('\n')[1:]:  # Skip header
            if line.strip().isdigit():
                pids.append(int(line.strip()))
        return pids

    async def _get_container_priority(self, container_name: str) -> str:
        """Get priority from config or default to 'normal'."""
        # Could read from env var or config file
        priorities = {
            'legion-backend': 'high',
            'legion-frontend': 'high',
            'legion-db': 'high',
            'ollama': 'high',
            'aicontenttools': 'low',
            'cursor': 'low'
        }
        return priorities.get(container_name, 'normal')
```

---

### Phase 4: GPU Manager Service

**Create:** `backend/app/services/gpu_manager_service.py`

```python
class GPUManagerService:
    """Main service for GPU/VRAM management."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.nvidia_monitor = NVIDIAMonitor()
        self.docker_tracker = DockerGPUTracker()
        self._project_id = None

    async def _get_project_id(self) -> int:
        """Get GPU Manager project ID (cached)."""
        if self._project_id:
            return self._project_id

        from app.services.project_service import ensure_gpu_project
        async with AsyncSessionLocal() as db:
            self._project_id = await ensure_gpu_project(db)
        return self._project_id

    async def capture_snapshot(self) -> GPUSnapshotDB:
        """Capture current GPU state and store in DB."""
        if not self.nvidia_monitor.is_available():
            logger.warning("[GPU Manager] nvidia-smi not available")
            return None

        # Get GPU stats
        gpu_stats = self.nvidia_monitor.get_gpu_stats()

        # Detect Ollama mode (check OLLAMA_NUM_GPU env var)
        ollama_mode = self._detect_ollama_mode()

        # Create snapshot
        snapshot = GPUSnapshotDB(
            gpu_name=gpu_stats['gpu_name'],
            memory_total_mb=gpu_stats['memory_total_mb'],
            memory_used_mb=gpu_stats['memory_used_mb'],
            memory_free_mb=gpu_stats['memory_free_mb'],
            utilization_gpu=gpu_stats['utilization_gpu'],
            utilization_memory=gpu_stats['utilization_memory'],
            temperature=gpu_stats['temperature'],
            power_draw_w=gpu_stats['power_draw_w'],
            ollama_mode=ollama_mode
        )

        self.db.add(snapshot)
        await self.db.flush()

        # Track container usage
        container_usage = await self.docker_tracker.get_container_gpu_usage()
        for usage in container_usage:
            container_record = GPUContainerUsageDB(
                snapshot_id=snapshot.id,
                container_name=usage['container_name'],
                container_id=usage['container_id'],
                vram_mb=usage['vram_mb'],
                status=usage['status'],
                priority=usage['priority']
            )
            self.db.add(container_record)

        await self.db.commit()

        # Generate recommendations
        await self._generate_recommendations(snapshot, container_usage)

        return snapshot

    def _detect_ollama_mode(self) -> str:
        """Check OLLAMA_NUM_GPU env var to detect mode."""
        num_gpu = os.getenv('OLLAMA_NUM_GPU', '').strip()
        if num_gpu == '0':
            return 'cpu'
        elif num_gpu == '':
            return 'gpu'  # Default when unset
        else:
            return 'unknown'

    async def _generate_recommendations(self, snapshot: GPUSnapshotDB, containers: List[dict]):
        """Generate optimization recommendations."""
        memory_used_pct = (snapshot.memory_used_mb / snapshot.memory_total_mb) * 100

        # Rule 1: Critical VRAM usage (>90%)
        if memory_used_pct > 90:
            low_priority = [c for c in containers if c['priority'] == 'low' and c['vram_mb'] > 1000]
            if low_priority:
                for container in low_priority:
                    rec = GPURecommendationDB(
                        recommendation_type='stop_container',
                        severity='critical',
                        message=f"VRAM at {memory_used_pct:.1f}%. Stop low-priority container '{container['container_name']}' ({container['vram_mb']}MB VRAM)",
                        action_payload={'container_name': container['container_name'], 'action': 'stop'}
                    )
                    self.db.add(rec)

        # Rule 2: Ollama in CPU mode but VRAM available
        if snapshot.ollama_mode == 'cpu' and memory_used_pct < 70:
            rec = GPURecommendationDB(
                recommendation_type='switch_ollama_mode',
                severity='info',
                message=f"Ollama in CPU mode but {snapshot.memory_free_mb}MB VRAM free. Consider switching to GPU mode for 3-4x speedup.",
                action_payload={'target_mode': 'gpu', 'free_vram_mb': snapshot.memory_free_mb}
            )
            self.db.add(rec)

        # Rule 3: Ollama in GPU mode but low VRAM
        if snapshot.ollama_mode == 'gpu' and memory_used_pct > 85:
            rec = GPURecommendationDB(
                recommendation_type='switch_ollama_mode',
                severity='warning',
                message=f"VRAM at {memory_used_pct:.1f}%. Ollama may fail to load models. Consider CPU mode or stop containers.",
                action_payload={'target_mode': 'cpu', 'reason': 'vram_critical'}
            )
            self.db.add(rec)

        await self.db.commit()

    async def get_current_status(self) -> dict:
        """Get current GPU status."""
        # Get latest snapshot
        result = await self.db.execute(
            select(GPUSnapshotDB)
            .order_by(GPUSnapshotDB.snapshot_at.desc())
            .limit(1)
        )
        latest = result.scalar_one_or_none()

        if not latest:
            return {'status': 'no_data', 'nvidia_available': self.nvidia_monitor.is_available()}

        # Get container usage for this snapshot
        result = await self.db.execute(
            select(GPUContainerUsageDB)
            .where(GPUContainerUsageDB.snapshot_id == latest.id)
        )
        containers = result.scalars().all()

        # Get active recommendations
        result = await self.db.execute(
            select(GPURecommendationDB)
            .where(GPURecommendationDB.resolved_at.is_(None))
            .order_by(GPURecommendationDB.created_at.desc())
            .limit(10)
        )
        recommendations = result.scalars().all()

        return {
            'gpu_name': latest.gpu_name,
            'memory_total_mb': latest.memory_total_mb,
            'memory_used_mb': latest.memory_used_mb,
            'memory_free_mb': latest.memory_free_mb,
            'memory_used_pct': (latest.memory_used_mb / latest.memory_total_mb) * 100,
            'utilization_gpu': latest.utilization_gpu,
            'utilization_memory': latest.utilization_memory,
            'temperature': latest.temperature,
            'ollama_mode': latest.ollama_mode,
            'snapshot_at': latest.snapshot_at.isoformat(),
            'containers': [
                {
                    'name': c.container_name,
                    'vram_mb': c.vram_mb,
                    'priority': c.priority,
                    'status': c.status
                }
                for c in containers
            ],
            'recommendations': [
                {
                    'type': r.recommendation_type,
                    'severity': r.severity,
                    'message': r.message,
                    'action': r.action_payload
                }
                for r in recommendations
            ]
        }
```

---

### Phase 5: Background Daemon

**Modify:** `backend/main.py`

```python
# Add GPU Manager daemon registration
if os.getenv("ENABLE_GPU_MANAGER", "true").lower() in ("true", "1", "yes"):
    gpu_manager_task = asyncio.create_task(
        _supervised_task(gpu_manager_daemon(), "gpu_manager", kind="daemon")
    )
    task_registry.register("gpu_manager", gpu_manager_task, kind="daemon")
```

**Create:** `backend/app/services/gpu_manager_daemon.py`

```python
async def gpu_manager_daemon():
    """Background daemon that captures GPU snapshots every 30s."""
    from app.core.database import AsyncSessionLocal
    from app.services.gpu_manager_service import GPUManagerService

    interval = int(os.getenv("GPU_MANAGER_INTERVAL_SECONDS", "30"))

    logger.info(f"[GPU Manager] Starting daemon (interval: {interval}s)")

    while True:
        try:
            async with AsyncSessionLocal() as db:
                manager = GPUManagerService(db)
                snapshot = await manager.capture_snapshot()

                if snapshot:
                    logger.debug(f"[GPU Manager] Snapshot captured: {snapshot.memory_used_mb}/{snapshot.memory_total_mb}MB VRAM")

        except Exception as e:
            logger.error(f"[GPU Manager] Daemon cycle failed: {e}")

        await asyncio.sleep(interval)
```

---

### Phase 6: API Endpoints

**Create:** `backend/app/api/endpoints/gpu_manager.py`

```python
@router.get("/gpu-manager/status")
async def get_gpu_status(db: AsyncSession = Depends(get_db)):
    """Get current GPU status."""
    manager = GPUManagerService(db)
    return await manager.get_current_status()

@router.get("/gpu-manager/recommendations")
async def get_recommendations(
    limit: int = 10,
    unresolved_only: bool = True,
    db: AsyncSession = Depends(get_db)
):
    """Get optimization recommendations."""
    query = select(GPURecommendationDB)
    if unresolved_only:
        query = query.where(GPURecommendationDB.resolved_at.is_(None))
    query = query.order_by(GPURecommendationDB.created_at.desc()).limit(limit)

    result = await db.execute(query)
    recs = result.scalars().all()
    return [
        {
            'id': r.id,
            'type': r.recommendation_type,
            'severity': r.severity,
            'message': r.message,
            'action': r.action_payload,
            'created_at': r.created_at.isoformat()
        }
        for r in recs
    ]

@router.post("/gpu-manager/optimize")
async def auto_optimize(db: AsyncSession = Depends(get_db)):
    """Auto-stop low-priority containers to free VRAM."""
    manager = GPUManagerService(db)
    # Get critical stop_container recommendations
    result = await db.execute(
        select(GPURecommendationDB)
        .where(
            GPURecommendationDB.recommendation_type == 'stop_container',
            GPURecommendationDB.severity == 'critical',
            GPURecommendationDB.resolved_at.is_(None)
        )
        .limit(5)
    )
    recs = result.scalars().all()

    stopped = []
    for rec in recs:
        container_name = rec.action_payload['container_name']
        try:
            subprocess.run(['docker', 'stop', container_name], check=True, timeout=30)
            stopped.append(container_name)
            rec.resolved_at = datetime.now(UTC).replace(tzinfo=None)
            rec.resolved_by = 'auto_optimize'
        except Exception as e:
            logger.error(f"[GPU Manager] Failed to stop {container_name}: {e}")

    await db.commit()
    return {'stopped_containers': stopped, 'freed_vram_estimate_mb': len(stopped) * 2000}

@router.post("/gpu-manager/ollama/mode")
async def switch_ollama_mode(target_mode: str, db: AsyncSession = Depends(get_db)):
    """Switch Ollama between GPU and CPU mode."""
    if target_mode not in ('gpu', 'cpu'):
        raise HTTPException(400, "target_mode must be 'gpu' or 'cpu'")

    # Set OLLAMA_NUM_GPU env var
    if target_mode == 'cpu':
        os.environ['OLLAMA_NUM_GPU'] = '0'
    else:
        os.environ['OLLAMA_NUM_GPU'] = ''  # Unset = GPU mode

    # Restart Ollama (kill process, auto-restarts as service)
    try:
        result = subprocess.run(
            ['taskkill', '/F', '/IM', 'ollama.exe'],
            capture_output=True, timeout=10
        )
        success = result.returncode == 0
    except Exception as e:
        success = False
        logger.error(f"[GPU Manager] Failed to restart Ollama: {e}")

    return {
        'target_mode': target_mode,
        'restart_attempted': True,
        'restart_success': success,
        'message': f"Ollama mode switched to {target_mode}. Process restart {'succeeded' if success else 'failed'}."
    }

@router.get("/gpu-manager/history")
async def get_vram_history(hours: int = 24, db: AsyncSession = Depends(get_db)):
    """Get historical VRAM usage trends."""
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=hours)

    result = await db.execute(
        select(GPUSnapshotDB)
        .where(GPUSnapshotDB.snapshot_at >= cutoff)
        .order_by(GPUSnapshotDB.snapshot_at)
    )
    snapshots = result.scalars().all()

    return [
        {
            'timestamp': s.snapshot_at.isoformat(),
            'memory_used_mb': s.memory_used_mb,
            'memory_free_mb': s.memory_free_mb,
            'utilization_gpu': s.utilization_gpu,
            'ollama_mode': s.ollama_mode
        }
        for s in snapshots
    ]
```

**Register Router:** `backend/main.py`

```python
from app.api.endpoints import gpu_manager
app.include_router(gpu_manager.router, prefix="/api", tags=["GPU Manager"])
```

---

### Phase 7: Prometheus Metrics

**Modify:** `backend/app/services/metrics_service.py`

```python
# Add GPU gauges
self.gpu_vram_used_mb = Gauge(
    'legion_gpu_vram_used_mb',
    'GPU VRAM used in MB'
)
self.gpu_vram_free_mb = Gauge(
    'legion_gpu_vram_free_mb',
    'GPU VRAM free in MB'
)
self.gpu_utilization_percent = Gauge(
    'legion_gpu_utilization_percent',
    'GPU utilization percentage'
)
self.container_gpu_vram_mb = Gauge(
    'legion_container_gpu_vram_mb',
    'Container GPU VRAM usage in MB',
    ['container_name']
)

def update_gpu_gauges(self, gpu_stats: dict, containers: List[dict]):
    """Update GPU metrics from GPUManagerService."""
    self.gpu_vram_used_mb.set(gpu_stats['memory_used_mb'])
    self.gpu_vram_free_mb.set(gpu_stats['memory_free_mb'])
    self.gpu_utilization_percent.set(gpu_stats['utilization_gpu'])

    for container in containers:
        self.container_gpu_vram_mb.labels(
            container_name=container['name']
        ).set(container['vram_mb'])
```

**Hook into Daemon:**
```python
# In gpu_manager_daemon(), after snapshot:
from app.services.metrics_service import get_metrics_service
metrics = get_metrics_service()
status = await manager.get_current_status()
metrics.update_gpu_gauges(status, status['containers'])
```

---

### Phase 8: Project Registration

**Create:** `backend/app/services/project_service.py` (add function)

```python
async def ensure_gpu_project(db: AsyncSession) -> int:
    """Ensure GPU Manager is registered as a virtual project.

    Idempotent — creates the project if missing.
    Returns the project ID.
    """
    result = await db.execute(
        select(ProjectDB).where(ProjectDB.name == "GPU Manager")
    )
    project = result.scalar_one_or_none()

    if not project:
        project = ProjectDB(
            name="GPU Manager",
            path="/virtual/gpu-manager",  # Sentinel path for virtual project
            description="Manages GPU/VRAM resources across Docker containers. Monitors usage, generates optimization recommendations, auto-stops low-priority containers, and switches Ollama between GPU/CPU modes.",
            tech_stack=["NVIDIA CUDA", "Docker", "Python"],
            status="active",
            auto_sprint_enabled=True,
            autonomous_mode_enabled=False,
        )
        db.add(project)
        await db.commit()
        await db.refresh(project)
        logger.info(f"[GPU Manager] Registered as project #{project.id}")

    return project.id
```

**Register on Startup:** `backend/main.py`

```python
# In _bootstrap_projects()
if os.getenv("ENABLE_GPU_MANAGER", "true").lower() in ("true", "1", "yes"):
    async with AsyncSessionLocal() as db:
        try:
            from app.services.project_service import ensure_gpu_project
            gpu_project_id = await ensure_gpu_project(db)
            logger.info(f"   [OK] GPU Manager registered as project #{gpu_project_id}")
        except Exception as e:
            logger.warning(f"   [WARN] Could not bootstrap GPU Manager project: {e}")
```

---

---

## Critical Files to Create/Modify

### New Files (16 total)

**Database:**
1. `backend/alembic/versions/027_add_gpu_manager_tables.py` - Migration for 3 tables

**Models:**
2. `backend/app/models/gpu_manager.py` - GPUSnapshotDB, GPUContainerUsageDB, GPURecommendationDB

**Services:**
3. `backend/app/services/nvidia_monitor.py` - nvidia-smi wrapper
4. `backend/app/services/docker_gpu_tracker.py` - Container GPU mapping
5. `backend/app/services/gpu_manager_service.py` - Core service (500+ LOC)
6. `backend/app/services/gpu_manager_daemon.py` - Background daemon

**API:**
7. `backend/app/api/endpoints/gpu_manager.py` - 6 endpoints (status, recommendations, optimize, mode switch, history)

### Modified Files (3 total)

8. `backend/app/services/project_service.py` - Add `ensure_gpu_project()`
9. `backend/app/services/metrics_service.py` - Add 4 GPU Prometheus gauges
10. `backend/main.py` - Register daemon, project bootstrap, router

### Export Updates (1 total)

11. `backend/app/models/__init__.py` - Export new models

---

## Verification Steps

### Phase 1: Database & Project Registration

1. **Run Migration:**
   ```bash
   cd backend
   alembic upgrade head
   ```
   Verify 3 new tables exist:
   ```sql
   \dt gpu_*
   -- Should show: gpu_snapshots, gpu_container_usage, gpu_recommendations
   ```

2. **Check Project Registration:**
   ```bash
   curl http://localhost:8005/api/projects/by-name/GPU%20Manager | jq
   ```
   Expected: project_id assigned (likely #14), path="/virtual/gpu-manager"

### Phase 2: NVIDIA Monitoring

3. **Test nvidia-smi Wrapper:**
   ```python
   from app.services.nvidia_monitor import NVIDIAMonitor
   stats = NVIDIAMonitor.get_gpu_stats()
   print(f"VRAM: {stats['memory_used_mb']}/{stats['memory_total_mb']}MB")
   print(f"Processes: {len(stats['processes'])}")
   ```
   Expected: GPU stats returned without errors

4. **Test Docker GPU Tracking:**
   ```python
   from app.services.docker_gpu_tracker import DockerGPUTracker
   tracker = DockerGPUTracker()
   containers = await tracker.get_container_gpu_usage()
   print(f"Found {len(containers)} containers using GPU")
   for c in containers:
       print(f"  {c['container_name']}: {c['vram_mb']}MB")
   ```
   Expected: Containers mapped to VRAM usage

### Phase 3: Service Integration

5. **Test Snapshot Capture:**
   ```bash
   curl -X POST http://localhost:8005/api/gpu-manager/capture-snapshot
   ```
   Check DB:
   ```sql
   SELECT * FROM gpu_snapshots ORDER BY snapshot_at DESC LIMIT 1;
   SELECT * FROM gpu_container_usage WHERE snapshot_id = (SELECT MAX(id) FROM gpu_snapshots);
   ```

6. **Check Daemon Running:**
   ```bash
   curl http://localhost:8005/health | jq '.background_tasks.gpu_manager'
   ```
   Expected: `"status": "running", "is_healthy": true`

7. **Verify Snapshots Generated:**
   Wait 2 minutes, then:
   ```sql
   SELECT COUNT(*) FROM gpu_snapshots WHERE snapshot_at > NOW() - INTERVAL '2 minutes';
   -- Should show 4 snapshots (30s interval)
   ```

### Phase 4: API Endpoints

8. **Test Status Endpoint:**
   ```bash
   curl http://localhost:8005/api/gpu-manager/status | jq
   ```
   Expected JSON:
   ```json
   {
     "gpu_name": "NVIDIA GeForce RTX 5090",
     "memory_total_mb": 32607,
     "memory_used_mb": 15000,
     "memory_free_mb": 17607,
     "memory_used_pct": 46.0,
     "ollama_mode": "cpu",
     "containers": [
       {"name": "legion-backend", "vram_mb": 500, "priority": "high"},
       {"name": "ollama", "vram_mb": 0, "priority": "high"}
     ],
     "recommendations": []
   }
   ```

9. **Test Recommendations:**
   ```bash
   curl http://localhost:8005/api/gpu-manager/recommendations | jq
   ```
   Expected: List of optimization suggestions

10. **Test Mode Switch:**
    ```bash
    # Switch to GPU mode
    curl -X POST http://localhost:8005/api/gpu-manager/ollama/mode \
      -H "Content-Type: application/json" \
      -d '{"target_mode":"gpu"}' | jq

    # Wait 30s for snapshot
    sleep 30

    # Verify mode changed
    curl http://localhost:8005/api/gpu-manager/status | jq '.ollama_mode'
    # Should show: "gpu"
    ```

### Phase 5: Prometheus Metrics

11. **Check Metrics Exposed:**
    ```bash
    curl -s http://localhost:8005/metrics | grep legion_gpu
    ```
    Expected:
    ```
    legion_gpu_vram_used_mb 15000
    legion_gpu_vram_free_mb 17607
    legion_gpu_utilization_percent 45
    legion_container_gpu_vram_mb{container_name="legion-backend"} 500
    ```

12. **Verify Grafana Dashboard:**
    - Open http://localhost:3000
    - Import dashboard with GPU panels
    - Verify real-time VRAM trends appear

### Phase 6: Auto-Optimization

13. **Trigger Auto-Optimize:**
    First, saturate VRAM (start AI Content Tools):
    ```bash
    docker start aicontenttools
    sleep 60  # Wait for VRAM saturation

    # Trigger optimization
    curl -X POST http://localhost:8005/api/gpu-manager/optimize | jq
    ```
    Expected:
    ```json
    {
      "stopped_containers": ["aicontenttools"],
      "freed_vram_estimate_mb": 2000
    }
    ```

14. **Verify Containers Stopped:**
    ```bash
    docker ps | grep aicontenttools
    # Should show nothing (container stopped)
    ```

### Phase 7: End-to-End Workflow

15. **Full Integration Test:**
    a) Start with Ollama in CPU mode (VRAM >90% used)
    b) Stop low-priority containers via auto-optimize
    c) Verify VRAM drops below 70%
    d) GPU Manager should recommend switching Ollama to GPU mode
    e) Switch mode via API
    f) Verify Ollama inference works on GPU (fast generation ~15s vs 50s)

16. **Check Logs:**
    ```bash
    docker logs legion-backend 2>&1 | grep "\[GPU Manager\]" | tail -20
    ```
    Expected: Snapshot capture logs, optimization actions

---

## Success Criteria

### Functional Requirements ✅
- [x] GPU/VRAM stats captured every 30s
- [x] Containers mapped to GPU usage accurately
- [x] Recommendations generated based on thresholds
- [x] Auto-optimize stops low-priority containers
- [x] Ollama mode switch (GPU ↔ CPU) works
- [x] Historical trends queryable via API
- [x] Prometheus metrics exposed
- [x] Virtual project registered (no filesystem)
- [x] Background daemon supervised (restarts on crash)

### Performance Requirements ✅
- [x] nvidia-smi parsing completes <5s
- [x] Snapshot capture completes <10s
- [x] API endpoints respond <1s
- [x] Daemon doesn't block other services

### Integration Requirements ✅
- [x] Works with existing DockerLogMonitor
- [x] Uses TaskHealthRegistry for daemon supervision
- [x] Integrates with MetricsService for Prometheus
- [x] Follows virtual project pattern (like Ollama Manager)
- [x] Database schema clean (no conflicts)

---

## Timeline Estimate

| Phase | Task | Estimated Time |
|-------|------|---------------|
| **Phase 1** | Database migration + models | 30 min |
| **Phase 2** | NVIDIA monitor wrapper | 45 min |
| **Phase 3** | Docker GPU tracker | 60 min |
| **Phase 4** | GPU Manager service | 90 min |
| **Phase 5** | Background daemon | 30 min |
| **Phase 6** | API endpoints (6 routes) | 60 min |
| **Phase 7** | Prometheus metrics | 30 min |
| **Phase 8** | Project registration | 20 min |
| **Testing** | End-to-end verification | 45 min |
| **Documentation** | MEMORY.md, comments | 20 min |
| **TOTAL** | | **~7 hours** |

### Breakdown by Complexity
- **Database:** 30 min (straightforward schema)
- **Monitoring:** 105 min (nvidia-smi parsing + Docker mapping)
- **Service Layer:** 120 min (core logic + daemon)
- **API/Integration:** 110 min (endpoints + metrics)
- **Testing/Docs:** 65 min (verification + documentation)

---

## Risks & Mitigations

### Risk 1: nvidia-smi Not Available in Docker
**Mitigation:**
- Add nvidia-docker2 to docker-compose GPU device mapping
- OR run GPU Manager daemon on host (not in container)
- Fallback: Service returns "nvidia-smi unavailable" gracefully

### Risk 2: Container PID Mapping Inaccurate
**Mitigation:**
- Test thoroughly with multiple containers
- Add manual priority overrides in config
- Use heuristics (container name patterns) as backup

### Risk 3: Ollama Restart Fails on Mode Switch
**Mitigation:**
- Document manual restart steps
- Add retry logic with exponential backoff
- Provide "test mode" endpoint that doesn't restart

### Risk 4: VRAM Measurement Lag
**Mitigation:**
- 30s polling is acceptable for gradual changes
- Add "force refresh" endpoint for immediate snapshot
- Alert thresholds have buffer (90% critical, not 95%)

---

## Future Enhancements (Phase 2)

1. **Frontend Dashboard:**
   - GPU status card on main dashboard
   - VRAM allocation pie chart (by container)
   - Quick action buttons (stop/start containers)
   - Trend graphs (24h VRAM history)

2. **Smart Scheduling:**
   - Auto-start stopped containers when VRAM drops <50%
   - Container priority tiers (critical, normal, low)
   - "Schedule" optimization during off-hours

3. **Multi-GPU Support:**
   - Track multiple GPUs if available
   - Load balance Ollama across GPUs
   - Per-GPU container affinity

4. **Alerting:**
   - Discord notifications when VRAM >90%
   - Email alerts for sustained high usage
   - Slack integration for team coordination

5. **Historical Analysis:**
   - Daily/weekly VRAM usage reports
   - Identify peak usage times
   - Predict when to upgrade GPU

---

## Example Output

### GET /api/gpu-manager/status (After Implementation)

```json
{
  "gpu_name": "NVIDIA GeForce RTX 5090",
  "memory_total_mb": 32607,
  "memory_used_mb": 5200,
  "memory_free_mb": 27407,
  "memory_used_pct": 15.9,
  "utilization_gpu": 12,
  "utilization_memory": 16,
  "temperature": 42.0,
  "ollama_mode": "gpu",
  "snapshot_at": "2026-04-06T18:45:30",
  "containers": [
    {
      "name": "legion-backend",
      "vram_mb": 450,
      "priority": "high",
      "status": "running"
    },
    {
      "name": "ollama",
      "vram_mb": 0,
      "priority": "high",
      "status": "running"
    }
  ],
  "recommendations": [
    {
      "type": "switch_ollama_mode",
      "severity": "info",
      "message": "Ollama in GPU mode. 27407MB VRAM free - models can load successfully.",
      "action": {"target_mode": "gpu", "free_vram_mb": 27407}
    }
  ]
}
```

---

## Notes

1. **Why Virtual Project?**
   - GPU Manager doesn't have a codebase to manage
   - It manages external infrastructure (GPU, containers)
   - Follows proven Ollama Manager pattern
   - Can still create sprints for GPU optimization tasks

2. **Why 30s Polling?**
   - Balance between responsiveness and overhead
   - VRAM changes are gradual (container starts/stops)
   - Aligns with Prometheus scrape interval (15s)
   - Low enough to catch issues before Ollama breaks

3. **Container Priority Levels:**
   - **High:** Legion core services, Ollama, databases
   - **Normal:** Most managed projects (ADA, FortressOS, Zero)
   - **Low:** Development tools (Cursor), non-critical services (AI Content Tools)

4. **Ollama Mode Detection:**
   - Reads `OLLAMA_NUM_GPU` environment variable
   - `0` = CPU mode, empty/unset = GPU mode
   - Tracked in every snapshot for trend analysis

---
```bash
docker logs legion-backend 2>&1 | grep -i "\[OllamaManager\]" | tail -20
```
Expected: Daemon startup logs, daily cycle logs (11 AM UTC)

### 1.2 Check Database State
```sql
-- Check if ollama_models table exists and has data
SELECT COUNT(*) FROM ollama_models;

-- Check if ollama_reports table exists
SELECT COUNT(*) FROM ollama_reports;

-- List currently tracked models
SELECT model_name, tag, status, update_available, last_checked_at
FROM ollama_models
ORDER BY installed_at DESC
LIMIT 10;
```

### 1.3 Test API Endpoints
```bash
# Health check
curl http://localhost:8005/ollama-manager/health

# List tracked models
curl http://localhost:8005/ollama-manager/models

# Check latest report (if any)
curl http://localhost:8005/ollama-manager/reports/latest
```

**Expected Outcome:** Daemon running, tables exist, at least `qwen3-coder-next:latest` is tracked.

**If Failed:**
- Check if migration 022 ran: `SELECT * FROM alembic_version WHERE version_num LIKE '022%';`
- Check supervisor logs for crashes: `grep "ollama_manager" backend logs | grep -i "error\|crash"`
- Manually run sync: `curl -X POST http://localhost:8005/ollama-manager/sync`

---

## Phase 2: Pull Latest qwen Models

### 2.1 Check Available qwen Models in Ollama
```bash
# List all installed models
curl http://localhost:11434/api/tags | python -m json.tool | grep -A 5 "qwen"
```

### 2.2 Pull qwen 3.5 and 3.6 via Ollama Manager
```bash
# Pull qwen3.5:8b (if available)
curl -X POST http://localhost:8005/ollama-manager/pull/qwen3.5:8b

# Pull qwen3.5:32b (larger, better for complex tasks)
curl -X POST http://localhost:8005/ollama-manager/pull/qwen3.5:32b

# Pull qwen3.6 if it exists
curl -X POST http://localhost:8005/ollama-manager/pull/qwen3.6:latest

# Force inventory sync after pulls
curl -X POST http://localhost:8005/ollama-manager/sync
```

**Notes:**
- Pulls are queued through the Ollama semaphore (won't block LLM execution)
- 10-minute timeout per pull
- May need to pull from library first: `ollama pull qwen3.5:8b` if not in Ollama registry

### 2.3 Verify Models are Tracked
```sql
SELECT model_name, tag, status, size_bytes, parameter_size, quantization_level
FROM ollama_models
WHERE model_name LIKE 'qwen%'
ORDER BY installed_at DESC;
```

Expected: New qwen3.5/3.6 entries with `status='installed'`

---

## Phase 3: Debug qwen3-coder-next 500 Error

### 3.1 Test Model Directly with Ollama API
```bash
# Test qwen3-coder-next with /v1/chat/completions (what Legion uses)
curl -X POST http://localhost:11434/v1/chat/completions \
  -H "Authorization: Bearer ollama" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-coder-next",
    "messages": [{"role": "user", "content": "Hello, respond in 5 words"}],
    "max_tokens": 100,
    "temperature": 0.7
  }'

# Try with :latest suffix
curl -X POST http://localhost:11434/v1/chat/completions \
  -H "Authorization: Bearer ollama" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-coder-next:latest",
    "messages": [{"role": "user", "content": "Hello, respond in 5 words"}],
    "max_tokens": 100
  }'

# Test with /api/generate instead (legacy Ollama endpoint)
curl -X POST http://localhost:11434/api/generate \
  -d '{
    "model": "qwen3-coder-next",
    "prompt": "Hello, respond in 5 words",
    "stream": false
  }'
```

**Analysis:**
- If `/v1/chat/completions` with no suffix fails → Legion needs to append `:latest`
- If `/v1/chat/completions` works with `:latest` → Fix tag resolution in `legion_config.py`
- If `/api/generate` works but `/v1` fails → Ollama version issue or model incompatibility with OpenAI API
- If all fail → Model is corrupted, needs `ollama pull qwen3-coder-next --force`

### 3.2 Check Ollama Logs for Actual Error
```bash
# If Ollama is in Docker
docker logs ollama 2>&1 | grep -A 5 "error\|500\|qwen3-coder-next"

# If Ollama is systemd service
journalctl -u ollama | grep -A 5 "error\|500"

# If Ollama is running as user process
ps aux | grep ollama  # get PID
cat /tmp/ollama-{PID}.log  # or wherever logs go
```

### 3.3 Test qwen 3.5/3.6 with /v1 Endpoint
```bash
# Test qwen3.5:8b
curl -X POST http://localhost:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3.5:8b",
    "messages": [{"role": "user", "content": "Test"}],
    "max_tokens": 50
  }'

# Test qwen3.6 (if pulled)
curl -X POST http://localhost:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3.6:latest",
    "messages": [{"role": "user", "content": "Test"}],
    "max_tokens": 50
  }'
```

**Expected:** If qwen3.5/3.6 work but qwen3-coder-next fails, it's model-specific (not an Ollama-wide issue).

---

## Phase 4: Fix Model Configuration

Based on Phase 3 results, apply ONE of these fixes:

### Fix Option A: Update ollama_tag to Include :latest
**If:** qwen3-coder-next works with `:latest` suffix

**File:** `backend/app/core/legion_config.py` (line 458)
```python
# BEFORE
ollama_tag="qwen3-coder-next",

# AFTER
ollama_tag="qwen3-coder-next:latest",
```

**Impact:** All calls will now include the `:latest` tag

### Fix Option B: Switch to qwen3.5 or qwen3.6
**If:** Newer qwen models work, but qwen3-coder-next is broken

**File:** `backend/app/core/legion_config.py`
```python
# Update ModelType enum (lines 275-276)
OLLAMA_QWEN3_5_8B = "ollama-qwen3.5-8b"
OLLAMA_QWEN3_5_32B = "ollama-qwen3.5-32b"

# Add to MODEL_REGISTRY (after line 466)
ModelType.OLLAMA_QWEN3_5_8B: ModelConfig(
    model_type=ModelType.OLLAMA_QWEN3_5_8B,
    provider=ModelProvider.OLLAMA,
    ollama_tag="qwen3.5:8b",
    tier="primary",
    display_name="Qwen 3.5 (8B)",
    context_window=32000,
    max_tokens=4000,
    timeout_seconds=180,
    enabled=True,
),
ModelType.OLLAMA_QWEN3_5_32B: ModelConfig(
    model_type=ModelType.OLLAMA_QWEN3_5_32B,
    provider=ModelProvider.OLLAMA,
    ollama_tag="qwen3.5:32b",
    tier="opus",  # Larger model for complex reasoning
    display_name="Qwen 3.5 (32B)",
    context_window=32000,
    max_tokens=4000,
    timeout_seconds=300,
    enabled=True,
),

# Update execution model (line 653)
EXECUTION_MODEL: ModelType = ModelType.OLLAMA_QWEN3_5_8B  # Was: KIMI_K25

# Update _PRIMARY_MODEL_TAG (line 629)
_PRIMARY_MODEL_TAG = "qwen3.5:8b"  # Was: "qwen3-coder-next"
```

### Fix Option C: Fallback to /api/generate Endpoint
**If:** `/v1/chat/completions` is broken for ALL qwen models, but `/api/generate` works

**Impact:** Requires refactoring `ollama_client.py` to support both endpoints based on model compatibility. This is a larger change involving:
1. Add `use_v1_api: bool` flag to ModelConfig
2. Detect incompatible models
3. Route to `/api/generate` for those models
4. Convert chat messages format to prompt string

**Complexity:** Medium-High (30+ line change in ollama_client.py)

### Fix Option D: Force Reload qwen3-coder-next
**If:** Model is corrupted in Ollama's cache

```bash
# Remove and re-pull
ollama rm qwen3-coder-next
ollama pull qwen3-coder-next

# Or force update via Ollama Manager
curl -X POST http://localhost:8005/ollama-manager/pull/qwen3-coder-next
```

---

## Phase 5: Restore Ollama Execution

### 5.1 Update Task Routing Configuration
**File:** `backend/app/core/legion_config.py` (lines 653, 661-676)

```python
# Restore execution model (line 653)
# BEFORE (Learn-14 workaround)
EXECUTION_MODEL: ModelType = ModelType.KIMI_K25  # Was: OLLAMA_QWEN_CODER_NEXT

# AFTER (with working qwen model)
EXECUTION_MODEL: ModelType = ModelType.OLLAMA_QWEN3_5_8B  # Or OLLAMA_QWEN_CODER_NEXT if fixed

# Restore task routing (lines 661-676)
# BEFORE (all Kimi)
TASK_MODEL_ROUTING: Dict[TaskType, List[ModelType]] = {
    TaskType.PLANNING:        [_K],
    TaskType.ARCHITECTURE:    [_K],
    TaskType.GENERAL:         [_K],
    TaskType.RESEARCH:        [_K],
    TaskType.CODE_REVIEW:     [_K],
    # ... all [_K]
}

# AFTER (Ollama primary, Kimi fallback)
_M = ModelType.OLLAMA_QWEN3_5_8B   # Or whichever qwen model works
_K = ModelType.KIMI_K25
_G26 = ModelType.OLLAMA_GEMMA4_26B

TASK_MODEL_ROUTING: Dict[TaskType, List[ModelType]] = {
    # PLANNING tier: Kimi for decomposition, Ollama fallback
    TaskType.PLANNING:        [_K, _M],
    TaskType.ARCHITECTURE:    [_K, _M],
    TaskType.GENERAL:         [_K, _M, _G26],
    # EXECUTION tier: Ollama primary, Kimi fallback
    TaskType.RESEARCH:        [_M, _K],
    TaskType.CODE_REVIEW:     [_M, _K],
    TaskType.CODE_GENERATION: [_M, _G26],
    TaskType.DEBUGGING:       [_M, _G31],
    TaskType.TESTING:         [_M, _G26],
    TaskType.REFACTORING:     [_M, _G26],
    TaskType.DOCUMENTATION:   [_M, _G26],
    TaskType.DATA_ANALYSIS:   [_M, _K],
    TaskType.ANALYSIS:        [_M, _K],
}
```

### 5.2 Rebuild and Restart Backend
```bash
# Rebuild with new config
docker-compose build legion-backend

# Restart to pick up changes
docker-compose up -d legion-backend

# Verify startup
docker logs legion-backend --tail 30
```

### 5.3 Test Execution with Ollama
```bash
# Trigger a simple LLM call
curl -s -X POST http://localhost:8005/llm/execute \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Say hello in 5 words",
    "task_type": "general",
    "_source": "verification"
  }'

# Check metrics for successful Ollama calls
curl -s http://localhost:8005/metrics | grep "legion_ollama_queue_depth\|legion_circuit_breaker_state"

# Verify circuit breaker stays closed
# legion_circuit_breaker_state{provider="ollama"} 0.0
```

### 5.4 Monitor Active Sprint for Completion
```bash
# Check if tasks start completing
docker exec legion-db psql -U legion -d legion -c \
  "SELECT id, title, status FROM sprint_tasks
   WHERE sprint_id = 2803
   ORDER BY updated_at DESC
   LIMIT 5;"

# Wait 2-3 minutes, check again
# Expect status transitions: PENDING → RUNNING → COMPLETED

# Check for any new Ollama errors
docker logs legion-backend 2>&1 | grep -i "ollama.*error\|circuit.*open" | tail -10
```

---

## Phase 6: Verification & Cleanup

### 6.1 Verify Cost Savings
```sql
-- Count LLM calls by provider in last 24 hours
SELECT provider, COUNT(*) as calls
FROM llm_call_details
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY provider;

-- Expected: ollama count should increase, kimi count should decrease
```

### 6.2 Generate Ollama Manager Report
```bash
# Trigger daily report manually
curl -X POST http://localhost:8005/ollama-manager/reports/generate

# Check report content
curl http://localhost:8005/ollama-manager/reports/latest | python -m json.tool
```

Expected report sections:
- Models installed (qwen3.5, qwen3.6, gemma4, etc.)
- Performance stats (success rate, latency, task types)
- Recommendations (e.g., "qwen3.5:8b performing well for code_generation")
- Update suggestions

### 6.3 Update MEMORY.md and CLAUDE.md
```markdown
## Learn-14 Resolution (2026-04-06)
- Root cause: qwen3-coder-next returning 500 errors from Ollama /v1/chat/completions
- Fix: [Insert actual fix from Phase 4]
- Restored Ollama execution (qwen3.5:8b primary, Kimi fallback)
- Ollama Manager used to pull/verify latest models
- Circuit breaker reset, execution pipeline now working
```

### 6.4 Run Sprint Auditor Again
```bash
# Re-audit sprint quality after fix
/legion-sprint-auditor
```

Expected improvements:
- **Execution Success:** 15% → 70%+ (tasks completing)
- **Learning Capture:** 0% → 40%+ (episodes storing)
- **Overall Health:** 41.2% → 65%+ (pipeline working)

---

## Rollback Plan (If Ollama Still Fails)

If after all fixes Ollama models still return errors:

1. **Keep Kimi routing** (don't change legion_config.py)
2. **Investigate Ollama version:**
   ```bash
   ollama --version
   docker exec ollama ollama --version  # if containerized
   ```
3. **Check for known issues:** GitHub issues for Ollama + qwen models
4. **Consider Ollama upgrade:**
   ```bash
   curl https://ollama.ai/install.sh | sh
   # or pull latest Docker image
   docker pull ollama/ollama:latest
   ```
5. **Alternative:** Use gemma4:26b or gemma4:31b (already installed) as temporary Ollama execution model

---

## Critical Files

**Configuration:**
- `backend/app/core/legion_config.py` (lines 455-466, 629, 653, 661-676)

**LLM Client:**
- `backend/app/services/llm_clients/ollama_client.py` (lines 141-146, 168)
- `backend/app/services/unified_llm_service.py` (semaphore, circuit breaker)

**Ollama Manager:**
- `backend/app/services/ollama_manager_service.py` (pull, sync, reports)
- `backend/app/api/endpoints/ollama_manager.py` (API)
- `backend/app/models/ollama_manager.py` (DB models)

**Sprint Execution:**
- `backend/app/services/autonomous_sprint_executor.py` (task execution)
- `backend/app/services/agentic_loop_service.py` (cycling)

---

## Success Criteria

✅ **Ollama Manager verified working** (sync, pull, reports)
✅ **Latest qwen models pulled** (3.5 or 3.6 installed and tracked)
✅ **qwen3-coder-next 500 error diagnosed** (root cause identified)
✅ **Fix applied** (tag suffix, model switch, or endpoint change)
✅ **Ollama execution restored** (tasks using qwen, not Kimi)
✅ **Circuit breaker stays closed** (no consecutive failures)
✅ **At least 1 task completes** (sprint 2803 shows COMPLETED tasks)
✅ **Cost savings confirmed** (ollama calls > kimi calls in metrics)
✅ **Sprint quality improves** (execution success >50% in next audit)

---

## Timeline Estimate

- **Phase 1 (Verify Ollama Manager):** 5-10 minutes
- **Phase 2 (Pull Models):** 10-20 minutes (depends on model size, network)
- **Phase 3 (Debug 500 Error):** 10-15 minutes
- **Phase 4 (Apply Fix):** 5-10 minutes (code change + commit)
- **Phase 5 (Restore Execution):** 10-15 minutes (rebuild, restart, monitor)
- **Phase 6 (Verification):** 5-10 minutes

**Total:** 45-80 minutes (assumes models download quickly)

**Blocker Risk:** If Ollama itself is broken or qwen models are fundamentally incompatible with `/v1/chat/completions`, may need to upgrade Ollama or use alternative models (gemma4). This could add 30-60 minutes.
