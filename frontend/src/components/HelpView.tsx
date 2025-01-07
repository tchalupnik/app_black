import { useState, useEffect } from 'react';
import axios from 'axios';

export default function HelpView() {
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
    <div className="flex flex-col items-center justify-center h-full bg-base-300 p-4">
      <div className="max-w-lg text-center space-y-4">
        <h1 className="text-2xl font-bold mb-6">Thanks for using boneIO Black</h1>
        {version && (
          <p className="text-base-content/70 mb-4">Your app version: {version}</p>
        )}
        <p className="text-lg mb-4">We'd like to help you with your problems.</p>
        <p className="text-lg flex flex-col">
          Join our community on Discord and get help{' '}
          <a 
            href="https://discord.gg/Hm2CzSjvtu" 
            target="_blank" 
            rel="noopener noreferrer" 
            className="link link-primary"
          >
            https://discord.gg/Hm2CzSjvtu
          </a>
        </p>
        <p className="text-lg flex flex-col">
          Repository containing this app:{' '}
          <a 
            href="https://github.com/boneIO-eu/app_black" 
            target="_blank" 
            rel="noopener noreferrer" 
            className="link link-primary"
          >
            https://github.com/boneIO-eu/app_black
          </a>
        </p>
        <p className="text-lg flex flex-col">
          Documentation of application:{' '}
          <a 
            href="https://boneio.eu/docs/black" 
            target="_blank" 
            rel="noopener noreferrer" 
            className="link link-primary"
          >
            https://boneio.eu/docs/black
          </a>
        </p>
      </div>
    </div>
  );
}
