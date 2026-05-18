# RanGwaz

RanGwaz is a clean rebuild of an image-first social site inspired by Pinterest.

## Modules

- `frontend`: React + Vite image website with masonry feed, infinite scroll, detail page, search, auth, and publish flow.
- `backend`: Spring Boot MVC API with controller, service, mapper, entity, dto, common, config, and utility-style packages.
- `infra`: Development middleware managed by Docker Compose.

## Development

1. Start middleware:
   ```powershell
   docker compose -f infra/docker-compose.yml up -d
   ```
2. Start backend from IDEA or Maven:
   ```powershell
   cd backend
   mvn spring-boot:run
   ```
3. Start frontend:
   ```powershell
   cd frontend
   npm install
   npm run dev
   ```

The backend rebuilds the development schema on startup and seeds random image data for local work.
