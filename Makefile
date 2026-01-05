.PHONY: setup setup-backend setup-frontend dev dev-backend dev-frontend stockfish clean

# Full setup
setup: stockfish setup-backend setup-frontend
	@echo "Setup complete! Run 'make dev' to start the application."

# Download Stockfish
stockfish:
	@chmod +x scripts/download-stockfish.sh
	@./scripts/download-stockfish.sh

# Backend setup
setup-backend:
	@echo "Setting up backend..."
	@cd backend && python -m venv venv
	@cd backend && . venv/bin/activate && pip install -r requirements.txt
	@if [ ! -f backend/.env ]; then cp backend/.env.example backend/.env; fi
	@echo "Backend setup complete. Edit backend/.env to add your ANTHROPIC_API_KEY"

# Frontend setup
setup-frontend:
	@echo "Setting up frontend..."
	@cd frontend && npm install

# Run both servers
dev:
	@echo "Starting backend and frontend..."
	@make dev-backend & make dev-frontend

# Run backend only
dev-backend:
	@cd backend && . venv/bin/activate && uvicorn app.main:app --reload --port 8000

# Run frontend only
dev-frontend:
	@cd frontend && npm run dev

# Build frontend
build:
	@cd frontend && npm run build

# Clean up
clean:
	@rm -rf backend/venv
	@rm -rf frontend/node_modules
	@rm -rf backend/engines/stockfish/*
	@echo "Cleaned up dependencies"
