# Chess Coach Project - Development Context

## Critical Limitation

**An LLM (including Claude Code) cannot reliably assess the quality of another LLM's chess analysis.** LLMs cannot:
- Verify if piece positions mentioned are correct
- Confirm if suggested moves are legal
- Validate tactical/strategic assessments
- Judge the accuracy of chess explanations

Therefore, testing must rely on:
1. Stockfish engine analysis (ground truth for moves/evaluation)
2. python-chess library validation (ground truth for board state)
3. Human review of actual responses
4. Automated tests comparing LLM claims against computed facts

## Architecture

### The Hallucination Problem
LLMs hallucinate chess positions because they cannot reliably parse FEN or ASCII boards. The solution: **pre-compute all positional facts** using python-chess before sending to the LLM.

### Data Flow
```
User Question → Position Analyzer (python-chess) → Rich Facts
                                                      ↓
                Stockfish Analysis → Engine Facts
                                                      ↓
                Combined Context → LLM (Claude Sonnet 4) → Natural Language Response
```

The LLM's role is **interpretation and teaching**, not analysis. It receives pre-computed facts and explains them in natural language.

## Key Files

### Position Analysis (NEW - Hallucination Fix)
- `backend/app/models/position_features.py` - Pydantic models for position data
- `backend/app/services/position_analyzer.py` - Feature extraction using python-chess

### Services
- `backend/app/services/coach_service.py` - Orchestrates Stockfish + Claude
- `backend/app/services/claude_service.py` - Claude API integration (text)
- `backend/app/services/openai_realtime_service.py` - OpenAI Voice API (WebRTC)
- `backend/app/services/stockfish_service.py` - Stockfish engine wrapper

### Models
- `backend/app/models/chess.py` - Core Pydantic models
- `backend/app/models/position_features.py` - Rich position features

## Models Used

- **Text Chat:** Claude Sonnet 4 (`claude-sonnet-4-20250514`)
- **Voice Chat:** GPT-4o Realtime (`gpt-realtime`)
- **Chess Engine:** Stockfish (bundled binary)

## Testing Chess Coach Quality

Since LLMs cannot assess LLM chess outputs, use these methods:

1. **Automated Fact Checking**
   - Compare LLM's mentioned squares against actual piece positions
   - Verify suggested moves are in Stockfish's top 3
   - Check material count claims against computed values

2. **Regression Tests**
   - Store known-good responses for key positions
   - Flag significant deviations for human review

3. **Human Review**
   - Periodically review actual chat responses
   - Focus on positions where hallucination is likely (complex tactics)

## Test PGN (Use for Development)

```
[Site "Chess.com"]
[White "Bishop_Of_Milan"]
[Black "eelsnut"]
[Result "1-0"]
1. f4 Nc6 2. Nf3 b6 3. e4 e6 4. c4 Bc5 5. d4 Bb4+ 6. Bd2 d5 7. Bxb4 Nxb4
8. Qa4+ Bd7 9. Qxb4 dxe4 10. Ne5 Qh4+ 11. g3 Qe7 12. Qxe7+ Nxe7 13. Nxd7 Kxd7
14. Nc3 f5 15. Ke2 Nc6 16. Rd1 Ne7 17. Bg2 a6 18. d5 Kc8 19. dxe6 Kb8
20. Nxe4 fxe4 21. Bxe4 c6 22. Rd7 Ra7 23. Rhd1 Rxd7 24. Rxd7 Re8 25. f5 h6
26. Kf3 Kc8 27. Kf4 g6 28. f6 g5+ 29. Ke5 Ng8 30. f7 Rf8 31. fxg8=Q Rxg8
32. Kd6 c5 33. Ra7 Rd8+ 34. Kc6 Kb8 35. Ra8+ Kxa8 36. Kc7+ Ka7 37. Kxd8 a5
38. e7 a4 39. e8=Q Ka6 40. Qxa4# 1-0
```

Key test positions:
- Move 17 (16...Ne7): Middlegame, White +2 pawns
- Move 40 (checkmate): Verify mate detection
