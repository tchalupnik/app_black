import { ReactNode } from 'react';
// import Sidebar from './Sidebar';
import Navigation, { DrawerSide } from './Navigation';

interface LayoutProps {
  children: ReactNode;
}

// const pathTitles: Record<string, string> = {
//   '/': 'Outputs',
//   '/outputs': 'Outputs',
//   '/inputs': 'Inputs',
//   '/config': 'Configuration'
// };


export default function Layout({ children }: LayoutProps) {
  // const location = useLocation();
  // const title = pathTitles[location.pathname] || 'BoneIOA';

  return (
    <div className="w-full max-w-screen h-screen drawer">
      <input id="my-drawer" type="checkbox" className="drawer-toggle" />
      
      <div className="flex flex-col drawer-content">
        <Navigation />
        <main className="flex-1 overflow-y-auto bg-base-100">
          {children}
        </main>
      </div>
      <DrawerSide />
    </div>
  );
}
