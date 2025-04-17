import { useState, useContext, memo, useEffect, useCallback } from 'react';
import axios from 'axios';
import { WebSocketContext } from '../App';
import { FaLightbulb, FaArrowUp, FaArrowDown, FaStop } from 'react-icons/fa';
import { RiOutletLine } from "react-icons/ri";
import { MdBlindsClosed, MdBlinds } from "react-icons/md";
import { GiValve } from "react-icons/gi";

import { formatTimestamp } from '../utils/formatters';
import ViewToggle from './ViewToggle';
import { isIOState, isCoverState } from '../hooks/useWebSocket';

// Returns icon component and ON color for given type
function getIconAndOnColor(type: string): { Icon: React.ElementType, onColor: string } {
  switch (type) {
    case 'valve':
      return { Icon: GiValve, onColor: 'text-blue-500' };
    case 'switch':
      return { Icon: RiOutletLine, onColor: 'text-yellow-400' };
    case 'light':
      return { Icon: FaLightbulb, onColor: 'text-yellow-400' };
    case 'cover':
      return { Icon: MdBlinds, onColor: 'text-gray-400' };
    default:
      return { Icon: FaLightbulb, onColor: 'text-yellow-400' };
  }
}

// Separate component for individual output
const OutputItem = memo(({ output, onToggle, isGrid, error }: {
  output: { id: string; name: string; state: string; type: string; timestamp?: number };
  onToggle: (id: string, name: string, type: string) => void;
  isGrid: boolean;
  error: string | null;
}) => {
  if (output.type == "cover" || output.type == "none") {
    return <></>;
  }
  const { Icon, onColor } = getIconAndOnColor(output.type);
  return (
  <div className={`bg-base-100 shadow-sm rounded-lg p-4 ${isGrid ? '' : 'flex justify-between items-center'}`}>
    <div className={`flex items-center gap-3 ${isGrid ? 'mb-3' : ''}`}>
      <Icon className={`text-xl ${output.state === 'ON' ? onColor: 'text-gray-400'}`} />
      <span className="text-lg">{output.name}</span>
    </div>
    <div className={`${isGrid ? '' : 'flex flex-col items-end gap-2'}`}>
      <label className="relative inline-flex items-center cursor-pointer">
        <input
          type="checkbox"
          className="sr-only peer"
          checked={output.state === 'ON'}
          disabled={error !== null}
          onChange={() => onToggle(output.id, output.name, output.type)}
        />
        <div className={`w-11 h-6 bg-gray-200 peer-focus:outline-hidden peer-focus:ring-4 
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

const CoverItem = memo(({ cover, action, isGrid, error }: {
  cover: { id: string; name: string; state: string; position: number; current_operation: string; timestamp?: number };
  action: (id: string, name: string, action: string) => void;
  isGrid: boolean;
  error: string | null;
}) => {
  const Icon = cover.state === 'open' ? MdBlinds : MdBlindsClosed;
  const [sliderPosition, setSliderPosition] = useState<number>(cover.position);
  const [isSliderActive, setIsSliderActive] = useState<boolean>(false);
  
  // Update slider position when cover position changes (if not actively sliding)
  useEffect(() => {
    if (!isSliderActive) {
      setSliderPosition(cover.position);
    }
  }, [cover.position, isSliderActive]);
  
  // Debounce function for setting position
  const debouncedSetPosition = useCallback(() => {
    const timer = setTimeout(() => {
      if (sliderPosition !== cover.position) {
        axios.post(`/api/covers/${cover.id}/set_position`, { position: sliderPosition })
          .catch(error => console.error('Error setting cover position:', error));
      }
      setIsSliderActive(false);
    }, 300); // 0.3 second debounce
    
    return () => clearTimeout(timer);
  }, [sliderPosition, cover.id, cover.position]);
  
  // Set up debounce effect
  useEffect(() => {
    if (isSliderActive) {
      return debouncedSetPosition();
    }
  }, [isSliderActive, sliderPosition, debouncedSetPosition]);
  
  const handleSliderChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newPosition = parseInt(e.target.value, 10);
    setSliderPosition(newPosition);
    setIsSliderActive(true);
  };
  
  return (
  <div className={`bg-base-100 shadow-sm rounded-lg p-4 ${isGrid ? '' : 'flex justify-between items-center'}`}>
    <div className={`flex items-center gap-3 ${isGrid ? 'mb-3' : ''}`}>
      <Icon className={`text-xl ${cover.state === 'open' ? 'text-yellow-400' : 'text-gray-400'}`} />
      <span className="text-lg">{cover.name}</span>
      <span className="text-xs bg-gray-200 text-gray-700 px-2 py-1 rounded-full">
        {cover.current_operation || 'idle'} {cover.position !== undefined ? `(${cover.position}%)` : ''}
      </span>
    </div>
    <div className={`${isGrid ? 'mt-3' : 'flex flex-col items-end gap-2'}`}>
      <div className="flex gap-2">
        <button 
          className="px-3 py-1 bg-blue-500 hover:bg-blue-600 text-white rounded-md disabled:opacity-50 disabled:cursor-not-allowed"
          onClick={() => action(cover.id, cover.name, 'open')}
          disabled={error !== null || cover.current_operation === 'opening' || (cover.state === 'open' && cover.position === 100)}
        >
          <FaArrowUp />
        </button>
        <button 
          className="px-3 py-1 bg-gray-500 hover:bg-gray-600 text-white rounded-md disabled:opacity-50 disabled:cursor-not-allowed"
          onClick={() => action(cover.id, cover.name, 'stop')}
          disabled={error !== null || cover.current_operation === 'idle'}
        >
          <FaStop />
        </button>
        <button 
          className="px-3 py-1 bg-blue-500 hover:bg-blue-600 text-white rounded-md disabled:opacity-50 disabled:cursor-not-allowed"
          onClick={() => action(cover.id, cover.name, 'close')}
          disabled={error !== null || cover.current_operation === 'closing' || (cover.state === 'closed' && cover.position === 0)}
        >
          <FaArrowDown />
        </button>
      </div>
      
      <div className="w-full mt-3 bg-secondary p-2 rounded-lg">
        <div className="flex justify-between text-xs text-gray-500 mb-1">
          <span>0%</span>
          <span>100%</span>
        </div>
        <div className="relative pt-1">
          <input
            type="range"
            min="0"
            max="100"
            value={sliderPosition}
            onChange={handleSliderChange}
            disabled={error !== null || cover.current_operation !== 'idle'}
            className="range range-sm range-primary [--range-bg:orange] [--range-thumb:blue]"
          />
        </div>
        <div className="flex justify-between text-xs text-gray-500 my-1">
          <span>Close</span>
          <span>Open</span>
        </div>
      </div>
      
      <p className="text-gray-500 text-xs mt-2">
        {formatTimestamp(cover.timestamp)}
      </p>
    </div>
  </div>
)});

export default function OutputsView({error}: {error: string | null}) {
  const [outputError, setError] = useState<string | null>(null);
  const { outputs, covers } = useContext(WebSocketContext);
  const [isGrid, setIsGrid] = useState(() => {
    const saved = localStorage.getItem('outputViewMode');
    return saved ? saved === 'grid' : true;
  });

  const validOutputs = outputs.filter(isIOState);

  const handleViewToggle = (gridView: boolean) => {
    setIsGrid(gridView);
    localStorage.setItem('outputViewMode', gridView ? 'grid' : 'list');
  };

  const toggleOutput = async (id: string, name: string, type: string) => {
    try {
      const response = await axios.post(`/api/outputs/${id}/toggle`);
      console.log("re", response, type)
      if (response.data.status === 'interlock') {
        setError(`${type} ${name} is locked by interlock`);
        return;
      }
      setError(null);
    } catch (error) {
      console.error('Error toggling output:', error);
      setError('Failed to toggle output');
    }
  };

  const actionCover = async (id: string, name: string, action: string) => {
    try {
      await axios.post(`/api/covers/${id}/action`, { action });
      setError(null);
    } catch (error) {
      console.error(`Error controlling cover ${name}:`, error);
      setError(`Failed to control cover ${name}`);
    }
  };

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
                key={output.id}
                output={output}
                onToggle={toggleOutput}
                isGrid={isGrid}
                error={error}
              />
            ))}
          </div>
          <div className={isGrid 
            ? "grid grid-cols-1 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4"
            : "flex flex-col gap-4"
          }>
            {covers.filter(cover => isCoverState(cover)).map((cover) => (
              <CoverItem 
                key={cover.id}
                cover={cover as { id: string; name: string; state: string; position: number; current_operation: string; timestamp?: number }}
                action={actionCover}
                isGrid={isGrid}
                error={error}
              />
            ))}
          </div>
        </div>
      </div>
      {outputError && <div className='toast'><div className="alert alert-error">{outputError}</div></div>}
    </div>
  );
}
