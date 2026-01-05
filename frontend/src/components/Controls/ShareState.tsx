/**
 * Button to copy current game state for sharing with AI assistant.
 */

import { useState } from 'react';
import type { Evaluation, LoadedGame } from '../../types/chess';

interface ShareStateProps {
  fen: string;
  history: string[];
  evaluation?: Evaluation;
  loadedGame: LoadedGame | null;
}

export function ShareState({ fen, history, evaluation, loadedGame }: ShareStateProps) {
  const [copied, setCopied] = useState(false);

  function formatEval(eval_?: Evaluation): string {
    if (!eval_) return 'Not analyzed';
    if (eval_.type === 'mate') {
      return eval_.value > 0 ? `White mates in ${eval_.value}` : `Black mates in ${Math.abs(eval_.value)}`;
    }
    const pawns = eval_.value / 100;
    return `${pawns >= 0 ? '+' : ''}${pawns.toFixed(2)} (${
      Math.abs(pawns) < 0.3 ? 'equal' :
      Math.abs(pawns) < 1 ? 'slight edge' :
      Math.abs(pawns) < 2 ? 'clear advantage' : 'winning'
    } for ${pawns >= 0 ? 'White' : 'Black'})`;
  }

  function generateSummary(): string {
    const moves = loadedGame
      ? loadedGame.moves.slice(0, loadedGame.currentPly).map(m => m.san)
      : history;

    // Format moves in pairs
    let movesText = '';
    if (moves.length > 0) {
      const pairs: string[] = [];
      for (let i = 0; i < moves.length; i += 2) {
        const moveNum = Math.floor(i / 2) + 1;
        const white = moves[i];
        const black = moves[i + 1] || '';
        pairs.push(`${moveNum}. ${white}${black ? ' ' + black : ''}`);
      }
      movesText = pairs.join(' ');
    }

    const lines = [
      '=== Chess Position ===',
      '',
      `FEN: ${fen}`,
      '',
      `Evaluation: ${formatEval(evaluation)}`,
    ];

    if (movesText) {
      lines.push('', `Moves: ${movesText}`);
    }

    if (loadedGame) {
      lines.push('', `Game: ${loadedGame.white} vs ${loadedGame.black}`);
      if (loadedGame.result) lines.push(`Result: ${loadedGame.result}`);
      lines.push(`Position: Move ${loadedGame.currentPly} of ${loadedGame.moves.length}`);
    }

    lines.push('', '======================');

    return lines.join('\n');
  }

  async function handleCopy() {
    const summary = generateSummary();
    await navigator.clipboard.writeText(summary);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <button
      onClick={handleCopy}
      className="px-3 py-2 text-sm font-medium rounded-lg bg-purple-100 hover:bg-purple-200 text-purple-700 transition-colors"
      title="Copy game state to share with AI"
    >
      {copied ? '✓ Copied!' : '📋 Copy for AI'}
    </button>
  );
}
