import { useNavigate, useLocation } from 'react-router-dom';
import { FaCode, FaList, FaLightbulb, FaInbox, FaQuestionCircle, FaThermometerHalf, FaSignOutAlt } from 'react-icons/fa';
import ThemeChanger from './ThemeChanger';
import { useState, useEffect } from 'react';
import clsx from 'clsx';
import axios from 'axios';
import { useAuth } from '../hooks/useAuth';
import Logo from "./Logo"

export default function Navigation() {
  const { isAuthenticated, logout } = useAuth();
  const [version, setVersion] = useState<string>('');

  useEffect(() => {
    const fetchVersion = async () => {
      try {
        const response = await axios.get('/api/version');
        setVersion(response.data.version);
      } catch (error) {
        console.error('Error fetching version:', error);
      }
    };

    fetchVersion();
  }, []);

  return (
    <div className="navbar bg-base-200 border-b border-base-content/10 px-4 sticky top-0 z-30">
      <div className="flex-none lg:hidden">
        <label htmlFor="my-drawer" className="btn btn-square btn-ghost">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
            className="inline-block w-6 h-6 stroke-current"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth="2"
              d="M4 6h16M4 12h16M4 18h16"
            ></path>
          </svg>
        </label>
      </div>
      <div className="flex-1">
        <a className="normal-case text-xl lg:ml-2">
          <Logo />
        </a>
        {version && <span className="text-xs opacity-50 ml-2">v{version}</span>}
      </div>
      <Menu />
      <div className="flex-none gap-2">
        <ThemeChanger />
        {isAuthenticated && (
          <button
            onClick={logout}
            className="btn btn-ghost btn-circle"
            title="Logout"
          >
            <FaSignOutAlt className="h-5 w-5" />
          </button>
        )}
      </div>
    </div>
  );
}

function Menu({ sideMenu = false }: { sideMenu?: boolean }) {
  const navigate = useNavigate();

  const location = useLocation();

  const menuItems = [
    { path: '/', default: true, icon: FaLightbulb, label: 'Outputs' },
    { path: '/inputs', icon: FaInbox, label: 'Inputs' },
    { path: '/sensors', icon: FaThermometerHalf, label: 'Sensors' },
    { path: '/config', icon: FaCode, label: 'Config' },
    { path: '/logs', icon: FaList, label: 'Logs' },
    { path: '/help', icon: FaQuestionCircle, label: 'Help' },
  ];

  return (
    <ul className={clsx('menu', { 'menu-horizontal': !sideMenu })}>
      {menuItems.map((item) => (
        <li key={item.path}>
          <a
            onClick={() => navigate(item.path)}
            className={clsx({
              active: location.pathname === item.path || location.pathname === "/" && item?.default,
            })}
          >
            <item.icon className={clsx('h-5 w-5', { 'lg:hidden': !sideMenu })} />
            <span className={clsx({ 'hidden lg:inline': !sideMenu })}>
              {item.label}
            </span>
          </a>
        </li>
      ))}
    </ul>
  );
}

export const DrawerSide = () => {
  return (
  <div className='drawer-side z-40'>
    <label htmlFor="my-drawer" aria-label="close sidebar" className="drawer-overlay"></label>
    <div className='menu bg-base-200 text-base-content min-h-full w-48 p-4'>
      <Menu sideMenu={true} />
    </div>
  </div>)
  
}