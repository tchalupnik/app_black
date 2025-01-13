import { useState, useContext, memo } from 'react';
import axios from 'axios';
import { WebSocketContext } from '../App';
import { FaLightbulb, } from 'react-icons/fa';
import { RiOutletLine } from "react-icons/ri";

import { formatTimestamp } from '../utils/formatters';
import ViewToggle from './ViewToggle';
import { isIOState } from '../hooks/useWebSocket';

// Separate component for individual output
const OutputItem = memo(({ output, onToggle, isGrid, error }: {
  output: { name: string; state: string; type: string; timestamp?: number };
  onToggle: (name: string) => void;
  isGrid: boolean;
  error: string | null;
}) => {
  const Icon = output.type === 'switch' ? RiOutletLine : FaLightbulb;
  return (
  <div className={`bg-base-100 shadow rounded-lg p-4 ${isGrid ? '' : 'flex justify-between items-center'}`}>
    <div className={`flex items-center gap-3 ${isGrid ? 'mb-3' : ''}`}>
      <Icon className={`text-xl ${output.state === 'ON' ? 'text-yellow-400' : 'text-gray-400'}`} />
      <span className="text-lg">{output.name}</span>
    </div>
    <div className={`${isGrid ? '' : 'flex flex-col items-end gap-2'}`}>
      <label className="relative inline-flex items-center cursor-pointer">
        <input
          type="checkbox"
          className="sr-only peer"
          checked={output.state === 'ON'}
          disabled={error !== null}
          onChange={() => onToggle(output.name)}
        />
        <div className={`w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 
          peer-focus:ring-blue-300 dark:peer-focus:ring-blue-800 rounded-full peer 
          dark:bg-gray-700 peer-checked:after:translate-x-full peer-checked:after:border-white 
          after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white 
          after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 
          after:transition-all dark:border-gray-600 peer-checked:bg-blue-600`}></div>
      </label>
      <p className="text-gray-500 text-xs mt-2">
        {formatTimestamp(output.timestamp)}
      </p>
    </div>
  </div>
)});

export default function OutputsView({error}: {error: string | null}) {
  const [outputError, setError] = useState<string | null>(null);
  const { outputs } = useContext(WebSocketContext);
  const [isGrid, setIsGrid] = useState(() => {
    const saved = localStorage.getItem('outputViewMode');
    return saved ? saved === 'grid' : true;
  });

  const validOutputs = outputs.filter(isIOState);

  const handleViewToggle = (gridView: boolean) => {
    setIsGrid(gridView);
    localStorage.setItem('outputViewMode', gridView ? 'grid' : 'list');
  };

  const toggleOutput = async (name: string) => {
    try {
      await axios.post(`/api/outputs/${name}/toggle`);
      setError(null);
    } catch (error) {
      console.error('Error toggling output:', error);
      setError('Failed to toggle output');
    }
  };

  if (outputError) {
    return <div className="alert alert-error">{outputError}</div>;
  }

  return (
    <div className="container mx-auto p-4">
      <div className="card bg-base-200 shadow-xl">
        <div className="card-body">
          <div className="flex justify-between items-center mb-4">
            <h2 className="card-title">Controls</h2>
            <ViewToggle isGrid={isGrid} onToggle={handleViewToggle} />
          </div>
          <div className={isGrid 
            ? "grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4"
            : "flex flex-col gap-4"
          }>
            {validOutputs.map((output) => (
              <OutputItem 
                key={output.name}
                output={output}
                onToggle={toggleOutput}
                isGrid={isGrid}
                error={error}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
