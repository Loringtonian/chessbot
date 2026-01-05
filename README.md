# Chess Coach

An AI-powered chess coaching application that combines **Stockfish** chess engine analysis with **Claude** natural language explanations.

## Features

- Interactive chess board with drag-and-drop moves
- Real-time position analysis using Stockfish engine
- Natural language explanations and coaching from Claude AI
- Ask questions about any position
- FEN input for custom positions
- Move history display

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    React Frontend (Vite)                    │
│       Chess Board (react-chessboard) + Chat Interface       │
└─────────────────────────────┬───────────────────────────────┘
                              │ REST API
┌─────────────────────────────▼───────────────────────────────┐
│                   FastAPI Backend (Python)                  │
│   StockfishService ──┬── CoachService ──┬── ClaudeService   │
│         │            │                  │                   │
│    Stockfish      Analysis           Claude API             │
│     Engine       Orchestration       (Anthropic)            │
└─────────────────────────────────────────────────────────────┘
```

## Prerequisites

- Python 3.11+
- Node.js 18+
- Stockfish chess engine
- Anthropic API key

## Quick Start

### 1. Clone and setup

```bash
cd chessbot
```

### 2. Download Stockfish

```bash
chmod +x scripts/download-stockfish.sh
./scripts/download-stockfish.sh
```

Or install via package manager:
- macOS: `brew install stockfish`
- Ubuntu: `sudo apt install stockfish`

### 3. Setup Backend

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

### 4. Setup Frontend

```bash
cd frontend
npm install
```

### 5. Run the Application

In one terminal, start the backend:
```bash
cd backend
source venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

In another terminal, start the frontend:
```bash
cd frontend
npm run dev
```

Open http://localhost:5173 in your browser.

## Configuration

### Environment Variables

Create a `.env` file in the `backend/` directory:

```env
# Required
ANTHROPIC_API_KEY=your_key_here

# Optional
STOCKFISH_PATH=/path/to/stockfish  # Auto-detected if not set
STOCKFISH_DEPTH=20
STOCKFISH_THREADS=2
STOCKFISH_HASH_MB=256
CLAUDE_MODEL=claude-sonnet-4-20250514
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/analyze` | POST | Analyze a chess position |
| `/api/chat` | POST | Ask coaching questions |
| `/api/hint` | POST | Get a hint without revealing the move |
| `/api/health` | GET | Check service health |

### Example: Analyze Position

```bash
curl -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
    "depth": 20,
    "multipv": 3,
    "include_explanation": true
  }'
```

### Example: Chat with Coach

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
    "question": "What should Black play here?",
    "move_history": ["e4"]
  }'
```

## Development

### Backend

```bash
cd backend
source venv/bin/activate

# Run with auto-reload
uvicorn app.main:app --reload

# Run tests
pytest
```

### Frontend

```bash
cd frontend

# Development server
npm run dev

# Type check
npx tsc --noEmit

# Build for production
npm run build
```

## Tech Stack

- **Frontend**: React 18, TypeScript, Vite, Tailwind CSS, react-chessboard
- **Backend**: Python 3.11+, FastAPI, python-chess
- **Chess Engine**: Stockfish 17
- **AI**: Claude (Anthropic API)

## License

MIT
