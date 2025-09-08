import { useApiAvailability } from "../hooks/useApiAvailability";
import { useCountdown } from "../hooks/useCountdown";

const NotAvailable = () => {
    const { isChecking, nextCheckTime, checkNow } = useApiAvailability();
    const secondsLeft = useCountdown(nextCheckTime);

    return (<div className="fixed inset-0 flex items-center justify-center z-50">
        <div className="p-8 text-center">
          <div className="loading loading-dots loading-lg mb-4"></div>
          <h2 className="text-xl font-bold mb-4">
            API unavailable
          </h2>
          <p className="text-base-content/70 mb-4">
            {isChecking ? 'Checking if service is back online...' :
              `Next check in ${secondsLeft} seconds`}
          </p>
          <button
            onClick={checkNow}
            disabled={isChecking}
            className="btn btn-primary"
          >
            {isChecking ? 'Checking...' : 'Check Now'}
          </button>
        </div>
      </div>)
}

export default NotAvailable
