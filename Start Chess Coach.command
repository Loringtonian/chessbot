#!/bin/bash
# Chess Coach Launcher
# Double-click this file to start the application

cd "$(dirname "$0")"

echo "=========================================="
echo "       Chess Coach - Starting Up         "
echo "=========================================="
echo ""

# Check for API key
if ! grep -q "ANTHROPIC_API_KEY=sk-" backend/.env 2>/dev/null; then
    echo "WARNING: No Anthropic API key found!"
    echo ""
    echo "To enable AI coaching, add your API key to:"
    echo "  $(pwd)/backend/.env"
    echo ""
    echo "Get an API key at: https://console.anthropic.com/"
    echo ""
    echo "Press Enter to continue anyway (Stockfish will still work)..."
    read
fi

# Function to cleanup background processes on exit
cleanup() {
    echo ""
    echo "Shutting down..."
    kill $BACKEND_PID 2>/dev/null
    kill $FRONTEND_PID 2>/dev/null
    exit 0
}
trap cleanup INT TERM

# Start backend
echo "Starting backend server..."
cd backend
source venv/bin/activate
uvicorn app.main:app --port 8000 &
BACKEND_PID=$!
cd ..

# Wait for backend to start
sleep 2

# Start frontend
echo "Starting frontend..."
cd frontend
npm run dev &
FRONTEND_PID=$!
cd ..

# Wait a moment then open browser
sleep 3
echo ""
echo "=========================================="
echo "  Chess Coach is running!"
echo ""
echo "  Open: http://localhost:5173"
echo ""
echo "  Press Ctrl+C to stop"
echo "=========================================="

# Open browser automatically
open http://localhost:5173

# Wait for processes
wait
