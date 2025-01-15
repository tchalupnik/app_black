import asyncio
import datetime as dt
import logging
import time
from datetime import datetime
from typing import Any, Callable, Coroutine, List, Optional

from boneio.helper.util import callback
from boneio.models import OutputState

_LOGGER = logging.getLogger(__name__)
UTC = dt.timezone.utc
EVENT_TIME_CHANGED = "event_time_changed"
CALLBACK_TYPE = Callable[[], None]


def utcnow() -> dt.datetime:
    return dt.datetime.now(UTC)


time_tracker_utcnow = utcnow


def _async_create_timer(
    loop: asyncio.AbstractEventLoop, event_callback
) -> CALLBACK_TYPE:
    """Create a timer that will start on BoneIO start."""
    handle = None

    def schedule_tick(now: dt.datetime) -> None:
        """Schedule a timer tick when the next second rolls around."""
        nonlocal handle
        slp_seconds = 1 - (now.microsecond / 10**6)
        handle = loop.call_later(slp_seconds, fire_time_event)

    def fire_time_event() -> None:
        """Fire next time event."""
        now = utcnow()
        event_callback(now)
        schedule_tick(now)

    def stop_timer() -> None:
        """Stop the timer."""
        if handle is not None:
            handle.cancel()

    schedule_tick(utcnow())
    return stop_timer


class GracefulExit(SystemExit):
    """Graceful exit."""

    def __init__(self, msg=None, code=None):
        super(GracefulExit, self).__init__(msg)
        self.code = code


class ListenerJob:
    """Listener to represent jobs during runtime."""

    def __init__(self, target) -> None:
        """Initialize listener."""
        self.target = target
        self._handle = None

    def add_handle(self, handle):
        """Add handle to listener."""
        self._handle = handle

    def set_target(self, target) -> None:
        """Set target."""
        self.target = target

    @property
    def handle(self):
        """Return handle."""
        return self._handle


class EventBus:
    """Simple event bus which ticks every second."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        """Initialize handler"""
        self._loop = loop or asyncio.get_event_loop()
        self._every_second_listeners = {}
        self._output_listeners = {}
        self._event_listeners = {
            "input": {},
            "output": {},
            "modbus_sensor": {},
            "sensor": {},
            "host": {}
        }
        # Index to track listener_ids across all event types
        self._listener_id_index = {}
        self._sigterm_listeners = []
        self._haonline_listeners = []
        self._timer_handle = _async_create_timer(
            self._loop, self._run_second_event
        )
        self._shutting_down = False
        self._monitor_task = None

    async def start(self):
        """Start the event bus monitor."""
        self._monitor_task = asyncio.create_task(self._monitor_loop())

    async def _monitor_loop(self):
        """Monitor loop that can be cancelled for cleanup."""
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            _LOGGER.info("Monitor loop cancelled, cleaning up...")
            await self.ask_stop()
            raise

    def request_stop(self):
        """Request the event bus to stop."""
        if self._monitor_task and not self._shutting_down:
            self._shutting_down = True
            self._monitor_task.cancel()

    async def ask_stop(self):
        """Function to call on restart. Should invoke all sigterm listeners."""
        if self._shutting_down:
            return
        self._shutting_down = True
        self._every_second_listeners = {}
        self._output_listeners = {}
        
        await self._handle_sigterm_listeners()
        for listener in self._every_second_listeners.values():
            listener.target()
        _LOGGER.info("Shutdown Eventbus gracefully.")

    def _run_second_event(self, time):
        """Run event every second."""
        for key, listener in self._every_second_listeners.items():
            if listener.target:
                self._every_second_listeners[key].add_handle(
                    self._loop.call_soon(listener.target, time)
                )

    def _timer_handle(self):
        """Handle timer event."""
        time = datetime.now()
        for listener in self._every_second_listeners.values():
            self._loop.call_soon(listener.target, time)

    async def _handle_sigterm_listeners(self):
        """Handle all sigterm listeners, supporting both async and sync listeners."""
        for target in self._sigterm_listeners:
            try:
                _LOGGER.debug("Invoking sigterm listener %s", target)
                if asyncio.iscoroutinefunction(target):
                    await target()
                else:
                    target()
            except Exception as e:
                _LOGGER.error("Error in sigterm listener %s: %s", target, e)

    def ask_exit(self):
        """Function to call on exit. Should invoke all sigterm listeners."""
        if self._shutting_down:
            return
        self._shutting_down = True
        _LOGGER.debug("EventBus Exiting process started.")

        def task_done_callback(task):
            task.result()  # Retrieve the result to handle any raised exception
            raise asyncio.CancelledError
        
        async def cleanup_and_exit():
            try:
                await asyncio.sleep(2)
                await self.ask_stop()
            except Exception as e:
                _LOGGER.error(f"Error during cleanup: {e}")
        
        # Create and run the cleanup task
        exit_task = self._loop.create_task(cleanup_and_exit())
        exit_task.add_done_callback(task_done_callback)
        
        


    def add_every_second_listener(self, name, target):
        """Add listener on every second job."""
        self._every_second_listeners[name] = ListenerJob(target=target)
        return self._every_second_listeners[name]

    def add_sigterm_listener(self, target):
        """Add sigterm listener."""
        self._sigterm_listeners.append(target)

    def add_output_listener(self, output_id, listener_id, target) -> ListenerJob:
        """Add output listener.

        listener_id is typically group_id for group outputs or ws (websocket)
        """
        if output_id not in self._output_listeners:
            self._output_listeners[output_id] = {}
        if listener_id in self._output_listeners[output_id]:
            listener = self._output_listeners[output_id][listener_id]
            listener.set_target(target)
            return listener
        self._output_listeners[output_id][listener_id] = ListenerJob(target=target)
        return self._output_listeners[output_id][listener_id]

    def remove_output_listener(self, output_id, listener_id):
        """Add output listener.

        listener_id is typically group_id for group outputs or ws (websocket)
        """
        if output_id in self._output_listeners and listener_id in self._output_listeners[output_id]:
            del self._output_listeners[output_id][listener_id]

    async def async_trigger_output_event(self, output_id: str, event: OutputState):
        listeners = self._output_listeners.get(output_id, {})
        for listener in listeners.values():
            await listener.target(event)

    async def async_trigger_event(self, event_type: str, entity_id: str, event: Any):
        """Trigger event for all listeners of given type and entity."""
        listeners = self._event_listeners.get(event_type, {}).get(entity_id, {})
        for listener in listeners.values():
            await listener.target(event)

    def add_event_listener(
        self, event_type: str, entity_id: str, listener_id: str, target
    ) -> ListenerJob:
        """Add event listener.

        listener_id is typically group_id for group outputs or ws (websocket)
        """
        if not target:
            return
        if entity_id not in self._event_listeners[event_type]:
            self._event_listeners[event_type][entity_id] = {}
        if listener_id in self._event_listeners[event_type][entity_id]:
            listener = self._event_listeners[event_type][entity_id][listener_id]
            listener.set_target(target)
            return listener

        # Add to main listeners
        listener_job = ListenerJob(target=target)
        self._event_listeners[event_type][entity_id][listener_id] = listener_job

        # Add to index
        if listener_id not in self._listener_id_index:
            self._listener_id_index[listener_id] = []
        self._listener_id_index[listener_id].append((event_type, entity_id))

        return listener_job

    def remove_event_listener(self, event_type: str = None, entity_id: str = None, listener_id: str = None) -> None:
        """Remove event listener. Can remove by event_type, listener_id, or both."""
        if listener_id and listener_id in self._listener_id_index:
            # Remove by listener_id
            for evt_type, ent_id in self._listener_id_index[listener_id]:
                if event_type and evt_type != event_type:
                    continue
                if entity_id and ent_id != entity_id:
                    continue
                if ent_id in self._event_listeners[evt_type]:
                    if listener_id in self._event_listeners[evt_type][ent_id]:
                        del self._event_listeners[evt_type][ent_id][listener_id]
                    if not self._event_listeners[evt_type][ent_id]:
                        del self._event_listeners[evt_type][ent_id]
            
            if event_type is None and entity_id is None:
                # If removing all references to this listener_id
                del self._listener_id_index[listener_id]
            else:
                # Update index to remove only specific references
                self._listener_id_index[listener_id] = [
                    (evt_type, ent_id) 
                    for evt_type, ent_id in self._listener_id_index[listener_id]
                    if (event_type and evt_type != event_type) or (entity_id and ent_id != entity_id)
                ]
                if not self._listener_id_index[listener_id]:
                    del self._listener_id_index[listener_id]

        elif event_type:
            # Remove by event_type
            if entity_id:
                # Remove specific entity
                if entity_id in self._event_listeners[event_type]:
                    for lid in list(self._event_listeners[event_type][entity_id].keys()):
                        self.remove_event_listener(event_type, entity_id, lid)
                    del self._event_listeners[event_type][entity_id]
            else:
                # Remove entire event_type
                for ent_id in list(self._event_listeners[event_type].keys()):
                    for lid in list(self._event_listeners[event_type][ent_id].keys()):
                        self.remove_event_listener(event_type, ent_id, lid)

    def add_haonline_listener(self, target: Callable) -> None:
        """Add HA Online listener."""
        self._haonline_listeners.append(target)

    def signal_ha_online(self):
        """Call events if HA goes online."""
        for target in self._haonline_listeners:
            target()

    def remove_every_second_listener(self, name: str) -> None:
        """Remove regular listener."""
        if name in self._every_second_listeners:
            del self._every_second_listeners[name]


def as_utc(dattim: dt.datetime) -> dt.datetime:
    """Return a datetime as UTC time.

    Assumes datetime without tzinfo to be in the DEFAULT_TIME_ZONE.
    """
    if dattim.tzinfo == UTC:
        return dattim
    return dattim.astimezone(UTC)


@callback
def async_track_point_in_time(
    loop: asyncio.AbstractEventLoop,
    action,
    point_in_time: datetime,
) -> CALLBACK_TYPE:
    """Add a listener that fires once after a specific point in UTC time."""
    # Ensure point_in_time is UTC
    utc_point_in_time = as_utc(point_in_time)
    expected_fire_timestamp = utc_point_in_time.timestamp()

    # Since this is called once, we accept a so we can avoid
    # having to figure out how to call the action every time its called.
    cancel_callback: Optional[asyncio.TimerHandle] = None

    @callback
    def run_action(job) -> None:
        """Call the action."""
        nonlocal cancel_callback

        # Depending on the available clock support (including timer hardware
        # and the OS kernel) it can happen that we fire a little bit too early
        # as measured by utcnow(). That is bad when callbacks have assumptions
        # about the current time. Thus, we rearm the timer for the remaining
        # time.
        delta = expected_fire_timestamp - time.time()
        if delta > 0:
            _LOGGER.debug("Called %f seconds too early, rearming", delta)

            cancel_callback = loop.call_later(delta, run_action, job)
            return

        loop.call_soon(job, utc_point_in_time)

    delta = expected_fire_timestamp - time.time()
    cancel_callback = loop.call_later(delta, run_action, action)

    @callback
    def unsub_point_in_time_listener() -> None:
        """Cancel the call_later."""
        assert cancel_callback is not None
        cancel_callback.cancel()

    return unsub_point_in_time_listener


@callback
def async_track_point_in_timestamp(
    loop: asyncio.AbstractEventLoop,
    action,
    timestamp: float,
) -> CALLBACK_TYPE:
    """Add a listener that fires once after a specific point in UTC time."""
    # Since this is called once, we accept a so we can avoid
    # having to figure out how to call the action every time its called.
    cancel_callback: Optional[asyncio.TimerHandle] = None

    @callback
    def run_action(job) -> None:
        """Call the action."""
        nonlocal cancel_callback

        now = time.time()

        # Depending on the available clock support (including timer hardware
        # and the OS kernel) it can happen that we fire a little bit too early
        # as measured by utcnow(). That is bad when callbacks have assumptions
        # about the current time. Thus, we rearm the timer for the remaining
        # time.
        delta = timestamp - now
        if delta > 0:
            _LOGGER.debug("Called %f seconds too early, rearming", delta)

            cancel_callback = loop.call_later(delta, run_action, job)
            return

        loop.call_soon(job, timestamp)

    now = time.time()
    delta = timestamp - now
    cancel_callback = loop.call_later(delta, run_action, action)

    @callback
    def unsub_point_in_time_listener() -> None:
        """Cancel the call_later."""
        assert cancel_callback is not None
        cancel_callback.cancel()

    return unsub_point_in_time_listener


@callback
def async_call_later_miliseconds(
    loop: asyncio.AbstractEventLoop,
    action,
    delay: float,
) -> CALLBACK_TYPE:
    """Add a listener that fires once after a specific point in UTC time."""
    # Ensure point_in_time is UTC
    expected_fire_timestamp = time.time() + (delay / 1000)
    return async_track_point_in_timestamp(
        loop=loop, action=action, timestamp=expected_fire_timestamp
    )


def create_unawaited_task_threadsafe(
    loop: asyncio.AbstractEventLoop,
    transient_tasks: List["asyncio.Task[Any]"],
    coro: Coroutine[Any, Any, None],
    task_future: Optional["asyncio.Future[asyncio.Task[Any]]"] = None,
) -> None:
    """
    Schedule a coroutine on the loop and add the Task to transient_tasks.
    """

    def callback() -> None:
        task = loop.create_task(coro)
        transient_tasks.append(task)
        if task_future is not None:
            task_future.set_result(task)

    loop.call_soon_threadsafe(callback)
