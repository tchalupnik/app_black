import { Link, useLocation } from 'react-router-dom';

export default function Sidebar() {
  const location = useLocation();
  const isActive = (path: string) => location.pathname === path;

  return (
    <div className="bg-base-200 w-80 min-h-full">
      <div className="p-4 border-b border-base-content/10">
        <h1 className="text-xl font-bold">BoneIO</h1>
      </div>

      <ul className="menu menu-lg p-4">
        <li>
          <Link
            to="/outputs"
            className={`flex items-center gap-2 ${isActive('/outputs') ? 'active' : ''}`}
          >
            <span className="text-lg">🔌</span>
            <span>Outputs</span>
          </Link>
        </li>
        <li>
          <Link
            to="/inputs"
            className={`flex items-center gap-2 ${isActive('/inputs') ? 'active' : ''}`}
          >
            <span className="text-lg">📡</span>
            <span>Inputs</span>
          </Link>
        </li>
        <li>
          <Link
            to="/config"
            className={`flex items-center gap-2 ${isActive('/config') ? 'active' : ''}`}
          >
            <span className="text-lg">⚙️</span>
            <span>Config</span>
          </Link>
        </li>
      </ul>
    </div>
  );
}
