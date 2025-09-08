import { useEffect, useState } from 'react';
import { FaSun, FaMoon } from 'react-icons/fa';

export default function ThemeChanger() {
  const [theme, setTheme] = useState('dark');

  useEffect(() => {
    const savedTheme = localStorage.getItem('theme') || 'dark';
    setTheme(savedTheme);
    document.documentElement.setAttribute('data-theme', savedTheme);
  }, []);

  const handleThemeChange = () => {
    const newTheme = theme === 'dark' ? 'light' : 'dark';
    setTheme(newTheme);
    document.documentElement.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);
  };

  return (
<div className='flex-none items-center lg:block '>
    <button className="btn btn-ghost font-normal" onClick={() => handleThemeChange()}>
      {theme === 'dark' ? (
      <FaSun className="w-5 h-5" />
    ) : (
      <FaMoon className="w-5 h-5" />
    )}
    </button>
    </div>
  );
}
