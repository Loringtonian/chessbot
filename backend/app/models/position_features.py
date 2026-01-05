"""Pydantic models for rich position features extracted from python-chess."""

from pydantic import BaseModel


class MaterialBalance(BaseModel):
    """Material count and balance between sides."""
    white_points: int  # Standard piece values (P=1, N=3, B=3, R=5, Q=9)
    black_points: int
    white_pieces: dict[str, int]  # {"pawns": 8, "knights": 2, ...}
    black_pieces: dict[str, int]
    balance: str  # "equal", "White up a pawn", "Black up the exchange"


class Development(BaseModel):
    """Piece development status."""
    white_developed: int  # Minor pieces off starting squares
    black_developed: int
    white_pieces_developed: list[str]  # ["Nf3", "Bc4"]
    black_pieces_developed: list[str]
    white_castled: str  # "kingside", "queenside", "not castled"
    black_castled: str
    summary: str  # "White leads in development by 2 pieces"


class KingSafety(BaseModel):
    """King safety assessment."""
    white_king_square: str  # "g1"
    black_king_square: str
    white_castling_rights: str  # "can castle both sides", "can castle kingside", "cannot castle"
    black_castling_rights: str
    white_king_attackers: int  # Number of pieces attacking king zone
    black_king_attackers: int
    white_safety: str  # "safe", "slightly exposed", "under attack"
    black_safety: str


class PawnStructure(BaseModel):
    """Pawn structure analysis."""
    white_doubled: list[str]  # ["c2, c3"] - pawns on same file
    black_doubled: list[str]
    white_isolated: list[str]  # ["a2"] - no pawns on adjacent files
    black_isolated: list[str]
    white_passed: list[str]  # ["d5"] - no enemy pawns can block
    black_passed: list[str]
    white_backward: list[str]  # Pawns that can't be defended by other pawns
    black_backward: list[str]
    pawn_islands: dict[str, int]  # {"white": 2, "black": 1}
    summary: str  # "White has an isolated d-pawn, Black has a passed a-pawn"


class PieceActivity(BaseModel):
    """Piece mobility and activity."""
    white_total_moves: int  # Total legal moves for white pieces
    black_total_moves: int
    white_piece_mobility: dict[str, int]  # {"Nf3": 5, "Bc4": 7}
    black_piece_mobility: dict[str, int]
    most_active_white: str | None  # "Bc4 (7 squares)"
    most_active_black: str | None
    trapped_pieces: list[str]  # ["White Bc1 has no moves"]


class Tactics(BaseModel):
    """Tactical elements in the position."""
    pins: list[str]  # ["Black Nd5 is pinned to the king by Bg2"]
    hanging_pieces: list[str]  # ["Black Nf6 is undefended and attacked"]
    forks: list[str]  # ["White Nc7 forks king and rook"]
    threats: list[str]  # ["White threatens Bxf7+"]
    checks: list[str]  # ["White can play Qh7+ check"]
    captures_available: list[str]  # ["White can capture on d5"]


class CenterControl(BaseModel):
    """Control of central squares e4, d4, e5, d5."""
    white_controls: list[str]  # ["e4", "d4"]
    black_controls: list[str]
    contested: list[str]  # ["e5"] - both sides attack
    white_pawns_center: list[str]  # Pawns on e4/d4/e5/d5
    black_pawns_center: list[str]
    summary: str  # "White dominates the center with pawns on e4 and d4"


class PositionFeatures(BaseModel):
    """Complete position analysis with all features."""
    # Side to move
    side_to_move: str  # "White" or "Black"

    # Core features
    material: MaterialBalance
    development: Development
    king_safety: KingSafety
    pawn_structure: PawnStructure
    piece_activity: PieceActivity
    tactics: Tactics
    center_control: CenterControl

    # Position classification
    position_type: str  # "open", "closed", "semi-open", "semi-closed"
    game_phase: str  # "opening", "middlegame", "endgame"

    # Key observations (computed summaries)
    key_features: list[str]  # ["White leads in development", "Black has weak d6 pawn"]

    def to_prompt_text(self) -> str:
        """Convert features to text suitable for LLM prompt."""
        lines = []

        lines.append(f"**Side to Move:** {self.side_to_move}")
        lines.append(f"**Game Phase:** {self.game_phase}")
        lines.append(f"**Position Type:** {self.position_type}")
        lines.append("")

        # Material
        lines.append(f"**Material:** {self.material.balance}")
        if self.material.white_points != self.material.black_points:
            lines.append(f"  White: {self.material.white_points} points, Black: {self.material.black_points} points")

        # Development
        lines.append(f"**Development:** {self.development.summary}")
        if self.development.white_pieces_developed:
            lines.append(f"  White developed: {', '.join(self.development.white_pieces_developed)}")
        if self.development.black_pieces_developed:
            lines.append(f"  Black developed: {', '.join(self.development.black_pieces_developed)}")
        lines.append(f"  Castling: White {self.development.white_castled}, Black {self.development.black_castled}")

        # King Safety
        lines.append(f"**King Safety:** White king on {self.king_safety.white_king_square} ({self.king_safety.white_safety}), "
                    f"Black king on {self.king_safety.black_king_square} ({self.king_safety.black_safety})")

        # Pawn Structure
        if self.pawn_structure.summary:
            lines.append(f"**Pawn Structure:** {self.pawn_structure.summary}")

        # Center Control
        lines.append(f"**Center:** {self.center_control.summary}")

        # Tactics
        if self.tactics.pins:
            lines.append(f"**Pins:** {'; '.join(self.tactics.pins)}")
        if self.tactics.hanging_pieces:
            lines.append(f"**Hanging Pieces:** {'; '.join(self.tactics.hanging_pieces)}")
        if self.tactics.threats:
            lines.append(f"**Threats:** {'; '.join(self.tactics.threats)}")
        if self.tactics.checks:
            lines.append(f"**Available Checks:** {'; '.join(self.tactics.checks)}")

        # Key Features Summary
        if self.key_features:
            lines.append("")
            lines.append("**Key Position Features:**")
            for feature in self.key_features:
                lines.append(f"  - {feature}")

        return "\n".join(lines)
