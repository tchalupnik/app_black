import { useState, useEffect } from 'react';
import axios from 'axios';

// interface UpdateInfo {
//   status: string;
//   current_version: string;
//   latest_version: string;
//   update_available: boolean;
//   release_url?: string;
//   published_at?: string;
//   is_prerelease?: boolean;
//   message?: string;
// }

export default function HelpView() {
  const [version, setVersion] = useState<string>('');
  // const [isUpdating, setIsUpdating] = useState(false);
  // const [updateStatus, setUpdateStatus] = useState<string | null>(null);
  // const [updateProgress, setUpdateProgress] = useState<number>(0);
  // const [updateInfo, setUpdateInfo] = useState<UpdateInfo | null>(null);
  // const [isCheckingUpdate, setIsCheckingUpdate] = useState(false);

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

  // const checkForUpdates = async () => {
  //   try {
  //     setIsCheckingUpdate(true);
  //     setUpdateStatus('Sprawdzanie dostępności aktualizacji...');
      
  //     const response = await axios.get('/api/check_update');
  //     setUpdateInfo(response.data);
      
  //     if (response.data.status === 'success') {
  //       if (response.data.update_available) {
  //         setUpdateStatus(`Dostępna jest nowa wersja: ${response.data.latest_version}`);
  //       } else {
  //         setUpdateStatus('Masz już najnowszą wersję aplikacji.');
  //       }
  //     } else {
  //       setUpdateStatus(`Błąd sprawdzania aktualizacji: ${response.data.message}`);
  //     }
  //   } catch (error) {
  //     console.error('Error checking for updates:', error);
  //     setUpdateStatus('Błąd podczas sprawdzania dostępności aktualizacji');
  //   } finally {
  //     setIsCheckingUpdate(false);
  //   }
  // };

  // const startUpdate = async () => {
  //   // Jeśli nie sprawdziliśmy jeszcze aktualizacji, zróbmy to najpierw
  //   if (!updateInfo) {
  //     await checkForUpdates();
  //     // Po sprawdzeniu musimy ponownie sprawdzić stan updateInfo
  //     // Musimy zaczekać na zakończenie asynchronicznego checkForUpdates
  //     // i ponownie sprawdzić stan
  //     return;
  //   }
    
  //   // Jeśli już sprawdziliśmy i nie ma aktualizacji, nie kontynuuj
  //   if (!updateInfo.update_available) {
  //     setUpdateStatus('Masz już najnowszą wersję aplikacji.');
  //     return;
  //   }
    
  //   try {
  //     setIsUpdating(true);
  //     setUpdateStatus('Rozpoczynanie aktualizacji...');
  //     setUpdateProgress(10);
      
  //     const response = await axios.post('/api/update');
      
  //     if (response.data.status === 'success') {
  //       setUpdateStatus('Aktualizacja w toku...');
  //       setUpdateProgress(30);
  //       checkUpdateStatus();
  //     } else {
  //       setUpdateStatus(`Błąd: ${response.data.message || 'Nieznany błąd'}`);
  //       setIsUpdating(false);
  //     }
  //   } catch (error) {
  //     console.error('Error starting update:', error);
  //     setUpdateStatus('Błąd podczas uruchamiania aktualizacji');
  //     setIsUpdating(false);
  //   }
  // };

  // const checkUpdateStatus = () => {
  //   let attempts = 0;
  //   const maxAttempts = 30; // 5 minut (10 sekund * 30)
  //   const interval = setInterval(async () => {
  //     try {
  //       // Sprawdź, czy serwer jest dostępny
  //       const response = await axios.get('/api/version');
        
  //       // Jeśli serwer odpowiada, to znaczy, że restart się zakończył
  //       setUpdateProgress(100);
  //       setUpdateStatus('Aktualizacja zakończona pomyślnie!');
  //       setIsUpdating(false);
  //       clearInterval(interval);
  //     } catch (error) {
  //       // Serwer jest w trakcie restartu
  //       attempts++;
  //       setUpdateProgress(30 + Math.min(60, attempts * 2)); // Maksymalnie do 90%
        
  //       if (attempts >= maxAttempts) {
  //         setUpdateStatus('Upłynął limit czasu aktualizacji. Sprawdź status ręcznie.');
  //         setIsUpdating(false);
  //         clearInterval(interval);
  //       }
  //     }
  //   }, 10000); // Sprawdzaj co 10 sekund
  // };

  // Sprawdź aktualizacje przy pierwszym załadowaniu komponentu
  // useEffect(() => {
  //   checkForUpdates();
  // }, []);

  // Formatowanie daty publikacji
  // const formatDate = (dateString?: string) => {
  //   if (!dateString) return '';
    
  //   const date = new Date(dateString);
  //   return date.toLocaleDateString('pl-PL', {
  //     year: 'numeric',
  //     month: 'long',
  //     day: 'numeric',
  //     hour: '2-digit',
  //     minute: '2-digit'
  //   });
  // };

  return (
    <div className="flex flex-col items-center justify-center h-full bg-base-300 p-4">
      <div className="max-w-lg text-center space-y-4">
        <h1 className="text-2xl font-bold mb-6">Thanks for using boneIO Black</h1>
        {version && (
          <p className="text-base-content/70 mb-4">Your app version: {version}</p>
        )}
        
        {/* Informacja o aktualizacji */}
        {/* {updateInfo && updateInfo.status === 'success' && (
          <div className="card bg-base-100 shadow-xl mb-4 p-4">
            <div className="card-body p-4">
              <h2 className="card-title justify-center mb-2">Informacje o wersji</h2>
              <div className="grid grid-cols-2 gap-1 text-sm">
                <div className="text-left font-semibold">Aktualna wersja:</div>
                <div className="text-right">{updateInfo.current_version}</div>
                
                <div className="text-left font-semibold">Najnowsza wersja:</div>
                <div className="text-right">{updateInfo.latest_version}</div>
                
                {updateInfo.published_at && (
                  <>
                    <div className="text-left font-semibold">Data publikacji:</div>
                    <div className="text-right">{formatDate(updateInfo.published_at)}</div>
                  </>
                )}
                
                {updateInfo.is_prerelease !== undefined && (
                  <>
                    <div className="text-left font-semibold">Typ wydania:</div>
                    <div className="text-right">
                      {updateInfo.is_prerelease ? 'Wersja testowa' : 'Wersja stabilna'}
                    </div>
                  </>
                )}
              </div>
              
              <div className="mt-3">
                <p className={updateInfo.update_available ? "text-success font-bold" : "text-info"}>
                  {updateInfo.update_available 
                    ? "Dostępna jest nowa wersja!" 
                    : "Masz najnowszą wersję."}
                </p>
              </div>
              
              {updateInfo.release_url && (
                <div className="card-actions justify-center mt-2">
                  <a 
                    href={updateInfo.release_url} 
                    target="_blank" 
                    rel="noopener noreferrer"
                    className="link link-primary text-sm"
                  >
                    Zobacz szczegóły wydania na GitHub
                  </a>
                </div>
              )}
            </div>
          </div>
        )} */}
        
        {/* Przyciski aktualizacji */}
        {/* <div className="my-4 flex flex-col items-center">
          <div className="flex gap-2 mb-4">
            <button 
              onClick={checkForUpdates} 
              disabled={isCheckingUpdate || isUpdating}
              className="btn btn-outline btn-info"
            >
              {isCheckingUpdate ? 'Sprawdzanie...' : 'Sprawdź aktualizacje'}
            </button>
            
            <button 
              onClick={startUpdate} 
              disabled={!!(isUpdating || isCheckingUpdate || (updateInfo && !updateInfo.update_available))}
              className="btn btn-primary"
            >
              {isUpdating ? 'Aktualizacja w toku...' : 'Aktualizuj BoneIO'}
            </button>
          </div>
          
          {updateStatus && (
            <div className="text-sm mt-2">{updateStatus}</div>
          )}
          
          {isUpdating && (
            <div className="w-full mt-4">
              <progress 
                className="progress progress-primary w-full" 
                value={updateProgress} 
                max="100"
              ></progress>
            </div>
          )}
        </div> */}
        
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
