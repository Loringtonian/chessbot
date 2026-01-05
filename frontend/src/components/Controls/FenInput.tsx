/**
 * FEN position input component.
 */

import { useState } from 'react';

interface FenInputProps {
  currentFen: string;
  onSetPosition: (fen: string) => boolean;
}

export function FenInput({ currentFen, onSetPosition }: FenInputProps) {
  const [fen, setFen] = useState('');
  const [error, setError] = useState('');

  function handleSubmit() {
    const trimmed = fen.trim();
    if (!trimmed) return;

    const success = onSetPosition(trimmed);
    if (success) {
      setFen('');
      setError('');
    } else {
      setError('Invalid FEN position');
    }
  }

  function handleCopy() {
    navigator.clipboard.writeText(currentFen);
  }

  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        <input
          type="text"
          value={fen}
          onChange={(e) => {
            setFen(e.target.value);
            setError('');
          }}
          placeholder="Paste FEN position..."
          className="flex-1 px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <button
          onClick={handleSubmit}
          disabled={!fen.trim()}
          className="px-3 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
        >
          Set
        </button>
      </div>
      {error && <p className="text-xs text-red-500">{error}</p>}
      <div className="flex items-center gap-2 text-xs text-gray-500">
        <span className="truncate flex-1 font-mono">{currentFen}</span>
        <button
          onClick={handleCopy}
          className="text-blue-600 hover:underline whitespace-nowrap"
        >
          Copy FEN
        </button>
      </div>
    </div>
  );
}
