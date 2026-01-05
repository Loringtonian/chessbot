"""Position analyzer service using python-chess for rich feature extraction.

This service extracts positional features that can be directly used by LLMs,
eliminating the need for LLMs to parse or reason about board positions.
"""

import chess
from typing import Optional

from ..models.position_features import (
    PositionFeatures,
    MaterialBalance,
    Development,
    KingSafety,
    PawnStructure,
    PieceActivity,
    Tactics,
    CenterControl,
)


# Standard piece values
PIECE_VALUES = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 0,  # King has no material value
}

PIECE_NAMES = {
    chess.PAWN: "pawns",
    chess.KNIGHT: "knights",
    chess.BISHOP: "bishops",
    chess.ROOK: "rooks",
    chess.QUEEN: "queens",
    chess.KING: "king",
}

# Starting squares for development tracking
WHITE_STARTING_SQUARES = {
    chess.KNIGHT: [chess.B1, chess.G1],
    chess.BISHOP: [chess.C1, chess.F1],
}

BLACK_STARTING_SQUARES = {
    chess.KNIGHT: [chess.B8, chess.G8],
    chess.BISHOP: [chess.C8, chess.F8],
}

# Center squares
CENTER_SQUARES = [chess.E4, chess.D4, chess.E5, chess.D5]
EXTENDED_CENTER = CENTER_SQUARES + [chess.C4, chess.F4, chess.C5, chess.F5, chess.E3, chess.D3, chess.E6, chess.D6]


class PositionAnalyzer:
    """Analyzes chess positions using python-chess to extract rich features."""

    def analyze(self, fen: str) -> PositionFeatures:
        """Analyze a position and return comprehensive features.

        Args:
            fen: Position in FEN notation.

        Returns:
            PositionFeatures with all analyzed aspects.
        """
        board = chess.Board(fen)

        material = self._analyze_material(board)
        development = self._analyze_development(board)
        king_safety = self._analyze_king_safety(board)
        pawn_structure = self._analyze_pawn_structure(board)
        piece_activity = self._analyze_piece_activity(board)
        tactics = self._analyze_tactics(board)
        center_control = self._analyze_center_control(board)

        # Determine game phase and position type
        game_phase = self._determine_game_phase(board, material)
        position_type = self._determine_position_type(board)

        # Generate key features summary
        key_features = self._generate_key_features(
            material, development, king_safety, pawn_structure,
            piece_activity, tactics, center_control, board
        )

        return PositionFeatures(
            side_to_move="White" if board.turn == chess.WHITE else "Black",
            material=material,
            development=development,
            king_safety=king_safety,
            pawn_structure=pawn_structure,
            piece_activity=piece_activity,
            tactics=tactics,
            center_control=center_control,
            position_type=position_type,
            game_phase=game_phase,
            key_features=key_features,
        )

    def _analyze_material(self, board: chess.Board) -> MaterialBalance:
        """Analyze material balance."""
        white_pieces: dict[str, int] = {}
        black_pieces: dict[str, int] = {}
        white_points = 0
        black_points = 0

        for piece_type in [chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN]:
            white_count = len(board.pieces(piece_type, chess.WHITE))
            black_count = len(board.pieces(piece_type, chess.BLACK))

            white_pieces[PIECE_NAMES[piece_type]] = white_count
            black_pieces[PIECE_NAMES[piece_type]] = black_count

            white_points += white_count * PIECE_VALUES[piece_type]
            black_points += black_count * PIECE_VALUES[piece_type]

        # Calculate balance description
        diff = white_points - black_points
        if diff == 0:
            balance = "equal material"
        elif abs(diff) == 1:
            side = "White" if diff > 0 else "Black"
            balance = f"{side} up a pawn"
        elif abs(diff) == 2:
            side = "White" if diff > 0 else "Black"
            # Check if it's exchange difference (R vs B/N = 2 points)
            white_minors = white_pieces.get("knights", 0) + white_pieces.get("bishops", 0)
            black_minors = black_pieces.get("knights", 0) + black_pieces.get("bishops", 0)
            white_rooks = white_pieces.get("rooks", 0)
            black_rooks = black_pieces.get("rooks", 0)

            if (diff > 0 and white_rooks > black_rooks and black_minors > white_minors) or \
               (diff < 0 and black_rooks > white_rooks and white_minors > black_minors):
                balance = f"{side} up the exchange"
            else:
                balance = f"{side} up 2 pawns"
        elif abs(diff) == 3:
            side = "White" if diff > 0 else "Black"
            balance = f"{side} up a minor piece"
        elif abs(diff) == 5:
            side = "White" if diff > 0 else "Black"
            balance = f"{side} up a rook"
        elif abs(diff) == 9:
            side = "White" if diff > 0 else "Black"
            balance = f"{side} up a queen"
        else:
            side = "White" if diff > 0 else "Black"
            balance = f"{side} up {abs(diff)} points"

        return MaterialBalance(
            white_points=white_points,
            black_points=black_points,
            white_pieces=white_pieces,
            black_pieces=black_pieces,
            balance=balance,
        )

    def _analyze_development(self, board: chess.Board) -> Development:
        """Analyze piece development."""
        white_developed = 0
        black_developed = 0
        white_pieces_developed: list[str] = []
        black_pieces_developed: list[str] = []

        # Piece symbols for SAN notation
        piece_symbols = {chess.KNIGHT: "N", chess.BISHOP: "B"}

        # Check knights and bishops
        for piece_type in [chess.KNIGHT, chess.BISHOP]:
            symbol = piece_symbols[piece_type]

            # White pieces
            for square in board.pieces(piece_type, chess.WHITE):
                if square not in WHITE_STARTING_SQUARES.get(piece_type, []):
                    white_developed += 1
                    square_name = chess.square_name(square)
                    white_pieces_developed.append(f"{symbol}{square_name}")

            # Black pieces
            for square in board.pieces(piece_type, chess.BLACK):
                if square not in BLACK_STARTING_SQUARES.get(piece_type, []):
                    black_developed += 1
                    square_name = chess.square_name(square)
                    black_pieces_developed.append(f"{symbol}{square_name}")

        # Determine castling status
        white_king_square = board.king(chess.WHITE)
        black_king_square = board.king(chess.BLACK)

        if white_king_square == chess.G1:
            white_castled = "kingside"
        elif white_king_square == chess.C1:
            white_castled = "queenside"
        else:
            white_castled = "not castled"

        if black_king_square == chess.G8:
            black_castled = "kingside"
        elif black_king_square == chess.C8:
            black_castled = "queenside"
        else:
            black_castled = "not castled"

        # Generate summary
        dev_diff = white_developed - black_developed
        if dev_diff == 0:
            if white_developed == 0:
                summary = "Neither side has developed pieces"
            else:
                summary = "Equal development"
        elif dev_diff > 0:
            summary = f"White leads in development by {dev_diff} piece{'s' if dev_diff > 1 else ''}"
        else:
            summary = f"Black leads in development by {abs(dev_diff)} piece{'s' if abs(dev_diff) > 1 else ''}"

        return Development(
            white_developed=white_developed,
            black_developed=black_developed,
            white_pieces_developed=white_pieces_developed,
            black_pieces_developed=black_pieces_developed,
            white_castled=white_castled,
            black_castled=black_castled,
            summary=summary,
        )

    def _analyze_king_safety(self, board: chess.Board) -> KingSafety:
        """Analyze king safety."""
        white_king_sq = board.king(chess.WHITE)
        black_king_sq = board.king(chess.BLACK)

        white_king_square = chess.square_name(white_king_sq) if white_king_sq else "unknown"
        black_king_square = chess.square_name(black_king_sq) if black_king_sq else "unknown"

        # Castling rights
        white_castling = []
        if board.has_kingside_castling_rights(chess.WHITE):
            white_castling.append("kingside")
        if board.has_queenside_castling_rights(chess.WHITE):
            white_castling.append("queenside")

        black_castling = []
        if board.has_kingside_castling_rights(chess.BLACK):
            black_castling.append("kingside")
        if board.has_queenside_castling_rights(chess.BLACK):
            black_castling.append("queenside")

        white_castling_rights = " and ".join(white_castling) if white_castling else "cannot castle"
        if white_castling:
            white_castling_rights = f"can castle {white_castling_rights}"

        black_castling_rights = " and ".join(black_castling) if black_castling else "cannot castle"
        if black_castling:
            black_castling_rights = f"can castle {black_castling_rights}"

        # Count attackers on king zone (squares around king)
        def count_king_attackers(king_sq: Optional[int], attacking_color: chess.Color) -> int:
            if king_sq is None:
                return 0
            attackers = 0
            king_file = chess.square_file(king_sq)
            king_rank = chess.square_rank(king_sq)

            for df in [-1, 0, 1]:
                for dr in [-1, 0, 1]:
                    f = king_file + df
                    r = king_rank + dr
                    if 0 <= f <= 7 and 0 <= r <= 7:
                        sq = chess.square(f, r)
                        attackers += len(board.attackers(attacking_color, sq))
            return attackers

        white_king_attackers = count_king_attackers(white_king_sq, chess.BLACK)
        black_king_attackers = count_king_attackers(black_king_sq, chess.WHITE)

        # Determine safety level
        def safety_level(attackers: int, can_castle: bool, is_castled: bool) -> str:
            if board.is_check():
                return "in check"
            if attackers >= 6:
                return "under attack"
            elif attackers >= 3:
                return "slightly exposed"
            elif is_castled or (attackers <= 1):
                return "safe"
            else:
                return "slightly exposed"

        white_is_castled = white_king_sq in [chess.G1, chess.C1]
        black_is_castled = black_king_sq in [chess.G8, chess.C8]

        white_safety = safety_level(white_king_attackers, bool(white_castling), white_is_castled)
        black_safety = safety_level(black_king_attackers, bool(black_castling), black_is_castled)

        return KingSafety(
            white_king_square=white_king_square,
            black_king_square=black_king_square,
            white_castling_rights=white_castling_rights,
            black_castling_rights=black_castling_rights,
            white_king_attackers=white_king_attackers,
            black_king_attackers=black_king_attackers,
            white_safety=white_safety,
            black_safety=black_safety,
        )

    def _analyze_pawn_structure(self, board: chess.Board) -> PawnStructure:
        """Analyze pawn structure."""
        white_pawns = list(board.pieces(chess.PAWN, chess.WHITE))
        black_pawns = list(board.pieces(chess.PAWN, chess.BLACK))

        white_pawn_files = [chess.square_file(sq) for sq in white_pawns]
        black_pawn_files = [chess.square_file(sq) for sq in black_pawns]

        # Doubled pawns (multiple pawns on same file)
        white_doubled: list[str] = []
        black_doubled: list[str] = []

        for f in range(8):
            white_on_file = [sq for sq in white_pawns if chess.square_file(sq) == f]
            if len(white_on_file) > 1:
                squares = ", ".join(chess.square_name(sq) for sq in white_on_file)
                white_doubled.append(squares)

            black_on_file = [sq for sq in black_pawns if chess.square_file(sq) == f]
            if len(black_on_file) > 1:
                squares = ", ".join(chess.square_name(sq) for sq in black_on_file)
                black_doubled.append(squares)

        # Isolated pawns (no friendly pawns on adjacent files)
        white_isolated: list[str] = []
        black_isolated: list[str] = []

        for sq in white_pawns:
            f = chess.square_file(sq)
            adjacent_files = [f - 1, f + 1]
            has_neighbor = any(pf in adjacent_files for pf in white_pawn_files if pf != f)
            if not has_neighbor:
                white_isolated.append(chess.square_name(sq))

        for sq in black_pawns:
            f = chess.square_file(sq)
            adjacent_files = [f - 1, f + 1]
            has_neighbor = any(pf in adjacent_files for pf in black_pawn_files if pf != f)
            if not has_neighbor:
                black_isolated.append(chess.square_name(sq))

        # Passed pawns (no enemy pawns can block or capture)
        white_passed: list[str] = []
        black_passed: list[str] = []

        for sq in white_pawns:
            f = chess.square_file(sq)
            r = chess.square_rank(sq)
            is_passed = True
            for enemy_sq in black_pawns:
                ef = chess.square_file(enemy_sq)
                er = chess.square_rank(enemy_sq)
                if abs(ef - f) <= 1 and er > r:  # Enemy pawn ahead or on adjacent file
                    is_passed = False
                    break
            if is_passed:
                white_passed.append(chess.square_name(sq))

        for sq in black_pawns:
            f = chess.square_file(sq)
            r = chess.square_rank(sq)
            is_passed = True
            for enemy_sq in white_pawns:
                ef = chess.square_file(enemy_sq)
                er = chess.square_rank(enemy_sq)
                if abs(ef - f) <= 1 and er < r:  # Enemy pawn ahead or on adjacent file
                    is_passed = False
                    break
            if is_passed:
                black_passed.append(chess.square_name(sq))

        # Backward pawns (can't be defended by other pawns, blocked from advancing)
        white_backward: list[str] = []
        black_backward: list[str] = []

        for sq in white_pawns:
            f = chess.square_file(sq)
            r = chess.square_rank(sq)
            # Check if any friendly pawn on adjacent file is behind or equal
            can_be_defended = False
            for pf in white_pawn_files:
                if abs(pf - f) == 1:
                    # Check if there's a pawn that could defend
                    for wsq in white_pawns:
                        if chess.square_file(wsq) == pf and chess.square_rank(wsq) <= r:
                            can_be_defended = True
                            break
            if not can_be_defended and sq not in [chess.square(f, 1) for f in range(8)]:  # Not on starting rank
                # Check if pawn is blocked
                advance_sq = chess.square(f, r + 1) if r + 1 <= 7 else None
                if advance_sq and board.piece_at(advance_sq):
                    white_backward.append(chess.square_name(sq))

        for sq in black_pawns:
            f = chess.square_file(sq)
            r = chess.square_rank(sq)
            can_be_defended = False
            for pf in black_pawn_files:
                if abs(pf - f) == 1:
                    for bsq in black_pawns:
                        if chess.square_file(bsq) == pf and chess.square_rank(bsq) >= r:
                            can_be_defended = True
                            break
            if not can_be_defended and sq not in [chess.square(f, 6) for f in range(8)]:
                advance_sq = chess.square(f, r - 1) if r - 1 >= 0 else None
                if advance_sq and board.piece_at(advance_sq):
                    black_backward.append(chess.square_name(sq))

        # Pawn islands
        def count_islands(pawn_files: list[int]) -> int:
            if not pawn_files:
                return 0
            unique_files = sorted(set(pawn_files))
            islands = 1
            for i in range(1, len(unique_files)):
                if unique_files[i] - unique_files[i - 1] > 1:
                    islands += 1
            return islands

        pawn_islands = {
            "white": count_islands(white_pawn_files),
            "black": count_islands(black_pawn_files),
        }

        # Generate summary
        summary_parts = []
        if white_doubled:
            summary_parts.append(f"White has doubled pawns on {', '.join(white_doubled)}")
        if black_doubled:
            summary_parts.append(f"Black has doubled pawns on {', '.join(black_doubled)}")
        if white_isolated:
            summary_parts.append(f"White has isolated pawn{'s' if len(white_isolated) > 1 else ''} on {', '.join(white_isolated)}")
        if black_isolated:
            summary_parts.append(f"Black has isolated pawn{'s' if len(black_isolated) > 1 else ''} on {', '.join(black_isolated)}")
        if white_passed:
            summary_parts.append(f"White has passed pawn{'s' if len(white_passed) > 1 else ''} on {', '.join(white_passed)}")
        if black_passed:
            summary_parts.append(f"Black has passed pawn{'s' if len(black_passed) > 1 else ''} on {', '.join(black_passed)}")

        summary = "; ".join(summary_parts) if summary_parts else "Balanced pawn structure"

        return PawnStructure(
            white_doubled=white_doubled,
            black_doubled=black_doubled,
            white_isolated=white_isolated,
            black_isolated=black_isolated,
            white_passed=white_passed,
            black_passed=black_passed,
            white_backward=white_backward,
            black_backward=black_backward,
            pawn_islands=pawn_islands,
            summary=summary,
        )

    def _analyze_piece_activity(self, board: chess.Board) -> PieceActivity:
        """Analyze piece mobility and activity."""
        white_mobility: dict[str, int] = {}
        black_mobility: dict[str, int] = {}
        white_total = 0
        black_total = 0
        trapped_pieces: list[str] = []

        # We need to count legal moves for pieces
        # Create a copy for each side to move
        for piece_type in [chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN]:
            # White pieces
            for sq in board.pieces(piece_type, chess.WHITE):
                moves = len([m for m in board.legal_moves if m.from_square == sq]) if board.turn == chess.WHITE else \
                        len(list(board.attacks(sq)))
                piece_name = f"{chess.piece_symbol(piece_type).upper()}{chess.square_name(sq)}"
                white_mobility[piece_name] = moves
                white_total += moves
                if moves == 0 and piece_type != chess.KING:
                    trapped_pieces.append(f"White {chess.piece_name(piece_type)} on {chess.square_name(sq)} has no moves")

            # Black pieces
            for sq in board.pieces(piece_type, chess.BLACK):
                moves = len([m for m in board.legal_moves if m.from_square == sq]) if board.turn == chess.BLACK else \
                        len(list(board.attacks(sq)))
                piece_name = f"{chess.piece_symbol(piece_type).lower()}{chess.square_name(sq)}"
                black_mobility[piece_name] = moves
                black_total += moves
                if moves == 0 and piece_type != chess.KING:
                    trapped_pieces.append(f"Black {chess.piece_name(piece_type)} on {chess.square_name(sq)} has no moves")

        # Find most active pieces
        most_active_white: Optional[str] = None
        most_active_black: Optional[str] = None

        if white_mobility:
            best = max(white_mobility.items(), key=lambda x: x[1])
            if best[1] > 0:
                most_active_white = f"{best[0]} ({best[1]} squares)"

        if black_mobility:
            best = max(black_mobility.items(), key=lambda x: x[1])
            if best[1] > 0:
                most_active_black = f"{best[0]} ({best[1]} squares)"

        return PieceActivity(
            white_total_moves=white_total,
            black_total_moves=black_total,
            white_piece_mobility=white_mobility,
            black_piece_mobility=black_mobility,
            most_active_white=most_active_white,
            most_active_black=most_active_black,
            trapped_pieces=trapped_pieces,
        )

    def _analyze_tactics(self, board: chess.Board) -> Tactics:
        """Analyze tactical elements."""
        pins: list[str] = []
        hanging_pieces: list[str] = []
        forks: list[str] = []
        threats: list[str] = []
        checks: list[str] = []
        captures_available: list[str] = []

        # Find pins (pieces that can't move because they'd expose the king)
        for color in [chess.WHITE, chess.BLACK]:
            king_sq = board.king(color)
            if king_sq is None:
                continue

            for piece_type in [chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN]:
                for sq in board.pieces(piece_type, color):
                    if board.is_pinned(color, sq):
                        piece_name = chess.piece_name(piece_type).capitalize()
                        color_name = "White" if color == chess.WHITE else "Black"
                        # Find what's pinning it
                        pin_mask = board.pin(color, sq)
                        for attacker_sq in chess.SquareSet(pin_mask):
                            attacker = board.piece_at(attacker_sq)
                            if attacker and attacker.color != color:
                                attacker_name = chess.piece_name(attacker.piece_type).capitalize()
                                pins.append(
                                    f"{color_name} {piece_name} on {chess.square_name(sq)} "
                                    f"is pinned by {attacker_name} on {chess.square_name(attacker_sq)}"
                                )
                                break

        # Find hanging pieces (attacked but not defended, or attacked by lesser value)
        for color in [chess.WHITE, chess.BLACK]:
            enemy_color = not color
            color_name = "White" if color == chess.WHITE else "Black"

            for piece_type in [chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN]:
                for sq in board.pieces(piece_type, color):
                    attackers = board.attackers(enemy_color, sq)
                    defenders = board.attackers(color, sq)

                    if attackers:
                        if not defenders:
                            piece_name = chess.piece_name(piece_type).capitalize()
                            hanging_pieces.append(
                                f"{color_name} {piece_name} on {chess.square_name(sq)} is undefended and attacked"
                            )
                        else:
                            # Check if attacked by lower value piece
                            min_attacker_value = min(
                                PIECE_VALUES.get(board.piece_at(a).piece_type, 0)
                                for a in attackers if board.piece_at(a)
                            )
                            piece_value = PIECE_VALUES.get(piece_type, 0)
                            if min_attacker_value < piece_value and piece_value > 1:
                                piece_name = chess.piece_name(piece_type).capitalize()
                                hanging_pieces.append(
                                    f"{color_name} {piece_name} on {chess.square_name(sq)} "
                                    f"is attacked by a lesser piece"
                                )

        # Find available checks
        for move in board.legal_moves:
            # Get SAN before pushing the move
            move_san = board.san(move)
            board.push(move)
            if board.is_check():
                piece = board.piece_at(move.to_square)
                if piece:
                    side = "White" if piece.color == chess.WHITE else "Black"
                    checks.append(f"{side} can play {move_san} check")
            board.pop()

        # Find available captures
        for move in board.legal_moves:
            if board.is_capture(move):
                captured = board.piece_at(move.to_square)
                if captured:
                    captures_available.append(
                        f"Can capture on {chess.square_name(move.to_square)}"
                    )

        # Limit lists to most important items
        return Tactics(
            pins=pins[:5],
            hanging_pieces=hanging_pieces[:5],
            forks=forks[:3],
            threats=threats[:5],
            checks=checks[:3],
            captures_available=captures_available[:5],
        )

    def _analyze_center_control(self, board: chess.Board) -> CenterControl:
        """Analyze control of central squares."""
        white_controls: list[str] = []
        black_controls: list[str] = []
        contested: list[str] = []
        white_pawns_center: list[str] = []
        black_pawns_center: list[str] = []

        for sq in CENTER_SQUARES:
            white_attackers = len(board.attackers(chess.WHITE, sq))
            black_attackers = len(board.attackers(chess.BLACK, sq))
            sq_name = chess.square_name(sq)

            # Check for pawns in center
            piece = board.piece_at(sq)
            if piece and piece.piece_type == chess.PAWN:
                if piece.color == chess.WHITE:
                    white_pawns_center.append(sq_name)
                else:
                    black_pawns_center.append(sq_name)

            if white_attackers > black_attackers:
                white_controls.append(sq_name)
            elif black_attackers > white_attackers:
                black_controls.append(sq_name)
            elif white_attackers > 0 and black_attackers > 0:
                contested.append(sq_name)

        # Generate summary
        if len(white_controls) >= 3:
            summary = "White dominates the center"
        elif len(black_controls) >= 3:
            summary = "Black dominates the center"
        elif len(white_controls) > len(black_controls):
            summary = "White has slightly better central control"
        elif len(black_controls) > len(white_controls):
            summary = "Black has slightly better central control"
        else:
            summary = "Center is contested"

        if white_pawns_center:
            summary += f" with pawn{'s' if len(white_pawns_center) > 1 else ''} on {', '.join(white_pawns_center)}"
        if black_pawns_center:
            summary += f"; Black has pawn{'s' if len(black_pawns_center) > 1 else ''} on {', '.join(black_pawns_center)}"

        return CenterControl(
            white_controls=white_controls,
            black_controls=black_controls,
            contested=contested,
            white_pawns_center=white_pawns_center,
            black_pawns_center=black_pawns_center,
            summary=summary,
        )

    def _determine_game_phase(self, board: chess.Board, material: MaterialBalance) -> str:
        """Determine if position is opening, middlegame, or endgame."""
        total_material = material.white_points + material.black_points

        # Count queens
        white_queens = len(board.pieces(chess.QUEEN, chess.WHITE))
        black_queens = len(board.pieces(chess.QUEEN, chess.BLACK))

        # Check for development (opening indicator)
        white_developed = sum(1 for sq in board.pieces(chess.KNIGHT, chess.WHITE)
                             if sq not in WHITE_STARTING_SQUARES[chess.KNIGHT])
        white_developed += sum(1 for sq in board.pieces(chess.BISHOP, chess.WHITE)
                              if sq not in WHITE_STARTING_SQUARES[chess.BISHOP])
        black_developed = sum(1 for sq in board.pieces(chess.KNIGHT, chess.BLACK)
                             if sq not in BLACK_STARTING_SQUARES[chess.KNIGHT])
        black_developed += sum(1 for sq in board.pieces(chess.BISHOP, chess.BLACK)
                              if sq not in BLACK_STARTING_SQUARES[chess.BISHOP])

        if total_material <= 26:  # Roughly 2 rooks + minor pieces or less per side
            return "endgame"
        elif white_developed + black_developed <= 4 and total_material >= 70:
            return "opening"
        else:
            return "middlegame"

    def _determine_position_type(self, board: chess.Board) -> str:
        """Determine if position is open, closed, semi-open, or semi-closed."""
        # Count pawns
        total_pawns = len(board.pieces(chess.PAWN, chess.WHITE)) + len(board.pieces(chess.PAWN, chess.BLACK))

        # Count pawn chains/blocks in center
        center_blocked = 0
        for sq in CENTER_SQUARES:
            piece = board.piece_at(sq)
            if piece and piece.piece_type == chess.PAWN:
                # Check if blocked
                advance_rank = chess.square_rank(sq) + (1 if piece.color == chess.WHITE else -1)
                if 0 <= advance_rank <= 7:
                    advance_sq = chess.square(chess.square_file(sq), advance_rank)
                    if board.piece_at(advance_sq):
                        center_blocked += 1

        if total_pawns <= 8 and center_blocked == 0:
            return "open"
        elif center_blocked >= 2:
            return "closed"
        elif total_pawns <= 10:
            return "semi-open"
        else:
            return "semi-closed"

    def _generate_key_features(
        self,
        material: MaterialBalance,
        development: Development,
        king_safety: KingSafety,
        pawn_structure: PawnStructure,
        piece_activity: PieceActivity,
        tactics: Tactics,
        center_control: CenterControl,
        board: chess.Board,
    ) -> list[str]:
        """Generate a list of key position features."""
        features: list[str] = []

        # Material
        if material.balance != "equal material":
            features.append(material.balance.capitalize())

        # Development
        if "leads" in development.summary:
            features.append(development.summary)

        # King safety concerns
        if king_safety.white_safety in ["under attack", "in check"]:
            features.append(f"White king is {king_safety.white_safety}")
        if king_safety.black_safety in ["under attack", "in check"]:
            features.append(f"Black king is {king_safety.black_safety}")

        # Pawn structure highlights
        if pawn_structure.white_passed or pawn_structure.black_passed:
            if pawn_structure.white_passed:
                features.append(f"White has passed pawn{'s' if len(pawn_structure.white_passed) > 1 else ''}")
            if pawn_structure.black_passed:
                features.append(f"Black has passed pawn{'s' if len(pawn_structure.black_passed) > 1 else ''}")

        # Tactical elements
        if tactics.pins:
            features.append("Position contains pin(s)")
        if tactics.hanging_pieces:
            features.append("Hanging piece(s) present")
        if tactics.checks:
            features.append("Check available")

        # Center control
        if "dominates" in center_control.summary:
            features.append(center_control.summary)

        # Activity
        if piece_activity.trapped_pieces:
            features.append("Trapped piece(s) on the board")

        return features[:6]  # Limit to 6 most important features


# Singleton instance
_position_analyzer: Optional[PositionAnalyzer] = None


def get_position_analyzer() -> PositionAnalyzer:
    """Get the global position analyzer instance."""
    global _position_analyzer
    if _position_analyzer is None:
        _position_analyzer = PositionAnalyzer()
    return _position_analyzer
