import { useContext, memo, useState } from 'react';
import { WebSocketContext } from '../App';
import { formatTimestamp } from '../utils/formatters';
import ViewToggle from './ViewToggle';
import { isSensorState } from '../hooks/useWebSocket';

// Separate component for individual sensor
const SensorItem = memo(({ sensor, isGrid }: {
  sensor: { name: string; id: string; state: number | string | null; unit?: string; timestamp?: number };
  isGrid: boolean;
}) => (
  <div
    className={`bg-secondary shadow-sm rounded-lg p-4 ${isGrid ? 'border-l-4' : 'border-l-8'} border-emerald-500`}
  >
    <div className={`flex ${isGrid ? 'justify-between items-start' : 'justify-between items-start'}`}>
      <div>
        <h3 className="font-semibold text-lg">{sensor.name}</h3>
        <p className="text-sm text-base-content/70">{sensor.id}</p>
      </div>
      <div className='text-right'>
        <div className="flex items-baseline gap-2 justify-end">
          <span className="text-2xl font-mono">
            {sensor.state !== null
              ? typeof sensor.state === 'number'
                ? sensor.state.toFixed(2)
                : sensor.state
              : 'N/A'}
          </span>
          {sensor.unit && (
            <span className="text-base-content/70">
              {sensor.unit}
            </span>
          )}
        </div>
        <p className="text-gray-500 text-xs mt-2">
          {formatTimestamp(sensor?.timestamp)}
        </p>
      </div>
    </div>
  </div>
));

export default function SensorView() {
  const { sensors } = useContext(WebSocketContext);
  const [isGrid, setIsGrid] = useState(() => {
    const saved = localStorage.getItem('sensorViewMode');
    return saved ? saved === 'grid' : true;
  });

  const validSensors = sensors.filter(isSensorState);

  const handleViewToggle = (gridView: boolean) => {
    setIsGrid(gridView);
    localStorage.setItem('sensorViewMode', gridView ? 'grid' : 'list');
  };

  return (
    <div className="container mx-auto p-4">
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-xl font-bold">Sensors</h2>
        <ViewToggle isGrid={isGrid} onToggle={handleViewToggle} />
      </div>
      <div className={isGrid
        ? "grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4 gap-4"
        : "flex flex-col gap-4"
      }>
        {validSensors.map((sensor) => (
          <SensorItem key={sensor.id} sensor={sensor} isGrid={isGrid} />
        ))}
      </div>
    </div>
  );
}
