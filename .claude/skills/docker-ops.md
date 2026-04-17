# Docker Operations

Comprehensive Docker reference combining container management, diagnostics, and debugging. Covers container lifecycle, image operations, Compose workflows, networking, resource inspection, health checks, and common failure patterns.

## Container Lifecycle

### Running containers
```bash
# Run container from image
docker run nginx

# Run in background (detached)
docker run -d nginx

# Run with name
docker run --name my-nginx -d nginx

# Run with port mapping
docker run -p 8080:80 -d nginx

# Run with environment variables
docker run -e MY_VAR=value -d app

# Run with volume mount
docker run -v /host/path:/container/path -d app

# Run with auto-remove on exit
docker run --rm alpine echo "Hello"

# Interactive terminal
docker run -it ubuntu bash
```

### Managing containers
```bash
# List running containers
docker ps

# List all containers (including stopped)
docker ps -a

# Stop / start / restart container
docker stop container_name
docker start container_name
docker restart container_name

# Remove container
docker rm container_name

# Force remove running container
docker rm -f container_name

# Remove all stopped containers
docker container prune
```

## Container Logs

### View and filter logs
```bash
# Show logs
docker logs container_name

# Follow logs (like tail -f)
docker logs -f container_name

# Last 100 lines
docker logs --tail 100 container_name

# Logs with timestamps
docker logs -t container_name

# Logs since a time
docker logs --since 30m container_name
docker logs --since "2026-02-03T10:00:00" container_name

# Logs between times
docker logs --since 1h --until 30m container_name

# Compose: logs for all services
docker compose logs -f

# Compose: logs for specific service
docker compose logs -f api db

# Redirect logs to file for analysis
docker logs container_name > container.log 2>&1

# Separate stdout and stderr
docker logs container_name > stdout.log 2> stderr.log
```

### Inspect log driver
```bash
# Check what log driver a container uses
docker inspect --format='{{.HostConfig.LogConfig.Type}}' container_name

# If json-file driver, find the actual log file
docker inspect --format='{{.LogPath}}' container_name
```

## Exec Into Containers

### Interactive shell
```bash
# Bash (most common)
docker exec -it container_name bash

# If bash isn't available (Alpine, distroless)
docker exec -it container_name sh

# As root (even if container runs as non-root user)
docker exec -u root -it container_name bash

# With specific environment variables
docker exec -e DEBUG=1 -it container_name bash

# Run a single command (no interactive shell)
docker exec container_name cat /etc/os-release
docker exec container_name ls -la /app/
docker exec container_name env
```

### Debug a crashed container
```bash
# Container exited? Check exit code
docker inspect --format='{{.State.ExitCode}}' container_name
docker inspect --format='{{.State.Error}}' container_name

# Common exit codes:
# 0   = clean exit
# 1   = application error
# 137 = killed (OOM or docker kill) -- 128 + signal 9
# 139 = segfault -- 128 + signal 11
# 143 = terminated (SIGTERM) -- 128 + signal 15

# Start a stopped container to debug it
docker start -ai container_name

# Or override the entrypoint to get a shell
docker run -it --entrypoint sh my-image

# Copy files out of a stopped container
docker cp container_name:/app/error.log ./error.log
```

### Debug without a shell (distroless / scratch images)
```bash
# Use docker cp to extract files
docker cp container_name:/app/config.json ./

# Use nsenter to get a shell in the container's namespace (Linux)
PID=$(docker inspect --format='{{.State.Pid}}' container_name)
nsenter -t $PID -m -u -i -n -p -- /bin/sh

# Attach a debug container to the same namespace
docker run -it --pid=container:container_name --net=container:container_name busybox sh

# Docker Desktop: use debug extension
docker debug container_name
```

## Container Inspection

```bash
# Inspect container details
docker inspect container_name

# Get specific field (JSON path)
docker inspect -f '{{.NetworkSettings.IPAddress}}' container_name

# View container stats (real-time)
docker stats

# Specific containers
docker stats api db redis

# One-shot (no streaming)
docker stats --no-stream

# Formatted output
docker stats --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}"

# View processes in container
docker top container_name
```

## Image Management

### Building images
```bash
# Build from Dockerfile
docker build -t myapp:1.0 .

# Build with custom Dockerfile
docker build -f Dockerfile.dev -t myapp:dev .

# Build with build args
docker build --build-arg VERSION=1.0 -t myapp .

# Build without cache
docker build --no-cache -t myapp .

# Build with progress output (essential for debugging build failures)
docker build --progress=plain -t myapp .

# Build up to a specific stage (multi-stage debugging)
docker build --target builder -t my-app:builder .
```

### Managing images
```bash
# List images
docker images

# Pull image from registry
docker pull nginx:latest

# Tag image
docker tag myapp:1.0 myapp:latest

# Push to registry
docker push myrepo/myapp:1.0

# Remove image
docker rmi image_name

# Remove unused images
docker image prune

# Remove all unused images
docker image prune -a

# Show image layers (size of each)
docker history my-image
docker history --no-trunc my-image

# Inspect image config (entrypoint, cmd, env, ports)
docker inspect my-image | jq '.[0].Config | {Cmd, Entrypoint, Env, ExposedPorts, WorkingDir}'
```

## Docker Compose

### Basic operations
```bash
# Start services
docker compose up -d

# Stop services
docker compose down

# Stop and remove volumes
docker compose down -v

# View logs
docker compose logs

# Follow logs for specific service
docker compose logs -f web

# Scale service
docker compose up -d --scale web=3
```

### Service management
```bash
# List services
docker compose ps

# Execute command in service
docker compose exec web bash

# Restart service
docker compose restart web

# Rebuild service
docker compose build web

# Rebuild and restart
docker compose up -d --build

# Recreate containers from scratch
docker compose up --force-recreate --build

# Check effective config (after variable substitution)
docker compose config

# Start a single service (with dependencies)
docker compose up db

# Start without dependencies
docker compose up --no-deps api
```

### Service dependency and startup order
```yaml
# docker-compose.yml
services:
  api:
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_started

  db:
    image: postgres:16
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5
```

## Networking

### Inspect container networking
```bash
# Show container IP address
docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' container_name

# Show all network details
docker inspect -f '{{json .NetworkSettings.Networks}}' container_name | jq

# List all networks
docker network ls

# Inspect a network (see all connected containers)
docker network inspect bridge

# Show port mappings
docker port container_name
```

### Test connectivity between containers
```bash
# From inside container A, reach container B
docker exec container-a ping container-b
docker exec container-a curl http://container-b:8080/health

# DNS resolution inside container
docker exec container_name nslookup db
docker exec container_name cat /etc/resolv.conf
docker exec container_name cat /etc/hosts

# Test if port is reachable
docker exec container_name nc -zv db 5432

# If curl/ping not available, use a debug container:
docker run --rm --network container:container_name curlimages/curl curl -s http://localhost:8080
```

### Common networking issues
```bash
# "Connection refused" between containers
# 1. Check the app binds to 0.0.0.0, not 127.0.0.1
docker exec container_name netstat -tlnp

# 2. Check containers are on the same network
docker inspect -f '{{json .NetworkSettings.Networks}}' container-a | jq 'keys'
docker inspect -f '{{json .NetworkSettings.Networks}}' container-b | jq 'keys'

# 3. Published ports vs exposed ports
# EXPOSE only documents, it doesn't publish. Use -p host:container to publish.

# "Name not found" -- DNS not resolving container names
# Container names resolve only on user-defined networks, NOT the default bridge
docker network create my-net
docker run --network my-net --name api my-api-image
docker run --network my-net --name db postgres
```

### Capture network traffic
```bash
# tcpdump inside a container
docker exec container_name tcpdump -i eth0 -n port 8080

# If tcpdump not available, use a sidecar (nicolaka/netshoot has every networking tool)
docker run --rm --net=container:container_name nicolaka/netshoot tcpdump -i eth0 -n
docker run --rm --net=container:container_name nicolaka/netshoot bash
```

## Resource Usage

### Memory investigation
```bash
# Check memory limit (0 means unlimited)
docker inspect --format='{{.HostConfig.Memory}}' container_name

# Check if container was OOM-killed
docker inspect --format='{{.State.OOMKilled}}' container_name

# Memory usage breakdown (Linux cgroups)
docker exec container_name cat /sys/fs/cgroup/memory.current 2>/dev/null || \
docker exec container_name cat /sys/fs/cgroup/memory/memory.usage_in_bytes

# Process memory inside container
docker exec container_name ps aux --sort=-%mem | head -10
docker exec container_name top -bn1
```

### Disk usage
```bash
# Overall Docker disk usage
docker system df
docker system df -v

# Container filesystem size
docker inspect --format='{{.SizeRw}}' container_name

# Find large files inside container
docker exec container_name du -sh /* 2>/dev/null | sort -rh | head -10
```

## Volumes
```bash
# List volumes
docker volume ls

# Create volume
docker volume create myvolume

# Inspect volume
docker volume inspect myvolume

# Remove volume
docker volume rm myvolume

# Remove unused volumes
docker volume prune

# Run with volume
docker run -v myvolume:/data -d app
```

## Health Checks

### Define and debug health checks
```dockerfile
# In Dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:8080/health || exit 1
```

```bash
# Check health status ("healthy", "unhealthy", or "starting")
docker inspect --format='{{.State.Health.Status}}' container_name

# See health check log (last 5 results)
docker inspect --format='{{json .State.Health}}' container_name | jq

# Run health check manually
docker exec container_name curl -f http://localhost:8080/health

# Override health check at run time
docker run --health-cmd "curl -f http://localhost:8080/health || exit 1" \
           --health-interval 10s my-image

# Disable health check
docker run --no-healthcheck my-image
```

## Multi-stage Build Debugging

```bash
# Build up to a specific stage
docker build --target builder -t my-app:builder .

# Inspect what's in the builder stage
docker run --rm -it my-app:builder sh
docker run --rm my-app:builder ls -la /app/

# Check which files made it to the final image
docker run --rm my-image ls -laR /app/

# Compare two images
docker history image-a --format "{{.Size}}\t{{.CreatedBy}}" > layers-a.txt
docker history image-b --format "{{.Size}}\t{{.CreatedBy}}" > layers-b.txt
diff layers-a.txt layers-b.txt

# Find what changed between builds
docker diff container_name
# A = added, C = changed, D = deleted
```

## System Cleanup

```bash
# Remove stopped containers
docker container prune

# Remove unused images
docker image prune

# Remove everything unused (containers, images, networks, volumes)
docker system prune -a

# Remove volumes too (WARNING: deletes data)
docker system prune -a --volumes

# Remove dangling build cache
docker builder prune

# View disk usage
docker system df

# Show Docker info/version
docker info
docker version
```

## Common Workflows

**Development container:**
```bash
docker run -it --rm \
  -v $(pwd):/app \
  -w /app \
  -p 3000:3000 \
  node:18 \
  npm run dev
```

**Database container:**
```bash
docker run -d \
  --name postgres \
  -e POSTGRES_PASSWORD=secret \
  -e POSTGRES_DB=mydb \
  -v postgres-data:/var/lib/postgresql/data \
  -p 5432:5432 \
  postgres:15
```

**Multi-stage build:**
```dockerfile
FROM node:18 AS builder
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
```

## Tips

- `docker logs -f` is the first thing to check. Most container failures are visible in the logs.
- Exit code 137 means OOM-killed. Increase the memory limit or fix the memory leak.
- Apps inside containers must bind to `0.0.0.0`, not `127.0.0.1`. Localhost inside a container is isolated.
- Container names only resolve via DNS on user-defined networks, not the default `bridge`. Always create a custom network for multi-container setups.
- `docker exec` only works on running containers. For crashed containers, use `docker cp` to extract logs or override the entrypoint with `docker run --entrypoint sh`.
- `nicolaka/netshoot` is the Swiss Army knife for container networking. It has every networking tool pre-installed.
- `--progress=plain` during builds shows full command output, essential for debugging build failures.
- Health checks with `start-period` prevent false unhealthy status during slow application startup.
- Use `.dockerignore` to exclude files from build context.
- Combine `RUN` commands in Dockerfile to reduce layers.
- Use multi-stage builds to reduce image size.
- Always tag your images with versions.
- Use `--rm` for one-off containers.
- Clean up regularly with `docker system prune`.

## Zero Project Docker Notes

- **Backend** (`zero-api`): Code is COPY'd, not volume-mounted. ALL backend changes require rebuild:
  ```bash
  docker compose -f docker-compose.sprint.yml build --no-cache zero-api && docker compose -f docker-compose.sprint.yml up -d zero-api
  ```
- **Frontend** (`zero-ui`): Source files ARE volume-mounted (live changes). Only new npm packages require rebuild.
- **Healthcheck gotcha**: Alpine containers resolve `localhost` to `::1`. Use `127.0.0.1` instead.
- **Check container status**: `docker ps --format "table {{.Names}}\t{{.Status}}" | grep zero`
