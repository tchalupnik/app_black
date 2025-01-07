import { FaList, FaThLarge } from 'react-icons/fa';

interface ViewToggleProps {
  isGrid: boolean;
  onToggle: (isGrid: boolean) => void;
}

export default function ViewToggle({ isGrid, onToggle }: ViewToggleProps) {
  return (
    <div className="join">
      <button
        className={`btn btn-sm join-item ${!isGrid ? 'btn-active' : ''}`}
        onClick={() => onToggle(false)}
        title="List view"
      >
        <FaList />
      </button>
      <button
        className={`btn btn-sm join-item ${isGrid ? 'btn-active' : ''}`}
        onClick={() => onToggle(true)}
        title="Grid view"
      >
        <FaThLarge />
      </button>
    </div>
  );
}
